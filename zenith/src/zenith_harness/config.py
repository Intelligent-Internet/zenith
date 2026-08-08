"""v5 HarnessConfig. See specs/memory_v2/PRODUCT.md for layout."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from .providers import (
    ProviderSelection,
    default_worker_provider_name,
    get_provider,
)

DEFAULT_MAX_PARALLEL_NODES = 4

# codex-acp `model_reasoning_effort` values. Also a safety allowlist: the
# resolved value is spliced into a shell command line by acp_runner. Codex's
# "ultra" is deliberately excluded: it is not a reasoning tier (codex
# downgrades the request to "max" on the wire) but a switch to proactive
# multi-agent mode — a lane spawning its own agent swarm inside a harness
# that already orchestrates and validates per-lane work.
VALID_REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")

# Model identifiers are open-ended (provider aliases like "opus", pinned ids
# like "claude-opus-5[1m]", Bedrock/Vertex ARNs), so they cannot be checked
# against an allowlist the way reasoning efforts are. They still reach a shell
# command line for codex (`-c model="..."`), so the character set is restricted
# to what real model identifiers use — no quotes, spaces, or shell operators.
# Matched with fullmatch: `$` would admit a trailing newline, which survives
# into .codex/config.toml as an unescaped newline inside a basic string.
MODEL_ID_PATTERN = re.compile(r"[A-Za-z0-9._:/@\[\]-]+")


def _bundled_dir() -> Path:
    return (Path(__file__).resolve().parent / "bundled").resolve()


def _resolve_optional_path(value: str | None) -> Path | None:
    if not value:
        return None
    return Path(value).expanduser().resolve()


def _resolve_max_parallel(value: str | None) -> int:
    if not value:
        return DEFAULT_MAX_PARALLEL_NODES
    try:
        parsed = int(value)
    except ValueError:
        return DEFAULT_MAX_PARALLEL_NODES
    return max(1, parsed)


def _resolve_reasoning_effort(value: str | None, *, env_var: str) -> str | None:
    """None passes through (provider default); anything else must be on the
    allowlist — a typo silently ignored would spend xhigh the user thought
    they had dialed down."""
    if not value:
        return None
    if value not in VALID_REASONING_EFFORTS:
        raise ValueError(
            f"{env_var}={value!r} is not a valid reasoning effort; "
            f"choose one of: {', '.join(VALID_REASONING_EFFORTS)}"
        )
    return value


def validate_model_id(value: str | None, *, env_var: str) -> str | None:
    """None passes through (provider default); anything else must look like a
    model identifier. The value is spliced into a shell command line for codex,
    so a rejected string is a refusal to execute, not a cosmetic complaint."""
    if not value:
        return None
    if not MODEL_ID_PATTERN.fullmatch(value):
        raise ValueError(
            f"{env_var}={value!r} is not a valid model identifier; "
            "allowed characters are letters, digits, and ._:/@[]-"
        )
    return value


@dataclass(frozen=True)
class HarnessConfig:
    """Static configuration loaded from env. Per-call overrides allowed via `with_*`."""

    bundled_dir: Path
    harness_home: Path  # ZENITH_HOME (default ~/.zenith)
    projects_dir: Path  # ZENITH_PROJECTS_DIR (default <harness_home>/projects)
    orchestrator_provider_name: str
    worker_provider_name: str
    worker_acp_command: str | None
    validator_provider_name: str | None
    validator_acp_command: str | None
    terminal_reviewer_provider_name: str | None
    terminal_reviewer_acp_command: str | None
    max_parallel_nodes: int = DEFAULT_MAX_PARALLEL_NODES
    # Per-role reasoning effort for providers whose ACP command accepts one
    # (codex today). None means the provider default ("xhigh" for codex).
    worker_reasoning_effort: str | None = None
    validator_reasoning_effort: str | None = None
    terminal_reviewer_reasoning_effort: str | None = None
    # Per-role model pin. None means whatever the lane would run without one:
    # codex uses the model in its own config, and claude-agent-acp reads an
    # inherited ANTHROPIC_MODEL if the environment carries one (that var is in
    # the CLI's runtime forward allowlist, so a workspace can carry it) before
    # falling back to its first model. So an unpinned claude lane is not
    # guaranteed to be on a provider default — including when `_inherited_model`
    # declines to inherit a foreign-provider pin.
    worker_model: str | None = None
    validator_model: str | None = None
    terminal_reviewer_model: str | None = None

    @classmethod
    def discover(cls) -> HarnessConfig:
        if os.environ.get("ZENITH_PROJECT_BUCKET_DIR"):
            raise RuntimeError(
                "ZENITH_PROJECT_BUCKET_DIR was removed in memory_v2; the project "
                "bucket is always $ZENITH_HOME/projects/<pid>/. Unset the env var."
            )
        harness_home = (
            Path(os.environ.get("ZENITH_HOME") or (Path.home() / ".zenith"))
            .expanduser()
            .resolve()
        )
        projects_dir = (
            _resolve_optional_path(os.environ.get("ZENITH_PROJECTS_DIR"))
            or harness_home / "projects"
        )
        orchestrator_provider_name = os.environ.get(
            "ZENITH_ORCHESTRATOR_PROVIDER", "claude"
        )
        worker_provider_name = os.environ.get(
            "ZENITH_WORKER_PROVIDER"
        ) or default_worker_provider_name(orchestrator_provider_name)
        worker_acp_command = os.environ.get("ZENITH_WORKER_ACP_COMMAND")
        validator_provider_name = os.environ.get("ZENITH_VALIDATOR_PROVIDER")
        validator_acp_command = os.environ.get("ZENITH_VALIDATOR_ACP_COMMAND")
        terminal_reviewer_provider_name = os.environ.get(
            "ZENITH_TERMINAL_REVIEWER_PROVIDER"
        )
        terminal_reviewer_acp_command = os.environ.get(
            "ZENITH_TERMINAL_REVIEWER_ACP_COMMAND"
        )
        return cls(
            bundled_dir=_bundled_dir(),
            harness_home=harness_home,
            projects_dir=projects_dir,
            orchestrator_provider_name=orchestrator_provider_name,
            worker_provider_name=worker_provider_name,
            worker_acp_command=worker_acp_command,
            validator_provider_name=validator_provider_name,
            validator_acp_command=validator_acp_command,
            terminal_reviewer_provider_name=terminal_reviewer_provider_name,
            terminal_reviewer_acp_command=terminal_reviewer_acp_command,
            max_parallel_nodes=_resolve_max_parallel(
                os.environ.get("ZENITH_MAX_PARALLEL_NODES")
            ),
            worker_reasoning_effort=_resolve_reasoning_effort(
                os.environ.get("ZENITH_WORKER_REASONING_EFFORT"),
                env_var="ZENITH_WORKER_REASONING_EFFORT",
            ),
            validator_reasoning_effort=_resolve_reasoning_effort(
                os.environ.get("ZENITH_VALIDATOR_REASONING_EFFORT"),
                env_var="ZENITH_VALIDATOR_REASONING_EFFORT",
            ),
            terminal_reviewer_reasoning_effort=_resolve_reasoning_effort(
                os.environ.get("ZENITH_TERMINAL_REVIEWER_REASONING_EFFORT"),
                env_var="ZENITH_TERMINAL_REVIEWER_REASONING_EFFORT",
            ),
            worker_model=validate_model_id(
                os.environ.get("ZENITH_WORKER_MODEL"),
                env_var="ZENITH_WORKER_MODEL",
            ),
            validator_model=validate_model_id(
                os.environ.get("ZENITH_VALIDATOR_MODEL"),
                env_var="ZENITH_VALIDATOR_MODEL",
            ),
            terminal_reviewer_model=validate_model_id(
                os.environ.get("ZENITH_TERMINAL_REVIEWER_MODEL"),
                env_var="ZENITH_TERMINAL_REVIEWER_MODEL",
            ),
        )

    # ------------------------------------------------------------------
    # Provider accessors
    # ------------------------------------------------------------------

    @property
    def orchestrator_provider(self):
        return get_provider(self.orchestrator_provider_name)

    @property
    def worker_provider(self):
        return get_provider(self.worker_provider_name)

    @property
    def validator_provider(self):
        return get_provider(self.validator_provider_name or self.worker_provider_name)

    @property
    def terminal_reviewer_provider(self):
        name = (
            self.terminal_reviewer_provider_name
            or self.validator_provider_name
            or self.worker_provider_name
        )
        return get_provider(name)

    @property
    def resolved_worker_acp_command(self) -> str | None:
        return self.worker_acp_command or self.worker_provider.default_worker_acp_command

    @property
    def resolved_validator_acp_command(self) -> str | None:
        return (
            self.validator_acp_command
            or self.validator_provider.default_worker_acp_command
            or self.resolved_worker_acp_command
        )

    @property
    def resolved_terminal_reviewer_acp_command(self) -> str | None:
        return (
            self.terminal_reviewer_acp_command
            or self.terminal_reviewer_provider.default_worker_acp_command
            or self.resolved_validator_acp_command
        )

    @property
    def provider_selection(self) -> ProviderSelection:
        return ProviderSelection(
            orchestrator=self.orchestrator_provider,
            worker=self.worker_provider,
            validation_worker=(
                self.validator_provider
                if self.validator_provider_name
                else None
            ),
            worker_acp_command=self.worker_acp_command,
            validation_worker_acp_command=self.validator_acp_command,
        )

    # ------------------------------------------------------------------
    # Bucket paths
    # ------------------------------------------------------------------

    def bucket_root(self, project_id: str) -> Path:
        """Per-project root: parent of .zenith/ and .zenith-runtime/."""
        return self.projects_dir / project_id

    def zenith_dir(self, project_id: str) -> Path:
        """Durable, all-roles-readable record (brief, decisions, skills, missions)."""
        return self.bucket_root(project_id) / ".zenith"

    def zenith_runtime_dir(self, project_id: str) -> Path:
        """Orchestrator-only cursors (project.json, state.json, dag.json, ...)."""
        return self.bucket_root(project_id) / ".zenith-runtime"

    def skill_dirs(self, project_id: str | None = None) -> list[Path]:
        dirs: list[Path] = []
        if project_id is not None:
            dirs.append(self.zenith_dir(project_id) / "skills")
        dirs.append(self.harness_home / "skills")
        dirs.append(self.bundled_dir / "skills")
        return dirs

    # ------------------------------------------------------------------
    # Role-specialized variants
    # ------------------------------------------------------------------

    def _inherited_model(
        self, provider_name: str, chain: tuple[tuple[str | None, str], ...]
    ) -> str | None:
        """Walk a role's fallback chain, skipping links from other providers.

        Reasoning efforts are provider-neutral vocabulary, so they inherit
        freely. Model ids are not — a codex worker's "gpt-5.5" handed to a
        claude validator becomes ANTHROPIC_MODEL="gpt-5.5" and breaks every
        session on that lane. So a pin only carries to a role running the same
        provider; otherwise the role falls back to its provider's own default.

        `chain` is ordered nearest-first: (pin, provider that pin was set for).
        """
        for pin, pin_provider_name in chain:
            if pin and pin_provider_name == provider_name:
                return pin
        return None

    def for_role(
        self, role: Literal["worker", "validator", "terminal_reviewer"]
    ) -> HarnessConfig:
        if role == "worker":
            return self
        if role == "validator":
            provider_name = self.validator_provider_name or self.worker_provider_name
            return replace(
                self,
                worker_provider_name=provider_name,
                worker_acp_command=self.resolved_validator_acp_command,
                worker_reasoning_effort=(
                    self.validator_reasoning_effort or self.worker_reasoning_effort
                ),
                worker_model=self._inherited_model(
                    provider_name,
                    (
                        (self.validator_model, provider_name),
                        (self.worker_model, self.worker_provider_name),
                    ),
                ),
            )
        if role == "terminal_reviewer":
            validator_provider_name = (
                self.validator_provider_name or self.worker_provider_name
            )
            provider_name = (
                self.terminal_reviewer_provider_name
                or self.validator_provider_name
                or self.worker_provider_name
            )
            return replace(
                self,
                worker_provider_name=provider_name,
                worker_acp_command=self.resolved_terminal_reviewer_acp_command,
                worker_reasoning_effort=(
                    self.terminal_reviewer_reasoning_effort
                    or self.validator_reasoning_effort
                    or self.worker_reasoning_effort
                ),
                worker_model=self._inherited_model(
                    provider_name,
                    (
                        (self.terminal_reviewer_model, provider_name),
                        (self.validator_model, validator_provider_name),
                        (self.worker_model, self.worker_provider_name),
                    ),
                ),
            )
        raise ValueError(f"unknown role: {role}")
