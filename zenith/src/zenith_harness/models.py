"""v5 schemas — task-list shape (see `specs/task_list/PRODUCT.md`).

The authoring vocabulary is intentionally small:
- `Task` + `TaskList` (orchestrator authors at `submit_plan`)
- `TaskListPatch` (orchestrator nests inside `Decision`)
- `Decision`, `AttentionItem` (decide_attention surface)
- `ProjectState`, `Envelope` (runtime surface)
- worker-side handoff types (`WorkHandoff`, `ValidateHandoff`, `TerminalReviewHandoff`)

Attempt filenames keep the `<ts>__<node_id>.json` token for on-disk continuity
— `node_id` reads as task id. WorkHandoff/ValidateHandoff retain the
`node_id` field for the same reason; an eventual rename is deferred.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Identifier conventions
# ---------------------------------------------------------------------------

ASSERTION_ID_REGEX = re.compile(r"^[A-Z][A-Z0-9-]+$")
TASK_ID_REGEX = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
SKILL_NAME_REGEX = re.compile(r"^[a-z][a-z0-9_-]*$")


TaskType = Literal["work", "validate", "gate"]
TaskStatus = Literal["pending", "running", "cleared", "failed", "superseded"]
AssertionStatus = Literal["pending", "passed", "failed"]


# ---------------------------------------------------------------------------
# Task / TaskList (orchestrator authors at submit_plan + via TaskListPatch)
# ---------------------------------------------------------------------------


class Task(BaseModel):
    """A single mission task.

    Dependencies live inline as `depends_on: list[task_id]`. The runtime
    computes "runnable" by checking that every id in `depends_on` is in a
    terminal status (`cleared` or `superseded`).
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Mission-unique task id.")
    type: TaskType = Field(description='"work" | "validate" | "gate"')
    body: str = Field(
        description=(
            "Markdown task body. Work/validate tasks need a specific outcome, "
            "scope, targets, evidence, setup, non-goals, and split rationale "
            "when broad. Gate bodies must be empty — they exist only to seal."
        )
    )
    targets: list[str] = Field(
        description=(
            "Contract assertion ids this task addresses. Work nodes may own one "
            "or multiple related atomic assertions when the implementation boundary "
            "is coherent; every assertion must still have exactly one active work "
            "owner. Validators / gates may bundle several."
        ),
    )
    skill: str | None = Field(
        default=None,
        description=(
            "Skill procedure to load. Required for work/validate; must be null for "
            "gate."
        ),
    )
    auto_merge: bool = Field(
        default=True,
        description=(
            "Legacy no-op. Work tasks always run directly in the project workspace."
        ),
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description=(
            "Upstream task ids that must reach a terminal status before this task "
            "becomes runnable. Dependencies are untyped — gate semantics come from "
            "`type == 'gate'`, not from the dep itself."
        ),
    )


class TaskList(BaseModel):
    """What `submit_plan` accepts. List order is a topological tie-break hint."""

    model_config = ConfigDict(extra="forbid")

    tasks: list[Task] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# TaskListPatch (orchestrator nests inside Decision when action == "patch")
# ---------------------------------------------------------------------------


class TaskListPatch(BaseModel):
    """Four ops. See `specs/task_list/PRODUCT.md` §Patching.

    - `add_items`: new assertion ids (contract files must exist on disk).
    - `add`: new tasks appended to the task list.
    - `supersede`: dict mapping old_id → new_id. Old task marked
      `superseded`; **every `depends_on` reference to old_id in the task
      list is rewritten to new_id in-place**. No runtime chain resolver.
    - `cancel`: list of task ids to remove. Each cancelled task is marked
      `superseded`; **every `depends_on` list is rewritten to drop the
      cancelled id**. Use when a planned task is no longer needed (wrong
      authoring, scope retraction, dead-end discovered).
    """

    model_config = ConfigDict(extra="forbid")

    add_items: list[str] = Field(
        default_factory=list,
        description=(
            "New assertion ids to declare. Matching contract/<id>.md files must "
            "already exist on disk before decide_attention is called."
        ),
    )
    add: list[Task] = Field(
        default_factory=list,
        description="New tasks; appended to the task list. Ids must be globally new.",
    )
    supersede: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Old task id → new task id. The new id must appear in `add` (this patch) "
            "or be an existing non-superseded task. Cleared/running tasks cannot be "
            "superseded. Downstream `depends_on` references are rewritten in-place."
        ),
    )
    cancel: list[str] = Field(
        default_factory=list,
        description=(
            "Task ids to remove without replacement. Cancelled tasks are marked "
            "superseded and dropped from every downstream `depends_on` list. "
            "Cleared/running tasks cannot be cancelled."
        ),
    )

    @property
    def is_empty(self) -> bool:
        return not (self.add_items or self.add or self.supersede or self.cancel)


