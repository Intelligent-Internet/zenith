"""v5 HarnessConfig. See specs/memory_v2/PRODUCT.md for layout."""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from .providers import (
    ProviderSelection,
    default_worker_provider_name,
    get_provider,
)

DEFAULT_MAX_PARALLEL_NODES = 4


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
            "ZENITH_ORCHESTRATOR_PROVIDER", "codex"
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

    def for_role(
        self, role: Literal["worker", "validator", "terminal_reviewer"]
    ) -> HarnessConfig:
        if role == "worker":
            return self
        if role == "validator":
            return replace(
                self,
                worker_provider_name=(
                    self.validator_provider_name or self.worker_provider_name
                ),
                worker_acp_command=self.resolved_validator_acp_command,
            )
        if role == "terminal_reviewer":
            return replace(
                self,
                worker_provider_name=(
                    self.terminal_reviewer_provider_name
                    or self.validator_provider_name
                    or self.worker_provider_name
                ),
                worker_acp_command=self.resolved_terminal_reviewer_acp_command,
            )
        raise ValueError(f"unknown role: {role}")
