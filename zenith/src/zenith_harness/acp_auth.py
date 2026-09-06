"""Fail-closed authentication contexts for ACP child processes.

Task JSON can request API billing, but only a private operator registry can
authorize it.  No credential is ever stored in tasks.json or an audit receipt.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr, model_validator

from .models import API_GRANT_ID_REGEX, Task

if TYPE_CHECKING:
    from .config import HarnessConfig


SUBSCRIPTION_CODEX_CONFIG = """forced_login_method = "chatgpt"
allow_login_shell = false

[features]
shell_snapshot = false

[shell_environment_policy]
inherit = "none"
ignore_default_excludes = false
"""

API_CODEX_CONFIG = """allow_login_shell = false

[features]
shell_snapshot = false

[shell_environment_policy]
inherit = "none"
ignore_default_excludes = false
"""

_SAFE_ENV_NAMES = frozenset(
    {
        "COLORTERM",
        "FORCE_COLOR",
        "HOME",
        "LANG",
        "LANGUAGE",
        "LOGNAME",
        "NO_COLOR",
        "PATH",
        "SHELL",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "TERM",
        "TMP",
        "TMPDIR",
        "TEMP",
        "TZ",
        "USER",
        # Adapter binary location, not a credential.
        "CODEX_PATH",
        # Test/smoke metadata. These are paths and opaque ids, not secrets.
        "ZENITH_HANDOFF_PATH",
        "ZENITH_NODE_ID",
        "ZENITH_NODE_TYPE",
    }
)


class ACPAuthError(RuntimeError):
    """Authentication policy or operator grant failed closed."""


class OperatorApiGrant(BaseModel):
    """One operator-owned grant record. The credential remains in a private file."""

    model_config = ConfigDict(extra="forbid")

    grant_id: str = Field(pattern=API_GRANT_ID_REGEX.pattern)
    zenith_project_id: str = Field(min_length=1)
    mission_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    provider: Literal["codex"] = "codex"
    api_project: str = Field(min_length=1)
    max_usd: Decimal = Field(gt=0)
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    approved_by: str = Field(min_length=1)
    credential_file: Path
    revoked: bool = False

    @model_validator(mode="after")
    def validate_window(self) -> OperatorApiGrant:
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be later than issued_at")
        return self


class OperatorApiGrantRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    grants: list[OperatorApiGrant] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_duplicate_ids(self) -> OperatorApiGrantRegistry:
        ids = [grant.grant_id for grant in self.grants]
        if len(ids) != len(set(ids)):
            raise ValueError("operator grant ids must be unique")
        return self


@dataclass(frozen=True)
class ResolvedApiGrant:
    grant_id: str
    api_project: str
    max_usd: Decimal
    expires_at: datetime
    approved_by: str
    credential: SecretStr
    registry_sha256: str


@dataclass(frozen=True)
class ACPAuthContext:
    mode: Literal["subscription", "api"]
    codex_home: Path | None = None
    api_grant: ResolvedApiGrant | None = None


def sanitized_process_env(source: dict[str, str] | None = None) -> dict[str, str]:
    """Return the small non-secret environment shared with ACP/MCP children."""

    ambient = source if source is not None else os.environ
    return {
        name: value
        for name, value in ambient.items()
        if name in _SAFE_ENV_NAMES or name.startswith("LC_")
    }


def prepare_acp_auth_context(
    *,
    config: HarnessConfig,
    provider,
    task: Task | None,
    project_id: str,
    mission_id: str,
    now: datetime | None = None,
) -> ACPAuthContext:
    """Resolve a task request to subscription auth or an operator API grant."""

    provider_name = getattr(provider, "name", None)
    billing = task.billing if task is not None else None
    wants_api = billing is not None and billing.mode == "api"

    if provider_name != "codex":
        if wants_api:
            raise ACPAuthError("OpenAI API grants are only valid for the codex provider")
        return ACPAuthContext(mode="subscription")

    if not wants_api:
        home = config.resolved_codex_subscription_home
        _ensure_managed_codex_home(home, SUBSCRIPTION_CODEX_CONFIG, subscription=True)
        return ACPAuthContext(mode="subscription", codex_home=home)

    assert task is not None and billing is not None and billing.api_grant is not None
    if config.api_grants_file is None:
        raise ACPAuthError(
            "task requests API billing but ZENITH_API_GRANTS_FILE is not configured"
        )
    grant = _resolve_operator_grant(
        grants_file=config.api_grants_file,
        task=task,
        project_id=project_id,
        mission_id=mission_id,
        now=now or datetime.now(UTC),
    )
    home = config.harness_home / "codex-api" / grant.grant_id
    _ensure_managed_codex_home(home, API_CODEX_CONFIG, subscription=False)
    return ACPAuthContext(mode="api", codex_home=home, api_grant=grant)


def build_acp_subprocess_env(provider, auth: ACPAuthContext | None = None) -> dict[str, str]:
    """Build a sanitized ACP environment and inject only an authorized task key."""

    env = sanitized_process_env()
    if getattr(provider, "name", None) != "codex":
        if auth is not None and auth.mode == "api":
            raise ACPAuthError("API auth context cannot be used with a non-codex provider")
        return env
    if auth is None or auth.codex_home is None:
        raise ACPAuthError("codex ACP launch requires an explicit auth context")

    home = str(auth.codex_home)
    env["HOME"] = home
    env["CODEX_HOME"] = home
    if auth.mode == "api":
        if auth.api_grant is None:
            raise ACPAuthError("API auth context is missing its resolved operator grant")
        env["OPENAI_API_KEY"] = auth.api_grant.credential.get_secret_value()
    return env


def api_grant_receipt(auth: ACPAuthContext) -> dict[str, str] | None:
    """Return non-secret audit fields for an authorized API launch."""

    grant = auth.api_grant
    if grant is None:
        return None
    return {
        "billing_mode": "api",
        "grant_id": grant.grant_id,
        "api_project": grant.api_project,
        "max_usd": str(grant.max_usd),
        "expires_at": grant.expires_at.isoformat(),
        "approved_by": grant.approved_by,
        "registry_sha256": grant.registry_sha256,
    }


def _resolve_operator_grant(
    *,
    grants_file: Path,
    task: Task,
    project_id: str,
    mission_id: str,
    now: datetime,
) -> ResolvedApiGrant:
    request = task.billing.api_grant
    assert request is not None
    registry_bytes = _read_private_file(grants_file, label="operator API grant registry")
    try:
        registry = OperatorApiGrantRegistry.model_validate_json(registry_bytes)
    except Exception as exc:  # noqa: BLE001
        raise ACPAuthError(f"operator API grant registry is invalid: {exc}") from exc

    matching = [grant for grant in registry.grants if grant.grant_id == request.grant_id]
    if len(matching) != 1:
        raise ACPAuthError("requested API grant is not present in the operator registry")
    grant = matching[0]
    expected = {
        "zenith_project_id": project_id,
        "mission_id": mission_id,
        "task_id": task.id,
        "provider": "codex",
        "api_project": request.api_project,
        "max_usd": request.max_usd,
        "expires_at": request.expires_at,
    }
    actual = {
        "zenith_project_id": grant.zenith_project_id,
        "mission_id": grant.mission_id,
        "task_id": grant.task_id,
        "provider": grant.provider,
        "api_project": grant.api_project,
        "max_usd": grant.max_usd,
        "expires_at": grant.expires_at,
    }
    if actual != expected:
        raise ACPAuthError("task API request does not exactly match its operator grant")
    if grant.revoked:
        raise ACPAuthError("operator API grant is revoked")
    if now < grant.issued_at:
        raise ACPAuthError("operator API grant is not active yet")
    if now >= grant.expires_at:
        raise ACPAuthError("operator API grant has expired")

    credential_path = grant.credential_file
    if not credential_path.is_absolute():
        credential_path = grants_file.parent / credential_path
    credential_bytes = _read_private_file(credential_path, label="API credential")
    try:
        credential_text = credential_bytes.decode("utf-8").rstrip("\r\n")
    except UnicodeDecodeError as exc:
        raise ACPAuthError("API credential is not UTF-8 text") from exc
    if not credential_text or "\n" in credential_text or "\r" in credential_text:
        raise ACPAuthError("API credential must contain exactly one non-empty line")

    return ResolvedApiGrant(
        grant_id=grant.grant_id,
        api_project=grant.api_project,
        max_usd=grant.max_usd,
        expires_at=grant.expires_at,
        approved_by=grant.approved_by,
        credential=SecretStr(credential_text),
        registry_sha256=hashlib.sha256(registry_bytes).hexdigest(),
    )


def _ensure_managed_codex_home(home: Path, config_text: str, *, subscription: bool) -> None:
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    home_stat = home.lstat()
    if stat.S_ISLNK(home_stat.st_mode) or not stat.S_ISDIR(home_stat.st_mode):
        raise ACPAuthError(f"managed Codex home is not a real directory: {home}")
    if home_stat.st_uid != os.geteuid():
        raise ACPAuthError(f"managed Codex home is not owned by the current user: {home}")
    os.chmod(home, 0o700)

    config_path = home / "config.toml"
    if config_path.exists():
        config_bytes = _read_private_file(config_path, label="managed Codex config")
        try:
            existing_config = config_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ACPAuthError("managed Codex config is not UTF-8 text") from exc
        if existing_config != config_text:
            raise ACPAuthError(f"managed Codex config differs from the required profile: {config_path}")
    else:
        tmp_path = home / f".config.toml.{os.getpid()}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(tmp_path, flags, 0o600)
        except OSError as exc:
            raise ACPAuthError(f"cannot create managed Codex config: {config_path}") from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(config_text)
        os.replace(tmp_path, config_path)
    os.chmod(config_path, 0o600)

    snapshots = home / "shell_snapshots"
    if snapshots.exists():
        snapshot_stat = snapshots.lstat()
        if stat.S_ISLNK(snapshot_stat.st_mode) or not stat.S_ISDIR(snapshot_stat.st_mode):
            raise ACPAuthError(f"managed Codex shell_snapshots path is unsafe: {snapshots}")
        if any(snapshots.iterdir()):
            raise ACPAuthError(f"managed Codex home contains forbidden shell snapshots: {snapshots}")

    auth_path = home / "auth.json"
    if not auth_path.exists():
        return
    auth_bytes = _read_private_file(auth_path, label="Codex auth cache")
    try:
        auth_payload = json.loads(auth_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ACPAuthError("Codex auth cache is invalid") from exc
    if not isinstance(auth_payload, dict):
        raise ACPAuthError("Codex auth cache must contain a JSON object")
    if subscription:
        if auth_payload.get("auth_mode") != "chatgpt":
            raise ACPAuthError("subscription Codex home is not authenticated with ChatGPT")
        if auth_payload.get("OPENAI_API_KEY") not in (None, ""):
            raise ACPAuthError("subscription Codex home contains an API key")
    else:
        raise ACPAuthError("API Codex homes must not contain a persistent auth cache")


def _read_private_file(path: Path, *, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as exc:
        raise ACPAuthError(f"{label} is missing: {path}") from exc
    except OSError as exc:
        raise ACPAuthError(f"{label} cannot be opened safely: {path}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ACPAuthError(f"{label} must be a regular non-symlink file: {path}")
        if metadata.st_uid != os.geteuid():
            raise ACPAuthError(f"{label} must be owned by the current user: {path}")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ACPAuthError(f"{label} permissions must not allow group/other access: {path}")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            return handle.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)
