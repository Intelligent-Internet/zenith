"""ACP runner adaptation tests — direct-to-PROJECT handoff path discipline.

We don't run a real `claude-agent-acp` here; we use the bundled
`mock_acp_agent.py` to exercise the ACP client + the handoff polling
mechanic. The worker MCP server subprocess is bypassed: the mock agent
writes directly to ZENITH_HANDOFF_PATH itself.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from zenith_harness.acp_runner import (
    ACPNodeRunner,
    ACPError,
    _acp_subprocess_env,
    _augment_acp_command,
    _ensure_claude_settings,
    _parse_codex_c_overrides,
)
from zenith_harness.providers import PROVIDERS
from zenith_harness.assets import AssetLoader
from zenith_harness.config import HarnessConfig
from zenith_harness.models import Task, WorkHandoff
from zenith_harness.storage import ProjectStore


@pytest.fixture
def mock_acp_command() -> str:
    """Wrap the mock agent script so it's invocable from a shell."""
    mock = Path(__file__).resolve().parent / "mock_acp_agent.py"
    return f"{sys.executable} {mock}"


@pytest.fixture
def config(harness_home: Path, mock_acp_command: str) -> HarnessConfig:
    bundled = Path(__file__).resolve().parents[1] / "src" / "zenith_harness" / "bundled"
    return HarnessConfig(
        bundled_dir=bundled,
        harness_home=harness_home,
        projects_dir=harness_home / "projects",
        orchestrator_provider_name="claude",
        worker_provider_name="claude",
        worker_acp_command=mock_acp_command,
        validator_provider_name=None,
        validator_acp_command=None,
        terminal_reviewer_provider_name=None,
        terminal_reviewer_acp_command=None,
    )


@pytest.fixture
def project_setup(config: HarnessConfig, workspace: Path):
    store = ProjectStore(config)
    store.create_project("brief", workspace, project_id="p1")
    contract_dir = store.ensure_contract_dir("p1", "mission-001")
    (contract_dir / "VAL-001.md").write_text("# VAL-001\n\nTest.\n")
    return store