# ---------------------------------------------------------------------------
# Decision (orchestrator authors in decide_attention)
# ---------------------------------------------------------------------------

ActionName = Literal[
    "continue",
    "patch",
    "retry",
    "next_mission",
    "abort",
]


class Decision(BaseModel):
    """4 fields. See `specs/task_list/PRODUCT.md` §Patching."""

    model_config = ConfigDict(extra="forbid")

    item_id: str
    action: ActionName = Field(
        description=(
            "continue | patch | retry | next_mission | abort. retry is for "
            "transient node_failed attempts only; use patch for changed work, "
            "failed validation, missing assertions, over-broad scope, or task-list "
            "adaptation. next_mission is only for runtime closure-report gaps that "
            "cannot be patched inside the current mission."
        )
    )
    patch: TaskListPatch | None = Field(
        default=None,
        description="Required iff action == patch; must satisfy task-list structural validation.",
    )
    justification: str = Field(
        default="",
        description="Decision rationale, especially for accepted risk, scope change, or why patch/retry/next_mission is appropriate.",
    )


# ---------------------------------------------------------------------------
# Attention (runtime writes, orchestrator reads)
# ---------------------------------------------------------------------------

AttentionKind = Literal[
    "node_failed",
    "node_attention",
    "gate_failed",
    "gate_checkpoint",
    "terminal_review",
]


class AttentionItem(BaseModel):
    """Public attention item: an id plus the raw report to decide from."""

    model_config = ConfigDict(extra="forbid")

    id: str
    report: str


class AttentionItemInternal(AttentionItem):
    """Runtime-only metadata for applying decisions.

    The envelope strips these fields; orchestrators read only id + report.
    """

    model_config = ConfigDict(extra="forbid")

    kind: AttentionKind
    mission_id: str
    node_id: str | None = None

# ---------------------------------------------------------------------------
# ProjectState (discriminated union)
# ---------------------------------------------------------------------------


class _StateBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Draft(_StateBase):
    state: Literal["draft"] = "draft"


class MissionPlanning(_StateBase):
    state: Literal["mission_planning"] = "mission_planning"
    mission_id: str


class MissionRunning(_StateBase):
    state: Literal["mission_running"] = "mission_running"
    mission_id: str


class AttentionNeeded(_StateBase):
    state: Literal["attention_needed"] = "attention_needed"
    items: list[AttentionItem] = Field(default_factory=list)


class Done(_StateBase):
    state: Literal["done"] = "done"


class Failed(_StateBase):
    state: Literal["failed"] = "failed"
    reason: str


class Aborted(_StateBase):
    state: Literal["aborted"] = "aborted"
    reason: str


ProjectState = Annotated[
    Union[
        Draft,
        MissionPlanning,
        MissionRunning,
        AttentionNeeded,
        Done,
        Failed,
        Aborted,
    ],
    Field(discriminator="state"),
]


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


class Envelope(BaseModel):
    """Returned by every MCP tool.

    `dag` is a text view of the task list (kept named `dag` for
    envelope-surface stability).
    """

    model_config = ConfigDict(extra="forbid")

    projectId: str
    state: ProjectState
    projectRoot: str
    harnessRoot: str
    dag: str | None = None


# ---------------------------------------------------------------------------
# Worker-side handoff schemas (written by spawned sessions, read off disk)
# ---------------------------------------------------------------------------


