"""ProjectController — routes the 8 orchestrator MCP tools.

See `specs/task_list/PRODUCT.md`. The controller owns:
- envelope construction
- decide_attention validation
- TaskListPatch application via task_list_patch.apply_patch()
- resume-from-disk on every tool call

The coordinator is constructed per-invocation; it has no in-memory state.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .config import HarnessConfig
from .coordinator import MissionCoordinator
from .dispatcher import NodeDispatcher, TerminalReviewer
from .envelope import EnvelopeDagMode, make_envelope
from .models import (
    AttentionItemInternal,
    AttentionNeeded,
    Aborted,
    ContractStateFile,
    Decision,
    Draft,
    Envelope,
    MissionPlanning,
    MissionRunning,
    ProjectState,
    TaskListPatch,
    TaskPlaceholderBindingAudit,
    TaskList,
    TaskStateFile,
)
from .storage import ProjectStore, task_list_digest, utc_now_iso
from .task_list_patch import apply_patch
from .task_validation import (
    ValidationError,
    parse_contract_dir,
    validate_task_list_submission,
)


@dataclass
class ToolError(Exception):
    code: str
    message: str
    details: list[ValidationError] | None = None

    def __str__(self) -> str:
        if self.details:
            tail = "; ".join(str(d) for d in self.details)
            return f"{self.code}: {self.message} ({tail})"
        return f"{self.code}: {self.message}"


class ProjectController:
    def __init__(
        self,
        config: HarnessConfig,
        dispatcher: NodeDispatcher,
        terminal_reviewer: TerminalReviewer,
        *,
        store: ProjectStore | None = None,
    ):
        self.config = config
        self.store = store or ProjectStore(config)
        self.dispatcher = dispatcher
        self.terminal_reviewer = terminal_reviewer

    # ------------------------------------------------------------------
    # Tool methods
    # ------------------------------------------------------------------

    def start_project(self, brief: str, workspace_dir: str) -> Envelope:
        if not brief.strip():
            raise ToolError("invalid_brief", "brief is empty")
        record = self.store.create_project(brief, workspace_dir)
        mission_id = self.store.generate_mission_id(1)
        record.current_mission_id = mission_id
        self.store.save_project(record)
        self.store.save_state(
            record.id, MissionPlanning(mission_id=mission_id)
        )
        return self._build_envelope(record.id, dag_mode="none")

    def submit_plan(self, project_id: str, task_list: TaskList) -> Envelope:
        state = self._require_state(project_id)
        if not isinstance(state, MissionPlanning):
            raise ToolError(
                "wrong_state",
                f"submit_plan requires MissionPlanning; got {state.state}",
            )
        mid = state.mission_id
        contract_dir = self.store.ensure_contract_dir(project_id, mid)
        ids, parse_errs = parse_contract_dir(contract_dir)
        if parse_errs:
            raise ToolError(
                "invalid_contract_dir",
                "contract directory invalid",
                details=parse_errs,
            )
        errs = validate_task_list_submission(ids, task_list)
        if errs:
            raise ToolError(
                "invalid_task_list", "task list validation failed", details=errs
            )

        self.store.save_task_list(
            project_id, mid, task_list, preserve_binding_audit=False
        )
        task_state = TaskStateFile()
        for task in task_list.tasks:
            task_state.set_status(task.id, "pending")
        self.store.save_task_state(project_id, mid, task_state)
        cs = ContractStateFile()
        for aid in ids:
            cs.items.setdefault(aid, _make_pending())
        self.store.save_contract_state(project_id, mid, cs)
        self.store.save_state(project_id, MissionRunning(mission_id=mid))
        return self._build_envelope(project_id, dag_mode="frontier")

    def bind_task_placeholders(
        self,
        project_id: str,
        task_id: str,
        bindings: dict[str, str],
    ) -> Envelope:
        with self.store.project_lock(project_id):
            return self._bind_task_placeholders(project_id, task_id, bindings)

    def _bind_task_placeholders(
        self,
        project_id: str,
        task_id: str,
        bindings: dict[str, str],
    ) -> Envelope:
        """Bind one task's placeholders exactly once before any dispatch."""
        state = self._require_state(project_id)
        if not isinstance(state, MissionRunning):
            raise ToolError(
                "wrong_state",
                f"bind_task_placeholders requires MissionRunning; got {state.state}",
            )
        mid = state.mission_id

        try:
            existing_audit = self.store.load_task_binding_audit(project_id, mid)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(
                "invalid_task_binding_audit",
                "task binding audit is invalid",
            ) from exc
        if existing_audit is not None:
            raise ToolError(
                "task_binding_already_applied",
                "task placeholders already bound for this mission",
            )

        task_list = self.store.load_task_list(project_id, mid)
        task_state = self.store.load_task_state(project_id, mid)
        task_ids = {task.id for task in task_list.tasks}
        if set(task_state.tasks) != task_ids:
            raise ToolError(
                "invalid_task_state",
                "task state must contain exactly one entry per task",
            )
        if any(
            entry.status != "pending" or entry.last_attempt is not None
            for entry in task_state.tasks.values()
        ):
            raise ToolError(
                "invalid_task_state",
                "all task states must be pending with no last_attempt",
            )
        if self.store.list_attempts(project_id, mid):
            raise ToolError(
                "attempts_exist",
                "task binding requires no existing attempts",
            )

        task = next((candidate for candidate in task_list.tasks if candidate.id == task_id), None)
        if task is None:
            raise ToolError("unknown_task", f"task {task_id!r} not found")
        if task.type == "gate":
            raise ToolError("gate_task", f"task {task_id!r} is a gate and cannot be bound")

        if not isinstance(bindings, dict) or not bindings:
            raise ToolError("empty_bindings", "bindings must not be empty")
        for placeholder, replacement in bindings.items():
            if not isinstance(placeholder, str) or not isinstance(replacement, str):
                raise ToolError(
                    "invalid_binding",
                    "placeholder and replacement must be strings",
                )

        spans: list[tuple[int, int, str, str]] = []
        for placeholder in sorted(bindings):
            replacement = bindings[placeholder]
            if not placeholder.strip():
                raise ToolError("empty_placeholder", "placeholder must not be empty")
            if not replacement.strip():
                raise ToolError("empty_replacement", "replacement must not be empty")
            if placeholder == replacement:
                raise ToolError(
                    "identical_binding",
                    "placeholder and replacement must differ",
                )

            start = task.body.find(placeholder)
            if start < 0:
                raise ToolError(
                    "placeholder_missing",
                    "placeholder must occur exactly once in task body",
                )
            second = task.body.find(placeholder, start + len(placeholder))
            if second >= 0:
                raise ToolError(
                    "ambiguous_placeholder",
                    "placeholder occurs more than once in task body",
                )
            spans.append((start, start + len(placeholder), placeholder, replacement))

        spans.sort(key=lambda span: (span[0], span[1], span[2]))
        for previous, current in zip(spans, spans[1:]):
            if current[0] < previous[1]:
                raise ToolError(
                    "ambiguous_placeholder",
                    "placeholder occurrences overlap",
                )

        body_parts: list[str] = []
        cursor = 0
        for start, end, _, replacement in spans:
            body_parts.append(task.body[cursor:start])
            body_parts.append(replacement)
            cursor = end
        body_parts.append(task.body[cursor:])
        bound_task = task.model_copy(update={"body": "".join(body_parts)})
        bound_task_list = TaskList(
            tasks=[
                bound_task if candidate.id == task_id else candidate
                for candidate in task_list.tasks
            ]
        )

        contract_ids, parse_errs = parse_contract_dir(
            self.store.contract_dir(project_id, mid)
        )
        if parse_errs:
            raise ToolError(
                "invalid_contract_dir",
                "contract directory invalid",
                details=parse_errs,
            )
        validation_errs = validate_task_list_submission(contract_ids, bound_task_list)
        if validation_errs:
            raise ToolError(
                "invalid_task_list",
                "task list validation failed",
                details=validation_errs,
            )

        audit = TaskPlaceholderBindingAudit(
            task_id=task_id,
            before_task_list_sha256=task_list_digest(task_list),
            after_task_list_sha256=task_list_digest(bound_task_list),
            bindings={
                placeholder: hashlib.sha256(replacement.encode("utf-8")).hexdigest()
                for placeholder, replacement in sorted(bindings.items())
            },
            bound_at=utc_now_iso(),
        )
        try:
            self.store.save_task_list_with_binding_audit(
                project_id,
                mid,
                bound_task_list,
                audit,
            )
        except FileExistsError as exc:
            raise ToolError(
                "task_binding_already_applied",
                "task placeholders already bound for this mission",
            ) from exc
        return self._build_envelope(project_id, dag_mode="frontier")

    def advance_project(
        self,
        project_id: str,
        max_steps: int | None = None,
    ) -> Envelope:
        with self.store.project_lock(project_id):
            return self._advance_project(project_id, max_steps)

    def _advance_project(
        self,
        project_id: str,
        max_steps: int | None = None,
    ) -> Envelope:
        self._verify_task_binding_audit(project_id)
        self.store.sync_workspace_skill_surfaces(project_id)
        coordinator = MissionCoordinator(
            self.store, project_id, self.dispatcher, self.terminal_reviewer
        )
        steps = 0
        while True:
            result = coordinator.step()
            if result.kind in ("attention_needed", "terminal", "idle"):
                break
            steps += 1
            if max_steps is not None and steps >= max_steps:
                break
        self.store.sync_workspace_skill_surfaces(project_id)
        return self._build_envelope(project_id, dag_mode="frontier")

    def end_mission(self, project_id: str) -> Envelope:
        with self.store.project_lock(project_id):
            return self._end_mission(project_id)

    def _end_mission(self, project_id: str) -> Envelope:
        state = self._require_state(project_id)
        if not isinstance(state, MissionRunning):
            raise ToolError(
                "wrong_state",
                f"end_mission requires MissionRunning; got {state.state}",
            )
        self._verify_task_binding_audit(project_id)
        coordinator = MissionCoordinator(
            self.store, project_id, self.dispatcher, self.terminal_reviewer
        )
        result = coordinator.close_mission(state.mission_id)
        if result.kind == "idle":
            raise ToolError(
                "mission_not_ready_to_close",
                result.detail or "mission still has runnable task work",
            )
        return self._build_envelope(project_id, dag_mode="none")

    def decide_attention(
        self,
        project_id: str,
        decisions: list[Decision],
    ) -> Envelope:
        state = self._require_state(project_id)
        if not isinstance(state, AttentionNeeded):
            raise ToolError(
                "wrong_state",
                f"decide_attention requires AttentionNeeded; got {state.state}",
            )
        open_items = self.store.load_attention(project_id)
        validation_errs = self._validate_decisions(decisions, open_items)
        if validation_errs:
            raise ToolError(
                "invalid_decisions",
                "decision validation failed",
                details=validation_errs,
            )
        item_by_id = {it.id: it for it in open_items}
        next_state = self._apply_decisions(project_id, decisions, item_by_id)
        self.store.append_decision_record(project_id, decisions, open_items)
        self.store.clear_attention(project_id)
        self.store.save_state(project_id, next_state)
        return self._build_envelope(project_id, dag_mode="none")

    def inspect_project(self, project_id: str) -> Envelope:
        return self._build_envelope(project_id, dag_mode="full")

    def abort_project(self, project_id: str, reason: str) -> Envelope:
        record = self.store.load_project(project_id)
        state = self.store.load_state(project_id)
        mid = self._current_mission_id(record, state)
        if mid:
            try:
                self.store.seal_mission(
                    project_id, mid, status="aborted", body=reason
                )
            except FileNotFoundError:
                pass
        self.store.clear_attention(project_id)
        self.store.save_state(project_id, Aborted(reason=reason))
        return self._build_envelope(project_id, dag_mode="none")

    # ------------------------------------------------------------------
    # Decision pipeline
    # ------------------------------------------------------------------

    def _validate_decisions(
        self,
        decisions: list[Decision],
        open_items: list[AttentionItemInternal],
    ) -> list[ValidationError]:
        errs: list[ValidationError] = []
        item_ids = {it.id for it in open_items}
        decided_ids = {d.item_id for d in decisions}
        for missing in sorted(item_ids - decided_ids):
            errs.append(ValidationError("unresolved_attention_item", missing))
        for extra in sorted(decided_ids - item_ids):
            errs.append(ValidationError("unknown_attention_item", extra))
        seen: set[str] = set()
        for dec in decisions:
            if dec.item_id in seen:
                errs.append(
                    ValidationError("duplicate_decision", dec.item_id)
                )
            seen.add(dec.item_id)
        item_by_id = {it.id: it for it in open_items}
        for dec in decisions:
            it = item_by_id.get(dec.item_id)
            if it is None:
                continue
            if dec.action == "retry" and it.kind != "node_failed":
                errs.append(
                    ValidationError("invalid_action", "retry is only valid for node_failed")
                )
            if dec.action == "next_mission" and it.kind != "terminal_review":
                errs.append(
                    ValidationError(
                        "invalid_action",
                        "next_mission is only valid for runtime closure reports",
                    )
                )
            if dec.action == "patch":
                if dec.patch is None:
                    errs.append(
                        ValidationError(
                            "missing_patch",
                            f"item {dec.item_id} action=patch requires patch",
                        )
                    )
                elif dec.patch.is_empty:
                    errs.append(
                        ValidationError("empty_patch", dec.item_id)
                    )
        return errs

    def _apply_decisions(
        self,
        project_id: str,
        decisions: list[Decision],
        item_by_id: dict[str, AttentionItemInternal],
    ) -> ProjectState:
        next_state: ProjectState | None = None
        for dec in decisions:
            item = item_by_id[dec.item_id]
            outcome = self._apply_one(project_id, item, dec)
            if outcome is not None:
                next_state = outcome
        if next_state is not None:
            return next_state
        record = self.store.load_project(project_id)
        mid = record.current_mission_id
        if mid:
            return MissionRunning(mission_id=mid)
        return Draft()

    def _apply_one(
        self,
        project_id: str,
        item: AttentionItemInternal,
        decision: Decision,
    ) -> ProjectState | None:
        mid = item.mission_id
        kind = item.kind
        action = decision.action

        if action == "patch":
            assert decision.patch is not None
            self._apply_task_list_patch(project_id, mid, decision.patch)
            task_state = self.store.load_task_state(project_id, mid)
            # A task superseded or cancelled by this same patch is already
            # marked `superseded` by apply_patch — do not reset it to pending.
            retired_ids = (
                set(decision.patch.supersede.keys()) | set(decision.patch.cancel)
            )
            if kind in ("node_failed", "gate_failed") and item.node_id:
                if item.node_id not in retired_ids:
                    task_state.set_status(item.node_id, "pending")
            self.store.save_task_state(project_id, mid, task_state)
            return MissionRunning(mission_id=mid)

        if action == "retry" and item.node_id:
            ts = self.store.load_task_state(project_id, mid)
            ts.set_status(item.node_id, "pending")
            self.store.save_task_state(project_id, mid, ts)
            return MissionRunning(mission_id=mid)

        if action == "continue":
            if kind in ("node_failed", "gate_failed") and item.node_id:
                ts = self.store.load_task_state(project_id, mid)
                ts.set_status(item.node_id, "cleared")
                self.store.save_task_state(project_id, mid, ts)
                return MissionRunning(mission_id=mid)
            if kind == "terminal_review":
                return None
            return MissionRunning(mission_id=mid)

        if action == "abort":
            return Aborted(reason=decision.justification or "aborted")

        if action == "next_mission":
            return self._seal_and_plan_next(project_id, mid)

        return None

    def _seal_and_plan_next(self, project_id: str, mid: str) -> ProjectState:
        self.store.seal_mission(
            project_id,
            mid,
            status="done_with_acknowledged_gaps",
            body="Sealed with gap(s) acknowledged via next_mission decision.",
        )
        existing = self.store.list_missions(project_id)
        new_mid = self.store.generate_mission_id(len(existing) + 1)
        record = self.store.load_project(project_id)
        record.current_mission_id = new_mid
        self.store.save_project(record)
        return MissionPlanning(mission_id=new_mid)

    def _apply_task_list_patch(
        self, project_id: str, mid: str, patch: TaskListPatch
    ) -> None:
        tl = self.store.load_task_list(project_id, mid)
        task_state = self.store.load_task_state(project_id, mid)
        contract_state = self.store.load_contract_state(project_id, mid)
        old_ids = set(contract_state.items.keys())
        all_ids_on_disk = set(self.store.list_contract_assertions(project_id, mid))
        new_on_disk = all_ids_on_disk - old_ids

        patched_tl, patched_state, patched_ids, errs = apply_patch(
            tl,
            task_state,
            old_ids,
            patch,
            new_contract_ids_on_disk=new_on_disk,
        )
        if errs:
            raise ToolError(
                "invalid_patch", "patch validation failed", details=errs
            )
        self.store.save_task_list(project_id, mid, patched_tl)
        self.store.save_task_state(project_id, mid, patched_state)
        cs = self.store.load_contract_state(project_id, mid)
        for aid in patched_ids - old_ids:
            cs.items.setdefault(aid, _make_pending())
        self.store.save_contract_state(project_id, mid, cs)

    # ------------------------------------------------------------------
    # Envelope
    # ------------------------------------------------------------------

    def _build_envelope(
        self, project_id: str, *, dag_mode: EnvelopeDagMode = "summary"
    ) -> Envelope:
        record = self.store.load_project(project_id)
        state = self.store.load_state(project_id) or Draft()
        tl: TaskList | None = None
        task_state: TaskStateFile | None = None
        mid = self._current_mission_id(record, state)
        if mid:
            try:
                tl = self.store.load_task_list(project_id, mid)
                task_state = self.store.load_task_state(project_id, mid)
            except FileNotFoundError:
                pass
        project_root = str(self.store.zenith_dir(project_id))
        harness_root = str(self.store.bucket_root(project_id))
        return make_envelope(
            project_id,
            state,
            project_root,
            harness_root,
            tl,
            task_state,
            dag_mode=dag_mode,
        )

    @staticmethod
    def _current_mission_id(record, state) -> str | None:
        if isinstance(state, (MissionPlanning, MissionRunning)):
            return state.mission_id
        return record.current_mission_id

    def _require_state(self, project_id: str) -> ProjectState:
        state = self.store.load_state(project_id)
        if state is None:
            raise ToolError("not_found", f"project {project_id!r} has no state")
        return state

    def _verify_task_binding_audit(self, project_id: str) -> None:
        """Block runtime execution when a one-shot claim is inconsistent."""
        record = self.store.load_project(project_id)
        state = self.store.load_state(project_id)
        mid = self._current_mission_id(record, state)
        if mid is None:
            return
        try:
            audit = self.store.load_task_binding_audit(project_id, mid)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(
                "invalid_task_binding_audit",
                "task binding audit is invalid",
            ) from exc
        if audit is None:
            return
        try:
            task_list = self.store.load_task_list(project_id, mid)
            current_digest = task_list_digest(task_list)
            task_state = self.store.load_task_state(project_id, mid)
            attempts = self.store.list_attempts(project_id, mid)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(
                "invalid_task_binding_audit",
                "task binding audit is invalid",
            ) from exc
        task_ids = {task.id for task in task_list.tasks}
        if attempts:
            return
        if set(task_state.tasks) != task_ids:
            raise ToolError(
                "invalid_task_state",
                "task state must contain exactly one entry per task",
            )
        if any(
            entry.status != "pending" or entry.last_attempt is not None
            for entry in task_state.tasks.values()
        ):
            raise ToolError(
                "invalid_task_state",
                "all task states must be pending with no last_attempt",
            )
        if current_digest != audit.after_task_list_sha256:
            raise ToolError(
                "task_binding_digest_mismatch",
                "task binding audit does not match current task list",
            )


def _make_pending():
    from .models import ContractStateEntry
    return ContractStateEntry()


__all__ = ["ProjectController", "ToolError"]