# ---------------------------------------------------------------------------
# Mock-agent integration: the agent writes directly to ZENITH_HANDOFF_PATH
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not shutil.which("python3") and not Path(sys.executable).exists(),
    reason="Python interpreter unavailable",
)
def test_run_node_with_mock_agent(
    config: HarnessConfig, project_setup, workspace: Path
):
    """End-to-end via the mock agent (NO real worker MCP server subprocess —
    we point at a free port that nothing binds to and rely on the mock to
    write the handoff file itself).
    """
    store = project_setup
    task = Task(id="w1", type="work", body="do it", targets=["VAL-001"], skill="s")
    spawn_ts = "2026-05-17T00-00-00Z"
    handoff_path = store.attempt_path("p1", "mission-001", spawn_ts, "w1")
    handoff_path.parent.mkdir(parents=True, exist_ok=True)

    os.environ["ZENITH_HANDOFF_PATH"] = str(handoff_path)
    os.environ["ZENITH_NODE_ID"] = task.id
    os.environ["ZENITH_NODE_TYPE"] = task.type
    try:
        loader = AssetLoader(config)
        runner = ACPNodeRunner(config=config, loader=loader)

        async def _no_op_server(*args, **kwargs):
            return await asyncio.create_subprocess_exec(
                "sleep", "30",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

        async def _ready_immediately(*args, **kwargs):
            return None

        runner._start_worker_mcp_server = _no_op_server  # type: ignore[method-assign]
        runner._wait_for_server_ready = _ready_immediately  # type: ignore[method-assign]

        handoff = asyncio.run(
            runner.run_node(
                project_id="p1",
                mission_id="mission-001",
                task=task,
                spawn_ts=spawn_ts,
                store=store,
            )
        )
    finally:
        for k in ("ZENITH_HANDOFF_PATH", "ZENITH_NODE_ID", "ZENITH_NODE_TYPE"):
            os.environ.pop(k, None)

    assert isinstance(handoff, WorkHandoff)
    assert handoff.done is True
    # The file should be at the durable audit path.
    assert handoff_path.exists()
    data = json.loads(handoff_path.read_text())
    assert data["node_id"] == "w1"


def test_synthesize_missing_handoff_records_failure(
    config: HarnessConfig, project_setup, workspace: Path
):
    """If the agent exits without writing, the runner synthesizes a failure
    handoff and persists it to the durable audit path.
    """
    store = project_setup
    task = Task(id="w1", type="work", body="b", targets=["VAL-001"], skill="s")
    runner = ACPNodeRunner(config=config, loader=AssetLoader(config))
    handoff_path = store.attempt_path("p1", "mission-001", "2026-05-17T00-00-00Z", "w1")
    handoff = runner._synthesize_and_persist_missing_handoff(
        handoff_path=handoff_path,
        task=task,
        stop_reason="cancelled",
        exit_code=1,
        stderr="boom",
        session_error=None,
    )
    assert handoff.done is False
    assert "stop_reason=cancelled" in handoff.report
    assert handoff_path.exists()


def test_augment_acp_command_codex_appends_bypass_flags():
    out = _augment_acp_command("codex-acp", PROVIDERS["codex"])
    assert 'sandbox_mode="danger-full-access"' in out
    assert 'approval_policy="never"' in out
    assert 'model_reasoning_effort="xhigh"' in out
    assert out.startswith("codex-acp ")


def test_augment_acp_command_codex_reasoning_effort_override():
    out = _augment_acp_command("codex-acp", PROVIDERS["codex"], reasoning_effort="medium")
    assert 'model_reasoning_effort="medium"' in out
    assert "xhigh" not in out
    # The bypass flags are effort-independent.
    assert 'sandbox_mode="danger-full-access"' in out
    assert 'approval_policy="never"' in out


def test_augment_acp_command_claude_untouched():
    assert _augment_acp_command("claude-agent-acp", PROVIDERS["claude"]) == "claude-agent-acp"
    assert (
        _augment_acp_command("claude-agent-acp", PROVIDERS["claude"], reasoning_effort="low")
        == "claude-agent-acp"
    )


def test_claude_settings_workaround_is_scoped_to_claude(tmp_path: Path):
    opencode_workspace = tmp_path / "opencode"
    opencode_workspace.mkdir()

    assert PROVIDERS["opencode"].acp_runtime_mode == "build"
    _ensure_claude_settings(opencode_workspace, PROVIDERS["opencode"])
    assert not (opencode_workspace / ".claude" / "settings.json").exists()

    existing_settings = opencode_workspace / ".claude" / "settings.json"
    existing_settings.parent.mkdir(parents=True)
    existing_settings.write_text('{"user": "keep-me"}\n', encoding="utf-8")
    _ensure_claude_settings(opencode_workspace, PROVIDERS["opencode"])
    assert existing_settings.read_text(encoding="utf-8") == '{"user": "keep-me"}\n'

    claude_workspace = tmp_path / "claude"
    claude_workspace.mkdir()
    _ensure_claude_settings(claude_workspace, PROVIDERS["claude"])
    assert json.loads(
        (claude_workspace / ".claude" / "settings.json").read_text(encoding="utf-8")
    ) == {"permissions": {"defaultMode": "bypassPermissions"}}


@pytest.mark.asyncio
async def test_opencode_build_mode_still_uses_session_set_mode(config: HarnessConfig):
    runner = ACPNodeRunner(config=config, loader=AssetLoader(config))
    client = AsyncMock()

    await runner._maybe_set_mode(client, "session-1", PROVIDERS["opencode"])

    client.send_request.assert_awaited_once_with(
        "session/set_mode", {"sessionId": "session-1", "modeId": "build"}
    )


def test_codex_acp_env_preserves_node_path_when_bwrap_is_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for executable in ("node", "bwrap"):
        path = bin_dir / executable
        path.write_text("#!/bin/sh\n", encoding="utf-8")
        path.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))

    env = _acp_subprocess_env(PROVIDERS["codex"])

    assert str(bin_dir) in env["PATH"].split(os.pathsep)
    assert env["CODEX_SANDBOX"] == "danger-full-access"
    assert env["CODEX_DISABLE_SANDBOX"] == "1"


def test_codex_acp_env_includes_codex_config_json_with_effort():
    env = _acp_subprocess_env(PROVIDERS["codex"], reasoning_effort="max")
    config = json.loads(env["CODEX_CONFIG"])
    assert config["sandbox_mode"] == "danger-full-access"
    assert config["approval_policy"] == "never"
    assert config["model_reasoning_effort"] == "max"


