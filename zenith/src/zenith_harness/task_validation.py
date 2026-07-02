"""Pure functions for task-list structural validation.

See `specs/task_list/PRODUCT.md` §Flow §Authoring.

Every function returns `list[ValidationError]`. The caller assembles errors
into the response payload. All checks operate on pure data — no I/O —
except `parse_contract_dir` which lists a directory.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import (
    ASSERTION_ID_REGEX,
    TASK_ID_REGEX,
    Task,
    TaskList,
    TaskStateFile,
)


@dataclass(frozen=True)
class ValidationError:
    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


# ---------------------------------------------------------------------------
# Contract parsing
# ---------------------------------------------------------------------------


def parse_contract_dir(contract_dir: str | Path) -> tuple[set[str], list[ValidationError]]:
    """List `*.md` files under `contract_dir`, return assertion ids + errors.

    - Returns the stem of each `.md` file as an assertion id.
    - Excludes `README.md`.
    - Reports `invalid_assertion_filename` for any stem that fails the id regex.
    - Reports `contract_dir_missing` if the directory does not exist.
    """
    path = Path(contract_dir)
    if not path.exists() or not path.is_dir():
        return set(), [
            ValidationError("contract_dir_missing", str(path))
        ]

    ids: set[str] = set()
    errors: list[ValidationError] = []
    for entry in sorted(path.glob("*.md")):
        stem = entry.stem
        if stem == "README":
            continue
        if not ASSERTION_ID_REGEX.fullmatch(stem):
            errors.append(
                ValidationError(
                    "invalid_assertion_filename",
                    f"{entry.name} (stem '{stem}' does not match {ASSERTION_ID_REGEX.pattern})",
                )
            )
            continue
        if stem in ids:
            errors.append(
                ValidationError("duplicate_assertion_filename", stem)
            )
            continue
        ids.add(stem)
    return ids, errors


# ---------------------------------------------------------------------------
# Task-level checks
# ---------------------------------------------------------------------------


def check_task_ids(tl: TaskList) -> list[ValidationError]:
    """Each task id matches the regex; all unique."""
    errors: list[ValidationError] = []
    seen: set[str] = set()
    for task in tl.tasks:
        if not TASK_ID_REGEX.fullmatch(task.id):
            errors.append(ValidationError("invalid_task_id", task.id))
        if task.id in seen:
            errors.append(ValidationError("duplicate_task_id", task.id))
        seen.add(task.id)
    return errors


def check_task_shape(tl: TaskList) -> list[ValidationError]:
    """Field-level rules per task type.

    - gate: skill must be None; body must be empty; targets ≥ 1.
    - work: skill required; body required; targets may be empty (discovery
      / integration nodes per the engineering / optimization playbooks).
    - validate: skill required; body required; targets ≥ 1.
    """
    errors: list[ValidationError] = []
    for task in tl.tasks:
        if task.type == "gate":
            if task.skill is not None:
                errors.append(ValidationError("gate_with_skill", task.id))
            if task.body.strip():
                errors.append(ValidationError("gate_with_body", task.id))
            if not task.targets:
                errors.append(ValidationError("empty_targets", task.id))
        else:
            if not task.skill:
                errors.append(
                    ValidationError("non_gate_without_skill", f"{task.id} (type={task.type})")
                )
            if not task.body.strip():
                errors.append(ValidationError("missing_body", task.id))
            if task.type == "validate" and not task.targets:
                errors.append(ValidationError("empty_targets", task.id))
    return errors


def check_skill_names(
    tl: TaskList,
    available_skills: set[str] | list[str] | tuple[str, ...],
) -> list[ValidationError]:
    """Non-gate task skills must resolve to an available skill name."""
    available = set(available_skills)
    errors: list[ValidationError] = []
    for task in tl.tasks:
        if task.type == "gate" or not task.skill:
            continue
        if task.skill not in available:
            if available:
                detail = (
                    f"{task.id} references unknown skill {task.skill!r}; "
                    f"available: {', '.join(sorted(available))}"
                )
            else:
                detail = (
                    f"{task.id} references unknown skill {task.skill!r}; "
                    "no skills are available"
                )
            errors.append(ValidationError("unknown_skill", detail))
    return errors


def check_deps_resolve(tl: TaskList) -> list[ValidationError]:
    """All `depends_on` ids reference declared tasks; no self-loop."""
    errors: list[ValidationError] = []
    ids = {t.id for t in tl.tasks}
    for task in tl.tasks:
        for dep in task.depends_on:
            if dep == task.id:
                errors.append(ValidationError("self_loop", task.id))
            elif dep not in ids:
                errors.append(
                    ValidationError(
                        "dep_unknown_task",
                        f"{task.id} -> {dep}",
                    )
                )
    return errors


def check_acyclic(tl: TaskList) -> list[ValidationError]:
    """Kahn's algorithm on the adjacency-list shape."""
    indeg: dict[str, int] = {t.id: 0 for t in tl.tasks}
    adj: dict[str, list[str]] = {t.id: [] for t in tl.tasks}
    for task in tl.tasks:
        for dep in task.depends_on:
            if dep in indeg:
                indeg[task.id] += 1
                adj[dep].append(task.id)
    queue = [tid for tid, d in indeg.items() if d == 0]
    visited = 0
    while queue:
        current = queue.pop(0)
        visited += 1
        for nxt in adj[current]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    if visited != len(tl.tasks):
        cycle = sorted(tid for tid, d in indeg.items() if d > 0)
        return [
            ValidationError(
                "cycle_detected",
                f"tasks still in cycle: {', '.join(cycle)}",
            )
        ]
    return []


