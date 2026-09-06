"""ACP authentication and explicit API-grant security tests."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr

from zenith_harness.acp_auth import (
    ACPAuthContext,
    ACPAuthError,
    ResolvedApiGrant,
    SUBSCRIPTION_CODEX_CONFIG,
    api_grant_receipt,
    build_acp_subprocess_env,
    prepare_acp_auth_context,
    sanitized_process_env,
)
from zenith_harness.acp_runner import (
    ACPNodeRunner,
    _enforce_api_grant_expiry,
    _write_api_authorization_receipt,
)
from zenith_harness.assets import AssetLoader
from zenith_harness.config import HarnessConfig
from zenith_harness.models import ApiGrantRequest, BillingPolicy, Task
from zenith_harness.providers import PROVIDERS


def _config(harness_home: Path, grants_file: Path | None = None) -> HarnessConfig:
    bundled = Path(__file__).resolve().parents[1] / "src" / "zenith_harness" / "bundled"
    return HarnessConfig(
        bundled_dir=bundled,
        harness_home=harness_home,
        projects_dir=harness_home / "projects",
        orchestrator_provider_name="codex",
        worker_provider_name="codex",
        worker_acp_command="codex-acp",
        validator_provider_name=None,
        validator_acp_command=None,
        terminal_reviewer_provider_name=None,
        terminal_reviewer_acp_command=None,
        api_grants_file=grants_file,
    )


def _api_task(*, expires_at: datetime, max_usd: str = "5.00") -> Task:
    return Task(
        id="w-api",
        type="work",
        body="explicitly approved API operation",
        targets=["VAL-API"],
        skill="api-worker",
        billing=BillingPolicy(
            mode="api",
            api_grant=ApiGrantRequest(
                grant_id="grant-001",
                api_project="isolated-api-project",
                max_usd=Decimal(max_usd),
                expires_at=expires_at,
            ),
        ),
    )


def _write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def _write_registry(
    path: Path,
    credential_file: Path,
    *,
    issued_at: datetime,
    expires_at: datetime,
    max_usd: str = "5.00",
    revoked: bool = False,
) -> None:
    payload = {
        "version": 1,
        "grants": [
            {
                "grant_id": "grant-001",
                "zenith_project_id": "project-001",
                "mission_id": "mission-001",
                "task_id": "w-api",
                "provider": "codex",
                "api_project": "isolated-api-project",
                "max_usd": max_usd,
                "issued_at": issued_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "approved_by": "operator@example",
                "credential_file": str(credential_file),
                "revoked": revoked,
            }
        ],
    }
    _write_private(path, json.dumps(payload))


def test_subscription_is_default_and_strips_all_ambient_credentials(
    monkeypatch: pytest.MonkeyPatch, harness_home: Path
) -> None:
    sentinels = {
        "OPENAI_API_KEY": "sentinel-openai",
        "CODEX_API_KEY": "sentinel-codex",
        "CODEX_ACCESS_TOKEN": "sentinel-access",
        "ANTHROPIC_API_KEY": "sentinel-anthropic",
        "DEFAULT_AUTH_REQUEST": "sentinel-auth-request",
        "SOME_OTHER_SECRET": "sentinel-secret",
    }
    for name, value in sentinels.items():
        monkeypatch.setenv(name, value)

    task = Task(id="w1", type="work", body="work", targets=["VAL-1"], skill="s")
    context = prepare_acp_auth_context(
        config=_config(harness_home),
        provider=PROVIDERS["codex"],
        task=task,
        project_id="project-001",
        mission_id="mission-001",
    )
    env = build_acp_subprocess_env(PROVIDERS["codex"], context)

    assert task.billing.mode == "subscription"
    assert context.mode == "subscription"
    assert env["HOME"] == str(harness_home / "codex-subscription")
    assert env["CODEX_HOME"] == env["HOME"]
    assert all(name not in env for name in sentinels)
    assert "CODEX_SANDBOX" not in env
    assert "CODEX_DISABLE_SANDBOX" not in env
    assert context.codex_home is not None
    assert (context.codex_home / "config.toml").read_text() == SUBSCRIPTION_CODEX_CONFIG


def test_subscription_profile_rejects_persistent_api_auth(harness_home: Path) -> None:
    home = harness_home / "codex-subscription"
    home.mkdir()
    _write_private(
        home / "auth.json",
        json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": "must-not-survive"}),
    )
    task = Task(id="w1", type="work", body="work", targets=["VAL-1"], skill="s")

    with pytest.raises(ACPAuthError, match="not authenticated with ChatGPT"):
        prepare_acp_auth_context(
            config=_config(harness_home),
            provider=PROVIDERS["codex"],
            task=task,
            project_id="project-001",
            mission_id="mission-001",
        )


def test_ambient_old_snapshot_is_not_reused(
    monkeypatch: pytest.MonkeyPatch, harness_home: Path, tmp_path: Path
) -> None:
    ambient_home = tmp_path / "ambient-codex"
    snapshot = ambient_home / "shell_snapshots" / "old.sh"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("export OPENAI_API_KEY=stale-key\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(ambient_home))
    monkeypatch.setenv("OPENAI_API_KEY", "stale-key")

    task = Task(id="w1", type="work", body="work", targets=["VAL-1"], skill="s")
    context = prepare_acp_auth_context(
        config=_config(harness_home),
        provider=PROVIDERS["codex"],
        task=task,
        project_id="project-001",
        mission_id="mission-001",
    )
    env = build_acp_subprocess_env(PROVIDERS["codex"], context)

    assert env["CODEX_HOME"] != str(ambient_home)
    assert "OPENAI_API_KEY" not in env
    assert context.codex_home is not None
    assert not (context.codex_home / "shell_snapshots").exists()


def test_managed_subscription_home_rejects_new_snapshots(harness_home: Path) -> None:
    snapshots = harness_home / "codex-subscription" / "shell_snapshots"
    snapshots.mkdir(parents=True)
    (snapshots / "unexpected.sh").write_text("export TOKEN=unexpected\n", encoding="utf-8")
    task = Task(id="w1", type="work", body="work", targets=["VAL-1"], skill="s")

    with pytest.raises(ACPAuthError, match="forbidden shell snapshots"):
        prepare_acp_auth_context(
            config=_config(harness_home),
            provider=PROVIDERS["codex"],
            task=task,
            project_id="project-001",
            mission_id="mission-001",
        )


def test_managed_subscription_config_cannot_be_overridden(harness_home: Path) -> None:
    home = harness_home / "codex-subscription"
    home.mkdir()
    _write_private(home / "config.toml", 'forced_login_method = "api"\n')
    task = Task(id="w1", type="work", body="work", targets=["VAL-1"], skill="s")

    with pytest.raises(ACPAuthError, match="differs from the required profile"):
        prepare_acp_auth_context(
            config=_config(harness_home),
            provider=PROVIDERS["codex"],
            task=task,
            project_id="project-001",
            mission_id="mission-001",
        )


def test_api_request_without_operator_registry_fails_closed(harness_home: Path) -> None:
    now = datetime.now(UTC)
    with pytest.raises(ACPAuthError, match="ZENITH_API_GRANTS_FILE"):
        prepare_acp_auth_context(
            config=_config(harness_home),
            provider=PROVIDERS["codex"],
            task=_api_task(expires_at=now + timedelta(hours=1)),
            project_id="project-001",
            mission_id="mission-001",
            now=now,
        )


def test_exact_operator_grant_injects_only_scoped_key_and_emits_safe_receipt(
    monkeypatch: pytest.MonkeyPatch, harness_home: Path, tmp_path: Path
) -> None:
    now = datetime.now(UTC)
    expires_at = now + timedelta(hours=1)
    key = "test-explicit-api-key"
    credential_file = tmp_path / "openai.key"
    grants_file = tmp_path / "grants.json"
    _write_private(credential_file, key + "\n")
    _write_registry(
        grants_file,
        credential_file,
        issued_at=now - timedelta(minutes=1),
        expires_at=expires_at,
    )
    monkeypatch.setenv("OPENAI_API_KEY", "wrong-ambient-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "wrong-provider-key")

    context = prepare_acp_auth_context(
        config=_config(harness_home, grants_file),
        provider=PROVIDERS["codex"],
        task=_api_task(expires_at=expires_at),
        project_id="project-001",
        mission_id="mission-001",
        now=now,
    )
    env = build_acp_subprocess_env(PROVIDERS["codex"], context)
    receipt = api_grant_receipt(context)

    assert context.mode == "api"
    assert env["OPENAI_API_KEY"] == key
    assert env["CODEX_HOME"] == str(harness_home / "codex-api" / "grant-001")
    assert "ANTHROPIC_API_KEY" not in env
    assert key not in json.dumps(receipt)
    assert receipt == {
        "billing_mode": "api",
        "grant_id": "grant-001",
        "api_project": "isolated-api-project",
        "max_usd": "5.00",
        "expires_at": expires_at.isoformat(),
        "approved_by": "operator@example",
        "registry_sha256": receipt["registry_sha256"],
    }

    receipt_path = tmp_path / "receipt.json"
    _write_api_authorization_receipt(
        path=receipt_path,
        auth=context,
        project_id="project-001",
        mission_id="mission-001",
        task_id="w-api",
        provider_name="codex",
        started_at=now.isoformat(),
        status="finished",
        finished_at=(now + timedelta(minutes=1)).isoformat(),
        exit_code=0,
    )
    receipt_text = receipt_path.read_text(encoding="utf-8")
    assert key not in receipt_text
    assert json.loads(receipt_text)["grant_id"] == "grant-001"


def test_running_api_process_is_terminated_at_grant_expiry() -> None:
    class FakeProcess:
        returncode: int | None = None
        terminated = False

        def terminate(self) -> None:
            self.terminated = True

    process = FakeProcess()
    expired = asyncio.Event()
    context = ACPAuthContext(
        mode="api",
        codex_home=Path("/tmp/codex-api-test"),
        api_grant=ResolvedApiGrant(
            grant_id="grant-001",
            api_project="isolated-api-project",
            max_usd=Decimal("5.00"),
            expires_at=datetime.now(UTC) + timedelta(milliseconds=5),
            approved_by="operator@example",
            credential=SecretStr("test-key"),
            registry_sha256="0" * 64,
        ),
    )

    asyncio.run(_enforce_api_grant_expiry(process, context, expired))  # type: ignore[arg-type]

    assert expired.is_set()
    assert process.terminated is True


@pytest.mark.parametrize("failure", ["expired", "revoked", "budget-mismatch"])
def test_invalid_operator_grants_fail_closed(
    failure: str, harness_home: Path, tmp_path: Path
) -> None:
    now = datetime.now(UTC)
    request_expiry = now + timedelta(hours=1)
    grant_expiry = request_expiry
    revoked = False
    request_budget = "5.00"
    if failure == "expired":
        request_expiry = now - timedelta(minutes=1)
        grant_expiry = request_expiry
    elif failure == "revoked":
        revoked = True
    else:
        request_budget = "6.00"

    credential_file = tmp_path / "openai.key"
    grants_file = tmp_path / "grants.json"
    _write_private(credential_file, "test-key\n")
    _write_registry(
        grants_file,
        credential_file,
        issued_at=now - timedelta(hours=2),
        expires_at=grant_expiry,
        revoked=revoked,
    )

    with pytest.raises(ACPAuthError):
        prepare_acp_auth_context(
            config=_config(harness_home, grants_file),
            provider=PROVIDERS["codex"],
            task=_api_task(expires_at=request_expiry, max_usd=request_budget),
            project_id="project-001",
            mission_id="mission-001",
            now=now,
        )


def test_world_readable_grant_registry_is_rejected(harness_home: Path, tmp_path: Path) -> None:
    now = datetime.now(UTC)
    credential_file = tmp_path / "openai.key"
    grants_file = tmp_path / "grants.json"
    _write_private(credential_file, "test-key\n")
    _write_registry(
        grants_file,
        credential_file,
        issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    grants_file.chmod(0o644)

    with pytest.raises(ACPAuthError, match="permissions"):
        prepare_acp_auth_context(
            config=_config(harness_home, grants_file),
            provider=PROVIDERS["codex"],
            task=_api_task(expires_at=now + timedelta(hours=1)),
            project_id="project-001",
            mission_id="mission-001",
            now=now,
        )


def test_non_codex_provider_cannot_consume_openai_api_grant(harness_home: Path) -> None:
    now = datetime.now(UTC)
    with pytest.raises(ACPAuthError, match="only valid for the codex provider"):
        prepare_acp_auth_context(
            config=_config(harness_home),
            provider=PROVIDERS["claude"],
            task=_api_task(expires_at=now + timedelta(hours=1)),
            project_id="project-001",
            mission_id="mission-001",
            now=now,
        )


def test_mcp_environment_uses_same_secret_allowlist(
    monkeypatch: pytest.MonkeyPatch, harness_home: Path
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-mcp")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-reach-mcp")
    captured: dict[str, str] = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured.update(kwargs["env"])
        return object()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    config = _config(harness_home)
    runner = ACPNodeRunner(config=config, loader=AssetLoader(config))
    task = Task(id="w1", type="work", body="work", targets=["VAL-1"], skill="s")
    asyncio.run(
        runner._start_worker_mcp_server(
            task=task,
            project_id="project-001",
            mission_id="mission-001",
            handoff_path="/tmp/handoff.json",
            workspace_dir="/tmp",
            mcp_port=12345,
        )
    )

    assert "OPENAI_API_KEY" not in captured
    assert "ANTHROPIC_API_KEY" not in captured
    assert captured["ZENITH_NODE_ID"] == "w1"


def test_sanitizer_never_copies_unknown_secret_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A_NEW_VENDOR_SECRET", "sentinel")
    monkeypatch.setenv("PATH", "/safe/bin")

    env = sanitized_process_env()
    assert env["PATH"] == "/safe/bin"
    assert "A_NEW_VENDOR_SECRET" not in env