def test_codex_acp_env_codex_config_defaults_to_xhigh():
    env = _acp_subprocess_env(PROVIDERS["codex"])
    config = json.loads(env["CODEX_CONFIG"])
    assert config["model_reasoning_effort"] == "xhigh"


def test_codex_acp_env_merges_user_codex_config(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("CODEX_CONFIG", json.dumps({"model": "gpt-5.6-luna"}))
    env = _acp_subprocess_env(PROVIDERS["codex"], reasoning_effort="ultra")
    config = json.loads(env["CODEX_CONFIG"])
    assert config["model"] == "gpt-5.6-luna"
    assert config["sandbox_mode"] == "danger-full-access"
    assert config["approval_policy"] == "never"
    assert config["model_reasoning_effort"] == "ultra"


def test_codex_acp_env_overrides_user_safety_values(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(
        "CODEX_CONFIG",
        json.dumps({"sandbox_mode": "read-only", "approval_policy": "on-failure"}),
    )
    env = _acp_subprocess_env(PROVIDERS["codex"])
    config = json.loads(env["CODEX_CONFIG"])
    assert config["sandbox_mode"] == "danger-full-access"
    assert config["approval_policy"] == "never"


@pytest.mark.parametrize("raw", ["not valid json", "", "[]", "null", '"text"', "42"])
def test_invalid_codex_config_fails_explicitly(monkeypatch, raw):
    monkeypatch.setenv("CODEX_CONFIG", raw)
    with pytest.raises(ACPError, match="CODEX_CONFIG"):
        _acp_subprocess_env(PROVIDERS["codex"], reasoning_effort="high")


@pytest.mark.parametrize("assignment", [
    'model="chosen-model"',
    "model=chosen-model",
    "'model=\"chosen-model\"'",
    'model="old-model" -c model=chosen-model',
])
def test_command_model_overrides_ambient_for_shell_quoting(monkeypatch, assignment):
    monkeypatch.setenv("CODEX_CONFIG", '{"model":"ambient-model"}')
    command = _augment_acp_command("codex-acp -c " + assignment, PROVIDERS["codex"], "high")
    config = json.loads(_acp_subprocess_env(PROVIDERS["codex"], "high", command)["CODEX_CONFIG"])
    assert config["model"] == "chosen-model"
    assert config["model_reasoning_effort"] == "high"


@pytest.mark.parametrize("command", [
    "codex-acp --config model=chosen-model",
    "codex-acp --config=model=chosen-model",
])
def test_long_config_option(command):
    assert _parse_codex_c_overrides(command) == {"model": "chosen-model"}


@pytest.mark.parametrize("command", ["codex-acp -c", "codex-acp -c model", 'codex-acp -c model="'])
def test_malformed_override_is_reported(command):
    with pytest.raises(ACPError):
        _parse_codex_c_overrides(command)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["worker", "validator", "terminal_reviewer"])
async def test_invalid_config_rejected_before_mcp_start(monkeypatch, config, role):
    monkeypatch.setenv("CODEX_CONFIG", "invalid-json")
    config = replace(config, worker_provider_name="codex", worker_acp_command="codex-acp")
    runner = ACPNodeRunner(config, AssetLoader(config))
    worker_start = AsyncMock()
    review_start = AsyncMock()
    monkeypatch.setattr(runner, "_start_worker_mcp_server", worker_start)
    monkeypatch.setattr(runner, "_start_terminal_reviewer_mcp", review_start)
    store = ProjectStore(config)
    with pytest.raises(ACPError, match="CODEX_CONFIG"):
        if role == "terminal_reviewer":
            await runner.run_terminal_review("p1", "mission-001", "attempt", store)
        else:
            task = Task(id="w1", type="validate" if role == "validator" else "work",
                        body="check", targets=[])
            await runner.run_node("p1", "mission-001", task, "attempt", store)
    worker_start.assert_not_called()
    review_start.assert_not_called()


@pytest.mark.parametrize("raw", ['{"value": NaN}', '{"value": Infinity}'])
def test_nonfinite_config_rejected(monkeypatch, raw):
    monkeypatch.setenv("CODEX_CONFIG", raw)
    with pytest.raises(ACPError, match="JSON-compatible"):
        _acp_subprocess_env(PROVIDERS["codex"])


def test_override_values_preserve_types_and_embedded_quotes():
    command = "codex-acp -c 'enabled=true' -c 'limit=3' -c 'label=\"a=b\"'"
    assert _parse_codex_c_overrides(command) == {"enabled": True, "limit": 3, "label": "a=b"}


def test_claude_acp_env_has_no_codex_config(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("CODEX_CONFIG", raising=False)
    env = _acp_subprocess_env(PROVIDERS["claude"])
    assert "CODEX_CONFIG" not in env


def test_parse_codex_c_overrides_extracts_model():
    cmd = 'codex-acp -c model="gpt-5.6-luna" -c sandbox_mode="danger-full-access"'
    overrides = _parse_codex_c_overrides(cmd)
    assert overrides["model"] == "gpt-5.6-luna"
    assert overrides["sandbox_mode"] == "danger-full-access"


def test_parse_codex_c_overrides_handles_single_quotes():
    cmd = "codex-acp -c model='gpt-5.6-luna'"
    overrides = _parse_codex_c_overrides(cmd)
    assert overrides["model"] == "gpt-5.6-luna"


def test_parse_codex_c_overrides_empty_when_no_flags():
    assert _parse_codex_c_overrides("codex-acp") == {}


def test_codex_acp_env_preserves_custom_model_from_command():
    """The user's custom model from ZENITH_*_ACP_COMMAND's -c model=...
    must reach CODEX_CONFIG — the npm adapter drops all argv -c flags."""
    cmd = 'codex-acp -c model="gpt-5.6-luna" -c sandbox_mode="danger-full-access" -c approval_policy="never" -c model_reasoning_effort="max"'
    env = _acp_subprocess_env(
        PROVIDERS["codex"], reasoning_effort="max", acp_command=cmd
    )
    config = json.loads(env["CODEX_CONFIG"])
    assert config["model"] == "gpt-5.6-luna"
    assert config["sandbox_mode"] == "danger-full-access"
    assert config["approval_policy"] == "never"
    assert config["model_reasoning_effort"] == "max"


def test_codex_acp_env_model_from_command_overrides_user_codex_config(
    monkeypatch: pytest.MonkeyPatch,
):
    """The -c model in the command string (explicit per-role) wins over
    an ambient CODEX_CONFIG model."""
    monkeypatch.setenv("CODEX_CONFIG", json.dumps({"model": "gpt-4o"}))
    cmd = 'codex-acp -c model="gpt-5.6-luna"'
    env = _acp_subprocess_env(
        PROVIDERS["codex"], reasoning_effort="max", acp_command=cmd
    )
    config = json.loads(env["CODEX_CONFIG"])
    assert config["model"] == "gpt-5.6-luna"


def test_codex_acp_env_without_command_keeps_user_codex_config_model(
    monkeypatch: pytest.MonkeyPatch,
):
    """When no acp_command is passed, a user-supplied CODEX_CONFIG model
    is preserved (backward-compatible call signature)."""
    monkeypatch.setenv("CODEX_CONFIG", json.dumps({"model": "gpt-4o"}))
    env = _acp_subprocess_env(PROVIDERS["codex"], reasoning_effort="high")
    config = json.loads(env["CODEX_CONFIG"])
    assert config["model"] == "gpt-4o"
    assert config["model_reasoning_effort"] == "high"


def test_attempt_path_naming(config: HarnessConfig, project_setup):
    store = project_setup
    p = store.attempt_path("p1", "mission-001", "2026-05-17T10-00-00Z", "w1")
    assert p.name == "2026-05-17T10-00-00Z__w1.json"
    assert "attempts" in p.parts
    # JSON handoff lives in the runtime cursor tree, not the durable .zenith record.
    assert ".zenith-runtime" in p.parts


def test_terminal_review_path_naming(config: HarnessConfig, project_setup):
    store = project_setup
    p = store.terminal_review_path("p1", "mission-001", "2026-05-17T10-00-00Z")
    assert p.name == "2026-05-17T10-00-00Z.json"
    assert "terminal-reviews" in p.parts
    # JSON handoff lives in the runtime cursor tree, not the durable .zenith record.
    assert ".zenith-runtime" in p.parts
