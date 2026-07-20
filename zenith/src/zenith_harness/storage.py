"""v5 ProjectStore — memory_v2 layout.

BUCKET_PROJECT = `$ZENITH_HOME/projects/<pid>/`. Inside it:
  - `.zenith/`            — durable record (brief, memory, decisions, skills,
                            missions/<mid>/attempts/*.md mirrors, ...)
  - `.zenith-runtime/`    — orchestrator-only cursors (state.json, tasks.json,
                            missions/<mid>/attempts/*.json handoffs, ...)

Workspace itself is left clean except for host-agent discovery shims
(`.agents/skills`, `.claude/skills`, `.codex/skills`, `AGENTS.md`) that
retarget into the bucket. If the workspace already has a real host `skills/`
directory, Zenith preserves it and copies missing bucket skills into it.

See `specs/memory_v2/PRODUCT.md` and `specs/task_list/PRODUCT.md`.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import HarnessConfig
from .models import (
    AttentionFile,
    AttentionItemInternal,
    ContractStateFile,
    Decision,
    ProjectRecord,
    ProjectState,
    TaskList,
    TaskStateFile,
    TerminalReviewConfig,
    TerminalReviewHandoff,
    ValidateHandoff,
    WorkHandoff,
)

# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def utc_now_iso() -> str:
    """ISO-8601 UTC timestamp with second precision."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_now_filesafe() -> str:
    """`2026-05-17T10-15-00Z` (colons turned into hyphens) for filenames."""
    return utc_now_iso().replace(":", "-")


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str, fallback: str = "item") -> str:
    slug = _SLUG_RE.sub("-", value.lower()).strip("-")
    return slug[:64] or fallback