class WorkHandoff(BaseModel):
    """Written by work tasks via `end_node`.

    Field `node_id` is retained as the on-disk attempt filename token —
    interpreted as task id. Rename deferred.
    """

    model_config = ConfigDict(extra="forbid")

    node_id: str
    done: bool
    report: str
    request_attention: bool = False


class ValidationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    passed: bool


class ValidateHandoff(BaseModel):
    """Written by validate tasks via `end_node`."""

    model_config = ConfigDict(extra="forbid")

    node_id: str
    done: bool = True
    report: str = ""
    items: list[ValidationItem] = Field(default_factory=list)
    passed: bool = False
    request_attention: bool = False


class TerminalReviewHandoff(BaseModel):
    """Written by the terminal reviewer via `submit_terminal_review`."""

    model_config = ConfigDict(extra="forbid")

    done: bool
    report: str = ""


class TerminalReviewConfig(BaseModel):
    """Explicit artifacts allowed as objects of independent closure review."""

    model_config = ConfigDict(extra="forbid")

    deliverable_roots: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# On-disk runtime cursors (HARNESS bucket; orchestrator-internal)
# ---------------------------------------------------------------------------


class TaskStateEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TaskStatus = "pending"
    last_attempt: str | None = None  # spawn_ts of most recent dispatch


class TaskStateFile(BaseModel):
    """Live cursor: per-task status. HARNESS bucket.

    `supersede` and `cancel` patch ops rewrite downstream `depends_on`
    references in `tasks.json` directly — runtime dep-satisfaction is the
    simple `status == cleared` check. The chain mapping lives implicitly in
    the post-patch task list shape; the audit trail of "why" lives in
    `decisions/NNN.md`.
    """

    model_config = ConfigDict(extra="forbid")

    tasks: dict[str, TaskStateEntry] = Field(default_factory=dict)

    def status_of(self, task_id: str) -> TaskStatus:
        entry = self.tasks.get(task_id)
        return entry.status if entry else "pending"

    def set_status(self, task_id: str, status: TaskStatus) -> None:
        entry = self.tasks.setdefault(task_id, TaskStateEntry())
        entry.status = status

    def set_last_attempt(self, task_id: str, spawn_ts: str) -> None:
        entry = self.tasks.setdefault(task_id, TaskStateEntry())
        entry.last_attempt = spawn_ts


class ContractStateEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AssertionStatus = "pending"


class ContractStateFile(BaseModel):
    """Live cursor: per-assertion verdict. HARNESS bucket."""

    model_config = ConfigDict(extra="forbid")

    items: dict[str, ContractStateEntry] = Field(default_factory=dict)


class ProjectRecord(BaseModel):
    """Immutable: id, workspace_dir, created_at. HARNESS bucket."""

    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_dir: str
    created_at: str
    current_mission_id: str | None = None


class AttentionFile(BaseModel):
    """List of open AttentionItemInternal entries. HARNESS bucket."""

    model_config = ConfigDict(extra="forbid")

    items: list[AttentionItemInternal] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Asset loader return type
# ---------------------------------------------------------------------------


class LoadedMarkdownAsset(BaseModel):
    name: str
    description: str | None = None
    source: Literal["project", "personal", "bundled"]
    path: str
    rawText: str
    body: str
    frontmatter: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ASSERTION_ID_REGEX",
    "TASK_ID_REGEX",
    "SKILL_NAME_REGEX",
    "TaskType",
    "TaskStatus",
    "AssertionStatus",
    "ActionName",
    "AttentionKind",
    "Task",
    "TaskList",
    "TaskListPatch",
    "Decision",
    "AttentionItem",
    "AttentionItemInternal",
    "Draft",
    "MissionPlanning",
    "MissionRunning",
    "AttentionNeeded",
    "Done",
    "Failed",
    "Aborted",
    "ProjectState",
    "Envelope",
    "WorkHandoff",
    "ValidationItem",
    "ValidateHandoff",
    "TerminalReviewHandoff",
    "TerminalReviewConfig",
    "TaskStateEntry",
    "TaskStateFile",
    "ContractStateEntry",
    "ContractStateFile",
    "ProjectRecord",
    "AttentionFile",
    "LoadedMarkdownAsset",
]