def check_coverage(
    contract_ids: set[str],
    tl: TaskList,
    *,
    task_status: TaskStateFile | None = None,
) -> list[ValidationError]:
    """Every assertion ↔ exactly one non-superseded work task.

    Also rejects:
    - `task_targets_unknown_assertion`: a task references an assertion id not
      present in the contract directory.
    - `uncovered_assertion`: an assertion has zero fulfilling work tasks.
    - `over_covered_assertion`: an assertion has >1 fulfilling work tasks.
    """
    errors: list[ValidationError] = []
    coverers: dict[str, list[str]] = {a: [] for a in contract_ids}
    for task in tl.tasks:
        status = "pending"
        if task_status is not None:
            status = task_status.status_of(task.id)
        for tgt in task.targets:
            if tgt not in contract_ids:
                errors.append(
                    ValidationError(
                        "task_targets_unknown_assertion",
                        f"task {task.id} targets unknown assertion {tgt!r}",
                    )
                )
        if task.type == "work" and status != "superseded":
            for tgt in task.targets:
                if tgt in coverers:
                    coverers[tgt].append(task.id)
    for assertion, tasks in coverers.items():
        if not tasks:
            errors.append(ValidationError("uncovered_assertion", assertion))
        elif len(tasks) > 1:
            errors.append(
                ValidationError(
                    "over_covered_assertion",
                    f"{assertion} covered by [{', '.join(sorted(tasks))}]",
                )
            )
    return errors


# ---------------------------------------------------------------------------
# Combined submit-time checks
# ---------------------------------------------------------------------------


def validate_task_list_submission(
    contract_ids: set[str],
    tl: TaskList,
) -> list[ValidationError]:
    """Run all submit-time checks. Stops at the first failing check group."""
    if not tl.tasks:
        return [ValidationError("empty_task_list", "submit_plan requires at least one task")]
    errs = check_task_ids(tl)
    if errs:
        return errs
    errs = check_task_shape(tl)
    if errs:
        return errs
    errs = check_deps_resolve(tl)
    if errs:
        return errs
    errs = check_acyclic(tl)
    if errs:
        return errs
    errs = check_coverage(contract_ids, tl)
    if errs:
        return errs
    return []


# ---------------------------------------------------------------------------
# Navigation helpers (used by coordinator)
# ---------------------------------------------------------------------------


def predecessors_of(tl: TaskList, task_id: str) -> list[str]:
    """Direct upstream task ids (the `depends_on` field of `task_id`)."""
    for task in tl.tasks:
        if task.id == task_id:
            return list(task.depends_on)
    return []


def successors_of(tl: TaskList, task_id: str) -> list[str]:
    """Direct downstream task ids — tasks that name `task_id` in `depends_on`."""
    return [t.id for t in tl.tasks if task_id in t.depends_on]


def gates_in_order(tl: TaskList) -> list[Task]:
    """Gates sorted by id for determinism."""
    return sorted([t for t in tl.tasks if t.type == "gate"], key=lambda t: t.id)


def upstream_tasks(
    tl: TaskList,
    task_id: str,
    *,
    predicate=None,
) -> list[Task]:
    """All transitive upstream tasks (predecessors of predecessors of ...).

    If `predicate(task)` is given, only tasks matching it are returned. The
    traversal still walks through non-matching nodes.
    """
    by_id = {t.id: t for t in tl.tasks}
    seen: set[str] = set()
    out: list[Task] = []
    stack: list[str] = list(predecessors_of(tl, task_id))
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in by_id:
            continue
        seen.add(cur)
        node = by_id[cur]
        if predicate is None or predicate(node):
            out.append(node)
        stack.extend(node.depends_on)
    return out


__all__ = [
    "ValidationError",
    "parse_contract_dir",
    "check_task_ids",
    "check_task_shape",
    "check_skill_names",
    "check_deps_resolve",
    "check_acyclic",
    "check_coverage",
    "validate_task_list_submission",
    "predecessors_of",
    "successors_of",
    "gates_in_order",
    "upstream_tasks",
]