def atomic_write_text(path: str | Path, content: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_suffix(target.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, target)


def atomic_write_json(path: str | Path, payload: object) -> None:
    atomic_write_text(
        path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def attempt_to_markdown(handoff: WorkHandoff | ValidateHandoff) -> str:
    lines = ["---"]
    lines.append(f"node_id: {handoff.node_id}")
    lines.append(f"done: {str(handoff.done).lower()}")
    if isinstance(handoff, ValidateHandoff):
        lines.append(f"passed: {str(handoff.passed).lower()}")
    lines.append(f"request_attention: {str(handoff.request_attention).lower()}")
    lines.append("---")
    lines.append("")
    if isinstance(handoff, ValidateHandoff) and handoff.items:
        lines.append("## Items")
        lines.append("")
        for item in handoff.items:
            lines.append(f"- {item.item_id}: {'passed' if item.passed else 'failed'}")
        lines.append("")
    lines.append("## Report")
    lines.append("")
    if handoff.report:
        lines.append(handoff.report)
    return "\n".join(lines).rstrip() + "\n"


def terminal_review_to_markdown(review: TerminalReviewHandoff) -> str:
    lines = ["---", f"done: {str(review.done).lower()}", "---", "", "## Report", ""]
    if review.report:
        lines.append(review.report)
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AttemptRecord:
    spawn_ts: str
    node_id: str
    path: Path


# ---------------------------------------------------------------------------
# ProjectStore
# ---------------------------------------------------------------------------


class ProjectStore:
    """All disk I/O for v5 memory_v2.

    Bucket root lives at `$ZENITH_HOME/projects/<pid>/`. Callers pass
    `project_id` (and `mission_id` where relevant); the store owns all path
    conventions.
    """

    def __init__(self, config: HarnessConfig):
        self.config = config

    # ------------------------------------------------------------------
    # Bucket path accessors
    # ------------------------------------------------------------------

    def bucket_root(self, project_id: str) -> Path:
        return self.config.bucket_root(project_id)

    def zenith_dir(self, project_id: str) -> Path:
        return self.config.zenith_dir(project_id)

    def zenith_runtime_dir(self, project_id: str) -> Path:
        return self.config.zenith_runtime_dir(project_id)

    def workspace_dir(self, project_id: str) -> Path:
        return Path(self.load_project(project_id).workspace_dir)

    def mission_dir(self, project_id: str, mission_id: str) -> Path:
        """Durable per-mission dir (contract/, attempts/, closeout.md, ...)."""
        return self.zenith_dir(project_id) / "missions" / mission_id

    def mission_runtime_dir(self, project_id: str, mission_id: str) -> Path:
        """Cursor per-mission dir (tasks.json, task-state.json, contract-state.json,
        attempts/*.json)."""
        return self.zenith_runtime_dir(project_id) / "missions" / mission_id

    # ------------------------------------------------------------------
    # Project lifecycle
    # ------------------------------------------------------------------

    def generate_project_id(self, brief: str) -> str:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        first_line = brief.strip().splitlines()[0] if brief.strip() else "project"
        return f"{ts}-{slugify(first_line, 'project')}"

    def create_project(
        self,
        brief: str,
        workspace_dir: str | Path,
        *,
        project_id: str | None = None,
    ) -> ProjectRecord:
        ws = Path(workspace_dir).expanduser().resolve()
        if not ws.exists():
            raise FileNotFoundError(f"workspace_dir does not exist: {ws}")
        pid = project_id or self.generate_project_id(brief)

        zenith = self.zenith_dir(pid)
        runtime = self.zenith_runtime_dir(pid)

        # 1) Durable layout (.zenith/)
        zenith.mkdir(parents=True, exist_ok=True)
        (zenith / "decisions").mkdir(parents=True, exist_ok=True)
        (zenith / "skills").mkdir(parents=True, exist_ok=True)
        (zenith / "missions").mkdir(parents=True, exist_ok=True)

        # 2) Cursor layout (.zenith-runtime/)
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / "missions").mkdir(parents=True, exist_ok=True)

        # 3) brief.md (atomic; do not overwrite if exists)
        brief_path = zenith / "brief.md"
        if not brief_path.exists():
            atomic_write_text(brief_path, brief.rstrip() + "\n")

        # 4) AGENTS.md placeholder
        agents_md = zenith / "AGENTS.md"
        if not agents_md.exists():
            atomic_write_text(
                agents_md,
                "# Project operational guidance\n\n"
                "Edit this file as the project's conventions emerge.\n",
            )

        # 5) MEMORY.md placeholder
        memory_md = zenith / "MEMORY.md"
        if not memory_md.exists():
            atomic_write_text(
                memory_md,
                "# Project memory\n\n"
                "Record concise reusable mission facts here. Do not paste transcripts.\n",
            )

        # 6) Import existing repo-native host skills, then seed bundled skills
        #    into the bucket so host-agent native
        #    discovery via the workspace shim has content from day one.
        self._import_workspace_skills(ws, zenith / "skills")
        self._seed_bundled_skills(zenith / "skills")

        # 7) Workspace symlink shims (host-agent native discovery surface).
        self._ensure_symlink_shims(ws, zenith)

        # 8) project.json (orchestrator-only cursor)
        record = ProjectRecord(
            id=pid,
            workspace_dir=str(ws),
            created_at=utc_now_iso(),
        )
        atomic_write_json(runtime / "project.json", record.model_dump(mode="json"))
        return record

    def load_project(self, project_id: str) -> ProjectRecord:
        path = self.zenith_runtime_dir(project_id) / "project.json"
        if not path.exists():
            raise FileNotFoundError(f"project not found: {project_id}")
        return ProjectRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def save_project(self, record: ProjectRecord) -> None:
        atomic_write_json(
            self.zenith_runtime_dir(record.id) / "project.json",
            record.model_dump(mode="json"),
        )

    def sync_workspace_skill_surfaces(self, project_id: str) -> None:
        """Refresh workspace-native skill dirs from the project skill bucket.

        Real user-authored host skill directories are preserved; missing bucket
        skills are copied into them. Bootstrap-only host skill directories are
        still converted to symlinks by the same rules used at project creation.
        """
        record = self.load_project(project_id)
        ws = Path(record.workspace_dir).expanduser().resolve()
        zenith = self.zenith_dir(project_id)
        target_skills = zenith / "skills"
        self._import_workspace_skills(ws, target_skills)
        self._seed_bundled_skills(target_skills)
        self._ensure_symlink_shims(ws, zenith)

    def list_projects(self) -> list[ProjectRecord]:
        if not self.config.projects_dir.exists():
            return []
        result: list[ProjectRecord] = []
        for entry in sorted(self.config.projects_dir.iterdir()):
            project_json = entry / ".zenith-runtime" / "project.json"
            if not project_json.exists():
                continue
            try:
                result.append(
                    ProjectRecord.model_validate_json(
                        project_json.read_text(encoding="utf-8")
                    )
                )
            except Exception:
                continue
        result.sort(key=lambda r: r.created_at, reverse=True)
        return result

    # ------------------------------------------------------------------
    # ProjectState (cursor)
    # ------------------------------------------------------------------

    def load_state(self, project_id: str) -> ProjectState | None:
        path = self.zenith_runtime_dir(project_id) / "state.json"
        if not path.exists():
            return None
        from pydantic import TypeAdapter

        return TypeAdapter(ProjectState).validate_json(
            path.read_text(encoding="utf-8")
        )

    def save_state(self, project_id: str, state: ProjectState) -> None:
        atomic_write_json(
            self.zenith_runtime_dir(project_id) / "state.json",
            state.model_dump(mode="json"),
        )

    # ------------------------------------------------------------------
    # Mission DAG + contract
    # ------------------------------------------------------------------

    def generate_mission_id(self, sequence: int) -> str:
        return f"mission-{sequence:03d}"

    def list_missions(self, project_id: str) -> list[str]:
        d = self.zenith_runtime_dir(project_id) / "missions"
        if not d.exists():
            return []
        return sorted(p.name for p in d.iterdir() if p.is_dir())

    def load_task_list(self, project_id: str, mission_id: str) -> TaskList:
        path = self.mission_runtime_dir(project_id, mission_id) / "tasks.json"
        if not path.exists():
            raise FileNotFoundError(f"tasks.json missing for {project_id}/{mission_id}")
        return TaskList.model_validate_json(path.read_text(encoding="utf-8"))

    def save_task_list(self, project_id: str, mission_id: str, tl: TaskList) -> None:
        atomic_write_json(
            self.mission_runtime_dir(project_id, mission_id) / "tasks.json",
            tl.model_dump(mode="json"),
        )

    def contract_dir(self, project_id: str, mission_id: str) -> Path:
        return self.mission_dir(project_id, mission_id) / "contract"

    def ensure_contract_dir(self, project_id: str, mission_id: str) -> Path:
        d = self.contract_dir(project_id, mission_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def list_contract_assertions(
        self, project_id: str, mission_id: str
    ) -> list[str]:
        from .task_validation import parse_contract_dir

        ids, _ = parse_contract_dir(self.contract_dir(project_id, mission_id))
        return sorted(ids)

    def contract_assertion_path(
        self, project_id: str, mission_id: str, assertion_id: str
    ) -> Path:
        return self.contract_dir(project_id, mission_id) / f"{assertion_id}.md"

    def load_contract_assertion(
        self, project_id: str, mission_id: str, assertion_id: str
    ) -> str | None:
        path = self.contract_assertion_path(project_id, mission_id, assertion_id)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    # task-state / contract-state cursors (runtime scope)

    def load_task_state(self, project_id: str, mission_id: str) -> TaskStateFile:
        path = self.mission_runtime_dir(project_id, mission_id) / "task-state.json"
        if not path.exists():
            return TaskStateFile()
        return TaskStateFile.model_validate_json(path.read_text(encoding="utf-8"))

    def save_task_state(
        self, project_id: str, mission_id: str, task_state: TaskStateFile
    ) -> None:
        atomic_write_json(
            self.mission_runtime_dir(project_id, mission_id) / "task-state.json",
            task_state.model_dump(mode="json"),
        )

    def load_contract_state(
        self, project_id: str, mission_id: str
    ) -> ContractStateFile:
        path = (
            self.mission_runtime_dir(project_id, mission_id) / "contract-state.json"
        )
        if not path.exists():
            return ContractStateFile()
        return ContractStateFile.model_validate_json(
            path.read_text(encoding="utf-8")
        )

    def save_contract_state(
        self, project_id: str, mission_id: str, contract_state: ContractStateFile
    ) -> None:
        atomic_write_json(
            self.mission_runtime_dir(project_id, mission_id)
            / "contract-state.json",
            contract_state.model_dump(mode="json"),
        )

    # ------------------------------------------------------------------
    # Attempts
    #   - JSON handoff   → .zenith-runtime/missions/<mid>/attempts/ (orchestrator cursor)
    #   - MD mirror      → .zenith/missions/<mid>/attempts/         (durable, agent-readable)
    # ------------------------------------------------------------------

    def attempts_dir(self, project_id: str, mission_id: str) -> Path:
        """Durable attempt mirrors (agent-readable markdown)."""
        return self.mission_dir(project_id, mission_id) / "attempts"

    def attempts_runtime_dir(self, project_id: str, mission_id: str) -> Path:
        """Orchestrator-only attempt handoffs (worker-written JSON cursors)."""
        return self.mission_runtime_dir(project_id, mission_id) / "attempts"

    def attempt_path(
        self,
        project_id: str,
        mission_id: str,
        spawn_ts: str,
        node_id: str,
    ) -> Path:
        """JSON handoff path — written by the worker MCP server (ZENITH_HANDOFF_PATH)
        and polled by the coordinator. Lives in the runtime cursor tree
        (.zenith-runtime/), not the durable .zenith/ record."""
        return (
            self.attempts_runtime_dir(project_id, mission_id)
            / f"{spawn_ts}__{node_id}.json"
        )

    def attempt_report_path(
        self,
        project_id: str,
        mission_id: str,
        spawn_ts: str,
        node_id: str,
    ) -> Path:
        """Agent-readable markdown mirror (durable .zenith/ record)."""
        return self.attempts_dir(project_id, mission_id) / f"{spawn_ts}__{node_id}.md"

    def save_attempt(
        self,
        project_id: str,
        mission_id: str,
        spawn_ts: str,
        node_id: str,
        handoff: WorkHandoff | ValidateHandoff,
    ) -> Path:
        json_path = self.attempt_path(project_id, mission_id, spawn_ts, node_id)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(json_path, handoff.model_dump(mode="json"))
        md_path = self.attempt_report_path(project_id, mission_id, spawn_ts, node_id)
        atomic_write_text(md_path, attempt_to_markdown(handoff))
        return json_path

    def read_attempt(
        self,
        project_id: str,
        mission_id: str,
        spawn_ts: str,
        node_id: str,
    ) -> WorkHandoff | ValidateHandoff | None:
        path = self.attempt_path(project_id, mission_id, spawn_ts, node_id)
        if not path.exists():
            return None
        return self._parse_attempt(path)

    def list_attempts(
        self,
        project_id: str,
        mission_id: str,
        node_id: str | None = None,
    ) -> list[AttemptRecord]:
        d = self.attempts_runtime_dir(project_id, mission_id)
        if not d.exists():
            return []
        results: list[AttemptRecord] = []
        for entry in sorted(d.glob("*.json")):
            stem = entry.stem
            if "__" not in stem:
                continue
            ts, nid = stem.split("__", 1)
            if node_id is not None and nid != node_id:
                continue
            results.append(AttemptRecord(spawn_ts=ts, node_id=nid, path=entry))
        return results

    @staticmethod
    def _parse_attempt(path: Path) -> WorkHandoff | ValidateHandoff:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict) and ("items" in data or "passed" in data):
            return ValidateHandoff.model_validate(data)
        return WorkHandoff.model_validate(data)

    # ------------------------------------------------------------------
    # Regression ledger (validator-owned, appended via Write tool)
    # ------------------------------------------------------------------

    def regressions_dir(self, project_id: str, mission_id: str) -> Path:
        return self.mission_dir(project_id, mission_id) / "regressions"

    def regression_path(
        self, project_id: str, mission_id: str, assertion_id: str
    ) -> Path:
        return self.regressions_dir(project_id, mission_id) / f"{assertion_id}.md"

    def regression_entry_count(
        self, project_id: str, mission_id: str, assertion_id: str
    ) -> int:
        """Count top-level (`## `) markdown headings as entries."""
        path = self.regression_path(project_id, mission_id, assertion_id)
        if not path.exists():
            return 0
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return 0
        return sum(1 for line in text.splitlines() if line.startswith("## "))

    # ------------------------------------------------------------------
    # Attention queue (cursor scope — orchestrator-only)
    # ------------------------------------------------------------------

    def load_attention(self, project_id: str) -> list[AttentionItemInternal]:
        path = self.zenith_runtime_dir(project_id) / "attention.json"
        if not path.exists():
            return []
        return AttentionFile.model_validate_json(
            path.read_text(encoding="utf-8")
        ).items

    def save_attention(
        self, project_id: str, items: list[AttentionItemInternal]
    ) -> None:
        atomic_write_json(
            self.zenith_runtime_dir(project_id) / "attention.json",
            AttentionFile(items=items).model_dump(mode="json"),
        )

    def clear_attention(self, project_id: str) -> None:
        self.save_attention(project_id, [])

    # ------------------------------------------------------------------
    # Decisions audit
    # ------------------------------------------------------------------

    def decisions_dir(self, project_id: str) -> Path:
        return self.zenith_dir(project_id) / "decisions"

    def next_decision_number(self, project_id: str) -> int:
        d = self.decisions_dir(project_id)
        if not d.exists():
            return 1
        max_n = 0
        for entry in d.glob("*.md"):
            try:
                num = int(entry.stem.split("-", 1)[0])
                max_n = max(max_n, num)
            except (ValueError, IndexError):
                continue
        return max_n + 1

    def append_decision_record(
        self,
        project_id: str,
        decisions: list[Decision],
        items: list[AttentionItemInternal],
        *,
        summary: str = "",
    ) -> Path:
        d = self.decisions_dir(project_id)
        d.mkdir(parents=True, exist_ok=True)
        n = self.next_decision_number(project_id)
        slug = slugify(summary or decisions[0].action if decisions else "decision")
        path = d / f"{n:03d}-{slug}.md"
        parts: list[str] = []
        parts.append(f"# Decision {n:03d}: {summary or 'decide_attention'}")
        parts.append("")
        parts.append(f"- Timestamp: {utc_now_iso()}")
        parts.append("")
        parts.append("## Resolved attention items")
        item_by_id = {it.id: it for it in items}
        for dec in decisions:
            it = item_by_id.get(dec.item_id)
            parts.append(f"### {dec.item_id} — action={dec.action}")
            if it is not None:
                parts.append("- report:")
                parts.append("```")
                parts.append(it.report)
                parts.append("```")
            if dec.justification:
                parts.append(f"- justification: {dec.justification}")
            if dec.patch is not None and not dec.patch.is_empty:
                parts.append("- patch:")
                parts.append("```json")
                parts.append(
                    json.dumps(dec.patch.model_dump(mode="json", by_alias=True), indent=2)
                )
                parts.append("```")
            parts.append("")
        atomic_write_text(path, "\n".join(parts).rstrip() + "\n")
        return path

    # ------------------------------------------------------------------
    # Terminal review
    #   - JSON handoff   -> .zenith-runtime/missions/<mid>/terminal-reviews/
    #   - MD mirror      -> .zenith/missions/<mid>/terminal-reviews/
    # ------------------------------------------------------------------

    def terminal_reviews_dir(self, project_id: str, mission_id: str) -> Path:
        """Durable terminal-review mirrors (agent-readable markdown)."""
        return self.mission_dir(project_id, mission_id) / "terminal-reviews"

    def terminal_reviews_runtime_dir(self, project_id: str, mission_id: str) -> Path:
        """Orchestrator-only terminal-review handoffs (reviewer-written JSON cursors)."""
        return self.mission_runtime_dir(project_id, mission_id) / "terminal-reviews"

    def terminal_review_path(
        self, project_id: str, mission_id: str, spawn_ts: str
    ) -> Path:
        """JSON path — written by the terminal-reviewer MCP server and polled by
        the coordinator. Lives in the runtime cursor tree (.zenith-runtime/),
        not the durable .zenith/ record."""
        return self.terminal_reviews_runtime_dir(project_id, mission_id) / f"{spawn_ts}.json"

    def terminal_review_report_path(
        self, project_id: str, mission_id: str, spawn_ts: str
    ) -> Path:
        """Agent-readable markdown mirror."""
        return self.terminal_reviews_dir(project_id, mission_id) / f"{spawn_ts}.md"

    def terminal_review_config_path(self, project_id: str, mission_id: str) -> Path:
        return self.mission_runtime_dir(project_id, mission_id) / "terminal-review-config.json"

    def load_terminal_review_config(
        self, project_id: str, mission_id: str
    ) -> TerminalReviewConfig:
        path = self.terminal_review_config_path(project_id, mission_id)
        if not path.exists():
            return TerminalReviewConfig()
        return TerminalReviewConfig.model_validate_json(path.read_text(encoding="utf-8"))

    def save_terminal_review_config(
        self, project_id: str, mission_id: str, config: TerminalReviewConfig
    ) -> Path:
        path = self.terminal_review_config_path(project_id, mission_id)
        atomic_write_json(path, config.model_dump(mode="json"))
        return path

    def resolve_terminal_review_roots(
        self, project_id: str, mission_id: str, roots: list[str]
    ) -> list[str]:
        workspace = self.workspace_dir(project_id).resolve()
        mission = self.mission_dir(project_id, mission_id).resolve()
        runtime = self.zenith_runtime_dir(project_id).resolve()
        forbidden = [
            (runtime, "mission"),
            (self.zenith_dir(project_id).resolve() / "decisions", "mission"),
            (self.zenith_dir(project_id).resolve() / "MEMORY.md", "mission"),
            (mission / "contract", "mission"),
            (mission / "attempts", "mission"),
            (mission / "terminal-reviews", "mission"),
            (mission / "closeout.md", "mission"),
            (workspace / ".git", "workspace"),
            (workspace / ".zenith", "workspace"),
            (workspace / ".zenith-runtime", "workspace"),
            (workspace / ".agents", "workspace"),
            (workspace / ".claude", "workspace"),
            (workspace / ".codex", "workspace"),
            (workspace / "AGENTS.md", "workspace"),
        ]
        resolved: list[str] = []
        for raw in roots:
            if any(ord(char) < 32 or ord(char) == 127 for char in raw):
                raise ValueError("terminal-review deliverable path contains control characters")
            candidate = Path(raw).expanduser()
            if not candidate.is_absolute():
                candidate = workspace / candidate
            try:
                target = candidate.resolve(strict=True)
            except FileNotFoundError as exc:
                raise ValueError(f"terminal-review deliverable does not exist: {raw}") from exc
            if not (_is_relative_to(target, workspace) or _is_relative_to(target, mission)):
                raise ValueError(
                    "terminal-review deliverable must be inside the workspace or current "
                    f"mission: {raw}"
                )
            for item, label in forbidden:
                if (
                    target == item
                    or _is_relative_to(target, item)
                    or (target.is_dir() and _is_relative_to(item, target))
                ):
                    raise ValueError(
                        f"terminal-review deliverable is a forbidden {label} artifact: {raw}"
                    )
            if target.is_dir():
                for nested in target.rglob("*"):
                    if not nested.is_symlink():
                        continue
                    try:
                        link_target = nested.resolve(strict=True)
                    except FileNotFoundError as exc:
                        raise ValueError(
                            f"terminal-review deliverable contains a broken symlink: {nested}"
                        ) from exc
                    if not _is_relative_to(link_target, target):
                        raise ValueError(
                            "terminal-review deliverable contains a symlink outside its "
                            f"declared root: {nested}"
                        )
            value = str(target)
            if value not in resolved:
                resolved.append(value)
        return sorted(resolved)

    def save_terminal_review(
        self,
        project_id: str,
        mission_id: str,
        spawn_ts: str,
        review: TerminalReviewHandoff,
    ) -> Path:
        # JSON: fallback only (acp_runner's MCP server normally writes this).
        json_path = self.terminal_review_path(project_id, mission_id, spawn_ts)
        if not json_path.exists():
            json_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(json_path, review.model_dump(mode="json"))
        md_path = self.terminal_review_report_path(project_id, mission_id, spawn_ts)
        atomic_write_text(md_path, terminal_review_to_markdown(review))
        return md_path

    # ------------------------------------------------------------------
    # Mission seal
    # ------------------------------------------------------------------

    def seal_mission(
        self,
        project_id: str,
        mission_id: str,
        *,
        status: str,
        body: str,
    ) -> Path:
        path = self.mission_dir(project_id, mission_id) / "closeout.md"
        header = (
            f"# Mission {mission_id} closeout\n\n"
            f"- status: {status}\n"
            f"- sealed_at: {utc_now_iso()}\n\n"
        )
        atomic_write_text(path, header + body.rstrip() + "\n")
        return path

    # ------------------------------------------------------------------
    # Workspace symlink shims
    # ------------------------------------------------------------------

    def _ensure_symlink_shims(self, workspace: Path, zenith: Path) -> None:
        """Install the four host-agent discovery shims at the workspace root.

        - `<ws>/.agents/skills` → `<zenith>/skills`
        - `<ws>/.claude/skills` → `<zenith>/skills`
        - `<ws>/.codex/skills`  → `<zenith>/skills`
        - `<ws>/AGENTS.md`      → `<zenith>/AGENTS.md`

        Idempotent: skill surfaces are merged or retargeted by
        `_ensure_skills_surface`; `AGENTS.md` is created only when the
        workspace does not already have one.
        """
        target_skills = zenith / "skills"
        target_agents_md = zenith / "AGENTS.md"
        target_skills.mkdir(parents=True, exist_ok=True)
        for host in (".agents", ".claude", ".codex"):
            host_dir = workspace / host
            host_dir.mkdir(parents=True, exist_ok=True)
            self._ensure_skills_surface(host_dir / "skills", target_skills)
        self._ensure_agents_surface(workspace / "AGENTS.md", target_agents_md)

    def _ensure_skills_surface(self, link: Path, target: Path) -> None:
        """Expose aggregate bucket skills without replacing real repo skill dirs."""
        target_abs = target.resolve() if target.exists() else target
        if link.is_symlink():
            try:
                if not link.exists():
                    link.unlink()
                    link.symlink_to(target_abs)
                    return
                if link.resolve() == target_abs:
                    return
                return
            except OSError:
                return
        if link.exists():
            if link.is_dir():
                if self._is_bootstrap_skill_dir(link):
                    shutil.rmtree(link)
                    link.symlink_to(target_abs)
                    return
                self._copy_missing_tree(target_abs, link)
            return
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target_abs)

    @staticmethod
    def _ensure_agents_surface(link: Path, target: Path) -> None:
        """Create the AGENTS.md shim only when the workspace has no AGENTS.md."""
        if os.path.lexists(link):
            return
        target_abs = target.resolve() if target.exists() else target
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target_abs)

    def _is_bootstrap_skill_dir(self, path: Path) -> bool:
        """True when a real host skill dir only contains Zenith-seeded skills.

        `zenith init` has to create real skill directories before a project
        bucket exists. Once `start_project` creates the bucket, those bootstrap
        directories should become symlinks so project-authored skills added later
        are visible through `.agents/skills`, `.claude/skills`, and
        `.codex/skills`. Directories containing user-authored or edited content
        are left in place by `_ensure_skills_surface`.
        """
        if not path.is_dir() or path.is_symlink():
            return False
        bundled = self.config.bundled_dir / "skills"
        if not bundled.exists():
            return False
        for src in sorted(path.rglob("*")):
            rel = src.relative_to(path)
            bundled_peer = bundled / rel
            if src.is_symlink():
                return False
            if src.is_dir():
                if not bundled_peer.is_dir():
                    return False
                continue
            if src.is_file():
                if not bundled_peer.is_file():
                    return False
                if src.read_bytes() != bundled_peer.read_bytes():
                    return False
                continue
            return False
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _import_workspace_skills(self, workspace: Path, target: Path) -> None:
        target.mkdir(parents=True, exist_ok=True)
        for host in (".agents", ".claude", ".codex"):
            source = workspace / host / "skills"
            if source.is_dir() and not source.is_symlink():
                self._copy_missing_tree(source, target)

    def _seed_bundled_skills(self, target: Path) -> None:
        """Copy bundled `SKILL.md` files into the bucket if not already
        present. Idempotent and non-overwriting per skill."""
        bundled_skills = self.config.bundled_dir / "skills"
        if not bundled_skills.exists():
            return
        target.mkdir(parents=True, exist_ok=True)
        for skill_dir in sorted(bundled_skills.iterdir()):
            if not skill_dir.is_dir():
                continue
            src = skill_dir / "SKILL.md"
            if not src.exists():
                continue
            dest_dir = target / skill_dir.name
            dest = dest_dir / "SKILL.md"
            if dest.exists():
                continue
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

    @staticmethod
    def _copy_missing_tree(source: Path, target: Path) -> None:
        if not source.is_dir():
            return
        for src in sorted(source.rglob("*")):
            rel = src.relative_to(source)
            dest = target / rel
            if os.path.lexists(dest):
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.is_symlink():
                dest.symlink_to(os.readlink(src))
            elif src.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            elif src.is_file():
                shutil.copy2(src, dest)


__all__ = [
    "ProjectStore",
    "AttemptRecord",
    "utc_now_iso",
    "utc_now_filesafe",
    "slugify",
    "atomic_write_text",
    "atomic_write_json",
    "attempt_to_markdown",
    "terminal_review_to_markdown",
]
