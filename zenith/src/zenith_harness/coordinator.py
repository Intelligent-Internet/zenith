"""MissionCoordinator — the state-machine kernel.

See `specs/task_list/PRODUCT.md` §Dispatch. One `step()` call advances
the state by at most one transition. The controller's `advance_project`
tool loops `step()` until a returnable condition.
"""
from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from typing import Literal

from . import attention as attn_factory
from .dispatcher import (
    DispatchRequest,
    NodeDispatcher,
    NodeHandoff,
    TerminalReviewer,
)
from .models import (
    AttentionItemInternal,
    AttentionNeeded,
    Aborted,
    ContractStateEntry,
    Done,
    Draft,
    Failed,
    MissionPlanning,
    MissionRunning,
    Task,
    TaskList,
    TaskStateFile,
    TerminalReviewConfig,
    ValidateHandoff,
    WorkHandoff,
)
from .storage import ProjectStore, utc_now_filesafe
from .envelope import public_attention_items


# ---------------------------------------------------------------------------
# StepResult
# ---------------------------------------------------------------------------


StepKind = Literal["idle", "advanced", "attention_needed", "terminal"]


@dataclass(frozen=True)
class StepResult:
    kind: StepKind
    detail: str = ""

    @classmethod
    def idle(cls, detail: str = "") -> "StepResult":
        return cls("idle", detail)

    @classmethod
    def advanced(cls, detail: str = "") -> "StepResult":
        return cls("advanced", detail)

    @classmethod
    def attention_needed(cls, detail: str = "") -> "StepResult":
        return cls("attention_needed", detail)

    @classmethod
    def terminal(cls, detail: str = "") -> "StepResult":
        return cls("terminal", detail)


# ---------------------------------------------------------------------------
# MissionCoordinator
# ---------------------------------------------------------------------------


class MissionCoordinator:
    def __init__(
        self,
        store: ProjectStore,
        project_id: str,
        dispatcher: NodeDispatcher,
        terminal_reviewer: TerminalReviewer,
    ):
        self.store = store
        self.project_id = project_id
        self.dispatcher = dispatcher
        self.terminal_reviewer = terminal_reviewer

    # ------------------------------------------------------------------
    # The main step() kernel
    # ------------------------------------------------------------------

    def step(self) -> StepResult:
        state = self.store.load_state(self.project_id)
        if state is None or isinstance(state, Draft):
            return StepResult.idle()
        if isinstance(state, MissionPlanning):
            return StepResult.idle()
        if isinstance(state, AttentionNeeded):
            return StepResult.attention_needed()
        if isinstance(state, (Done, Failed, Aborted)):
            return StepResult.terminal()
        if isinstance(state, MissionRunning):
            return self._step_mission(state.mission_id)
        return StepResult.idle()

    # ------------------------------------------------------------------
    # Mission inner loop
    # ------------------------------------------------------------------

    def _step_mission(self, mid: str) -> StepResult:
        try:
            tl = self.store.load_task_list(self.project_id, mid)
        except FileNotFoundError:
            self.store.save_state(
                self.project_id, Failed(reason=f"tasks.json missing for {mid}")
            )
            return StepResult.terminal("task_list missing")
        task_state = self.store.load_task_state(self.project_id, mid)
        contract_state = self.store.load_contract_state(self.project_id, mid)
        if not contract_state.items:
            for assertion in self.store.list_contract_assertions(self.project_id, mid):
                contract_state.items.setdefault(assertion, ContractStateEntry())
            self.store.save_contract_state(self.project_id, mid, contract_state)

        resume_result = self._reconcile_pending_attempts(mid, tl, task_state)
        if resume_result is not None:
            return resume_result

        gate_event = self._try_evaluate_a_gate(tl, task_state)
        if gate_event is not None:
            return self._apply_gate_event(mid, tl, task_state, gate_event)

        runnable = self._all_runnable_tasks(tl, task_state)
        if not runnable:
            return StepResult.idle("no runnable task work; call end_mission to request closure")

        validator_batch = self._validator_batch_for_pending_gate(tl, task_state, runnable)
        if len(validator_batch) > 1:
            return self._dispatch_batch(mid, tl, task_state, validator_batch)
        if len(validator_batch) == 1:
            return self._dispatch_one(mid, validator_batch[0])

        max_parallel = self.store.config.max_parallel_nodes
        if max_parallel <= 1:
            return self._dispatch_one(mid, runnable[0])
        return self._dispatch_batch(mid, tl, task_state, runnable[:max_parallel])

    def _dispatch_one(self, mid: str, task: Task) -> StepResult:
        """Original serial dispatch path, retained for max_parallel=1."""
        spawn_ts = utc_now_filesafe()
        task_state = self.store.load_task_state(self.project_id, mid)
        task_state.set_status(task.id, "running")
        task_state.set_last_attempt(task.id, spawn_ts)
        self.store.save_task_state(self.project_id, mid, task_state)

        request = DispatchRequest(
            project_id=self.project_id,
            mission_id=mid,
            task=task,
            spawn_ts=spawn_ts,
        )
        try:
            handoff = self.dispatcher.dispatch(request)
        except Exception as exc:  # noqa: BLE001
            synthetic = self._synthesize_handoff(task, f"Dispatcher crashed: {exc}")
            self.store.save_attempt(
                self.project_id,
                mid,
                spawn_ts,
                task.id,
                synthetic,
            )
            return self._apply_handoff(mid, task, synthetic, spawn_ts)

        self.store.save_attempt(self.project_id, mid, spawn_ts, task.id, handoff)
        return self._apply_handoff(mid, task, handoff, spawn_ts)

    # ------------------------------------------------------------------
    # Runnable selection (the only graph-shape-coupled code)
    # ------------------------------------------------------------------

    def _next_runnable_task(
        self, tl: TaskList, task_state: TaskStateFile
    ) -> Task | None:
        pending = self._all_runnable_tasks(tl, task_state)
        if not pending:
            return None
        return pending[0]

    def _all_runnable_tasks(
        self, tl: TaskList, task_state: TaskStateFile
    ) -> list[Task]:
        """Runnable = non-gate, pending, all deps cleared.

        `supersede` and `cancel` patches rewrite downstream `depends_on`
        in-place at patch time, so the runtime never sees a dep pointing at
        a retired task. The check is plain `status == cleared`.

        List order is preserved as a topological tie-break per spec G4.
        """
        runnable: list[Task] = []
        for task in tl.tasks:
            if task.type == "gate":
                continue
            if task_state.status_of(task.id) != "pending":
                continue
            if all(
                task_state.status_of(dep) == "cleared" for dep in task.depends_on
            ):
                runnable.append(task)
        return runnable

    @staticmethod
    def _validator_batch_for_pending_gate(
        tl: TaskList,
        task_state: TaskStateFile,
        runnable: list[Task],
    ) -> list[Task]:
        """Prefer a complete ready validator lane before starting more work."""
        by_id = {task.id: task for task in tl.tasks}
        runnable_validators = {
            task.id
            for task in runnable
            if task.type == "validate"
        }
        for gate in (task for task in tl.tasks if task.type == "gate"):
            if task_state.status_of(gate.id) != "pending":
                continue
            validator_dep_ids = [
                dep_id
                for dep_id in gate.depends_on
                if by_id.get(dep_id) is not None and by_id[dep_id].type == "validate"
            ]
            if not validator_dep_ids:
                continue
            deps_ready = True
            for dep_id in gate.depends_on:
                dep = by_id.get(dep_id)
                if dep is not None and dep.type == "validate":
                    deps_ready = (
                        task_state.status_of(dep_id) == "cleared"
                        or dep_id in runnable_validators
                    )
                else:
                    deps_ready = task_state.status_of(dep_id) == "cleared"
                if not deps_ready:
                    break
            if not deps_ready:
                continue
            validator_dep_set = set(runnable_validators).intersection(validator_dep_ids)
            return [
                task
                for task in runnable
                if task.id in validator_dep_set
            ]
        return []

    def _dispatch_batch(
        self,
        mid: str,
        tl: TaskList,
        task_state: TaskStateFile,
        batch: list[Task],
    ) -> StepResult:
        batch_attempts: list[_BatchAttempt] = []
        for index, task in enumerate(batch):
            spawn_ts = self._batch_spawn_ts(index)
            task_state.set_status(task.id, "running")
            task_state.set_last_attempt(task.id, spawn_ts)
            batch_attempts.append(
                _BatchAttempt(task=task, spawn_ts=spawn_ts)
            )
        self.store.save_task_state(self.project_id, mid, task_state)

        requests = [
            DispatchRequest(
                project_id=self.project_id,
                mission_id=mid,
                task=attempt.task,
                spawn_ts=attempt.spawn_ts,
            )
            for attempt in batch_attempts
        ]
        handoffs = self._dispatch_requests(requests)

        attention: list[AttentionItemInternal] = []
        for attempt in sorted(batch_attempts, key=lambda item: item.task.id):
            handoff = handoffs[attempt.task.id]
            self.store.save_attempt(
                self.project_id,
                mid,
                attempt.spawn_ts,
                attempt.task.id,
                handoff,
            )
            attention.extend(
                self._apply_handoff_collect(mid, attempt.task, handoff, attempt.spawn_ts)
            )

        if attention:
            self._raise_attention(attention)
            return StepResult.attention_needed("batch_attention")
        return StepResult.advanced(
            "batch cleared: " + ", ".join(attempt.task.id for attempt in batch_attempts)
        )

    def _dispatch_requests(
        self,
        requests: list[DispatchRequest],
    ) -> dict[str, NodeHandoff]:
        if not requests:
            return {}

        batch_method = getattr(self.dispatcher, "dispatch_batch", None)
        if callable(batch_method):
            try:
                handoffs = batch_method(requests)
                if len(handoffs) != len(requests):
                    raise RuntimeError(
                        f"dispatch_batch returned {len(handoffs)} handoff(s) for "
                        f"{len(requests)} request(s)"
                    )
                return {
                    request.task.id: handoff
                    for request, handoff in zip(requests, handoffs, strict=True)
                }
            except Exception as exc:  # noqa: BLE001
                return {
                    request.task.id: self._synthesize_handoff(
                        request.task,
                        f"Dispatcher batch crashed: {exc}",
                    )
                    for request in requests
                }

        def _run(request: DispatchRequest) -> tuple[str, NodeHandoff]:
            try:
                return request.task.id, self.dispatcher.dispatch(request)
            except Exception as exc:  # noqa: BLE001
                return (
                    request.task.id,
                    self._synthesize_handoff(
                        request.task,
                        f"Dispatcher crashed: {exc}",
                    ),
                )

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(requests)) as pool:
            return dict(pool.map(_run, requests))

    @staticmethod
    def _batch_spawn_ts(index: int) -> str:
        return f"{utc_now_filesafe()}-{index:04d}"

    def _apply_handoff(
        self,
        mid: str,
        task: Task,
        handoff: NodeHandoff,
        spawn_ts: str,
    ) -> StepResult:
        attention = self._apply_handoff_collect(mid, task, handoff, spawn_ts)
        if attention:
            self._raise_attention(attention)
            return StepResult.attention_needed(attention[0].kind)
        return StepResult.advanced(f"{task.id} cleared")

    def _apply_handoff_collect(
        self,
        mid: str,
        task: Task,
        handoff: NodeHandoff,
        spawn_ts: str,
    ) -> list[AttentionItemInternal]:
        tl = self.store.load_task_list(self.project_id, mid)
        task_state = self.store.load_task_state(self.project_id, mid)
        contract_state = self.store.load_contract_state(self.project_id, mid)
        attention: list[AttentionItemInternal] = []

        if task.type == "work":
            if not handoff.done:
                task_state.set_status(task.id, "failed")
                self.store.save_task_state(self.project_id, mid, task_state)
                assert isinstance(handoff, WorkHandoff)
                return [attn_factory.node_failed(mid, task, handoff)]
            task_state.set_status(task.id, "cleared")
            self.store.save_task_state(self.project_id, mid, task_state)
        elif task.type == "validate":
            task_state.set_status(task.id, "cleared")
            self.store.save_task_state(self.project_id, mid, task_state)
            if isinstance(handoff, ValidateHandoff):
                for item in handoff.items:
                    entry = contract_state.items.setdefault(
                        item.item_id, ContractStateEntry()
                    )
                    if item.passed:
                        entry.status = "passed"
                    elif entry.status != "passed":
                        entry.status = "failed"
                self.store.save_contract_state(self.project_id, mid, contract_state)
                if self._validate_failure_needs_attention(tl, task_state, task, handoff):
                    attention.append(
                        attn_factory.node_attention(mid, task, handoff)
                    )

        if handoff.request_attention:
            attention.append(attn_factory.node_attention(mid, task, handoff))
        return attention

    def _synthesize_handoff(self, task: Task, report: str) -> NodeHandoff:
        if task.type == "validate":
            return ValidateHandoff(
                node_id=task.id,
                done=False,
                report=report,
                items=[],
                passed=False,
                request_attention=False,
            )
        return WorkHandoff(
            node_id=task.id,
            done=False,
            report=report,
            request_attention=False,
        )

    def close_mission(
        self, mid: str, *, deliverable_roots: list[str] | None = None
    ) -> StepResult:
        state = self.store.load_state(self.project_id)
        if not isinstance(state, MissionRunning):
            return StepResult.idle("close_mission requires mission_running")
        try:
            tl = self.store.load_task_list(self.project_id, mid)
        except FileNotFoundError:
            self.store.save_state(
                self.project_id, Failed(reason=f"tasks.json missing for {mid}")
            )
            return StepResult.terminal("task_list missing")

        task_state = self.store.load_task_state(self.project_id, mid)
        resume_result = self._reconcile_pending_attempts(mid, tl, task_state)
        if resume_result is not None:
            return resume_result

        gate_event = self._try_evaluate_a_gate(tl, task_state)
        if gate_event is not None:
            return StepResult.idle("mission has a ready gate; call advance_project first")

        task = self._next_runnable_task(tl, task_state)
        if task is not None:
            return StepResult.idle(
                f"mission has runnable task work ({task.id}); call advance_project first"
            )

        if deliverable_roots is not None:
            self.store.save_terminal_review_config(
                self.project_id,
                mid,
                TerminalReviewConfig(deliverable_roots=deliverable_roots),
            )
        return self._enter_terminal_review(mid)

    # ------------------------------------------------------------------
    # Gates
    # ------------------------------------------------------------------

    def _try_evaluate_a_gate(
        self, tl: TaskList, task_state: TaskStateFile
    ) -> "_GateEvent | None":
        for gate in sorted(
            (t for t in tl.tasks if t.type == "gate"), key=lambda t: t.id
        ):
            if task_state.status_of(gate.id) != "pending":
                continue
            if not all(
                task_state.status_of(dep) == "cleared" for dep in gate.depends_on
            ):
                continue
            return _GateEvent(gate=gate, result=self._evaluate_gate(tl, gate))
        return None

    def _evaluate_gate(self, tl: TaskList, gate: Task) -> "_GateResult":
        """AND-semantics gate evaluation.

        For each gate target, every covering validator must report
        passed=True. Any single dissent blocks the gate. A validator
        "covers" a target when the validator task was authored with that
        target in `task.targets`; missing expected items count as passed=False.
        """
        mid = self._lookup_mid_for_state()
        validate_preds = self._upstream_validators(tl, gate.id)
        by_id = {t.id: t for t in tl.tasks}

        validator_verdicts: dict[str, dict[str, bool]] = {}
        attempt_paths: dict[str, str] = {}
        missing_items: dict[str, list[str]] = {}
        for v_task_id in validate_preds:
            v_task = by_id.get(v_task_id)
            if v_task is None:
                continue
            expected = [t for t in v_task.targets if t in gate.targets]
            if not expected:
                continue

            attempts = self.store.list_attempts(
                self.project_id, mid, node_id=v_task_id
            )
            if not attempts:
                validator_verdicts[v_task_id] = {t: False for t in expected}
                missing_items[v_task_id] = list(expected)
                continue
            last = attempts[-1]
            handoff = self.store.read_attempt(
                self.project_id, mid, last.spawn_ts, v_task_id
            )
            attempt_paths[v_task_id] = str(
                self.store.attempt_report_path(
                    self.project_id, mid, last.spawn_ts, v_task_id
                )
            )
            if not isinstance(handoff, ValidateHandoff):
                validator_verdicts[v_task_id] = {t: False for t in expected}
                missing_items[v_task_id] = list(expected)
                continue

            verdicts: dict[str, bool] = {}
            returned_ids: set[str] = set()
            for item in handoff.items:
                if item.item_id in gate.targets:
                    verdicts[item.item_id] = bool(item.passed)
                returned_ids.add(item.item_id)
            missing = [t for t in expected if t not in returned_ids]
            for t in missing:
                verdicts[t] = False
            if missing:
                missing_items[v_task_id] = missing
            validator_verdicts[v_task_id] = verdicts

        item_passed: dict[str, bool] = {}
        uncovered: list[str] = []
        for tgt in gate.targets:
            covering = [
                vid for vid, verds in validator_verdicts.items()
                if tgt in verds
            ]
            if not covering:
                uncovered.append(tgt)
                continue
            item_passed[tgt] = all(
                validator_verdicts[vid][tgt] for vid in covering
            )

        if uncovered:
            return _GateResult(
                cleared=False,
                reason=(
                    f"no validator covered item(s): {', '.join(uncovered)}"
                ),
                failed_items=uncovered,
                validator_verdicts=validator_verdicts,
                attempt_paths=attempt_paths,
                missing_items=missing_items,
            )
        if all(item_passed.values()):
            return _GateResult(
                cleared=True,
                validator_verdicts=validator_verdicts,
                attempt_paths=attempt_paths,
                missing_items=missing_items,
            )
        failed = [k for k, v in item_passed.items() if not v]
        dissent_detail: list[str] = []
        for tgt in failed:
            dissenters = [
                vid for vid, verds in validator_verdicts.items()
                if verds.get(tgt) is False and tgt not in missing_items.get(vid, [])
            ]
            omitters = [
                vid for vid, miss in missing_items.items() if tgt in miss
            ]
            parts: list[str] = []
            if dissenters:
                parts.append(f"dissent: {', '.join(dissenters)}")
            if omitters:
                parts.append(f"missing: {', '.join(omitters)}")
            dissent_detail.append(f"{tgt} ({'; '.join(parts)})")
        return _GateResult(
            cleared=False,
            reason=f"failed items: {', '.join(dissent_detail)}",
            failed_items=failed,
            validator_verdicts=validator_verdicts,
            attempt_paths=attempt_paths,
            missing_items=missing_items,
        )

    def _upstream_validators(self, tl: TaskList, gate_id: str) -> list[str]:
        """Transitive predecessors of `gate_id` that are validate tasks.

        Patches rewrite `depends_on` in-place when they supersede/cancel,
        so the gate's reachable chain never includes retired validators —
        no status filtering needed here.
        """
        by_id = {t.id: t for t in tl.tasks}
        gate = by_id.get(gate_id)
        if gate is None:
            return []
        seen: set[str] = set()
        stack: list[str] = list(gate.depends_on)
        result: list[str] = []
        while stack:
            cur = stack.pop()
            if cur in seen or cur not in by_id:
                continue
            seen.add(cur)
            task = by_id[cur]
            if task.type == "validate":
                result.append(cur)
            stack.extend(task.depends_on)
        return result

    def _validate_failure_needs_attention(
        self,
        tl: TaskList,
        task_state: TaskStateFile,
        task: Task,
        handoff: ValidateHandoff,
    ) -> bool:
        """Surface failed validation when no pending downstream gate will do it."""
        returned: dict[str, bool] = {
            item.item_id: bool(item.passed)
            for item in handoff.items
            if item.item_id in task.targets
        }
        targets_needing_attention = [
            target
            for target in task.targets
            if returned.get(target) is not True
        ]
        if not targets_needing_attention and handoff.passed:
            return False
        if not targets_needing_attention and not handoff.passed:
            targets_needing_attention = list(task.targets)

        return any(
            not self._has_pending_downstream_gate_covering(
                tl, task_state, task.id, target
            )
            for target in targets_needing_attention
        )

    @staticmethod
    def _has_pending_downstream_gate_covering(
        tl: TaskList,
        task_state: TaskStateFile,
        task_id: str,
        target: str,
    ) -> bool:
        by_id = {t.id: t for t in tl.tasks}
        adj: dict[str, list[str]] = {t.id: [] for t in tl.tasks}
        for task in tl.tasks:
            for dep in task.depends_on:
                if dep in adj:
                    adj[dep].append(task.id)

        seen: set[str] = set()
        stack = list(adj.get(task_id, []))
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            cur_task = by_id.get(cur)
            if cur_task is None:
                continue
            if (
                cur_task.type == "gate"
                and target in cur_task.targets
                and task_state.status_of(cur_task.id) == "pending"
            ):
                return True
            stack.extend(adj.get(cur, []))
        return False

    def _apply_gate_event(
        self,
        mid: str,
        tl: TaskList,
        task_state: TaskStateFile,
        event: "_GateEvent",
    ) -> StepResult:
        if event.result.cleared:
            task_state.set_status(event.gate.id, "cleared")
            self.store.save_task_state(self.project_id, mid, task_state)
            self._raise_attention(
                [
                    attn_factory.gate_checkpoint(
                        mid,
                        event.gate,
                        validator_verdicts=event.result.validator_verdicts,
                    )
                ]
            )
            return StepResult.attention_needed("gate_checkpoint")
        else:
            task_state.set_status(event.gate.id, "failed")
            self.store.save_task_state(self.project_id, mid, task_state)
            self._raise_attention(
                [
                    attn_factory.gate_failed(
                        mid,
                        event.gate,
                        event.result.reason or "",
                        failed_items=event.result.failed_items or [],
                        validator_verdicts=event.result.validator_verdicts,
                        missing_items=event.result.missing_items,
                    )
                ]
            )
            return StepResult.attention_needed("gate_failed")

    # ------------------------------------------------------------------
    # Terminal review
    # ------------------------------------------------------------------

    def _enter_terminal_review(self, mid: str) -> StepResult:
        config = self.store.load_terminal_review_config(self.project_id, mid)
        # Revalidate persisted roots immediately before dispatch. This canonical
        # policy preflight is best-effort; reviewer access is not OS-sandboxed.
        resolved_roots = self.store.resolve_terminal_review_roots(
            self.project_id, mid, config.deliverable_roots
        )
        if resolved_roots != config.deliverable_roots:
            self.store.save_terminal_review_config(
                self.project_id,
                mid,
                TerminalReviewConfig(deliverable_roots=resolved_roots),
            )
        spawn_ts = utc_now_filesafe()
        try:
            report = self.terminal_reviewer.review(self.project_id, mid, spawn_ts)
        except Exception as exc:  # noqa: BLE001
            self.store.save_state(
                self.project_id,
                Failed(reason=f"Terminal reviewer crashed: {exc}"),
            )
            return StepResult.terminal("terminal_review_crash")
        self.store.save_terminal_review(self.project_id, mid, spawn_ts, report)
        if report.done:
            self.store.seal_mission(
                self.project_id,
                mid,
                status="done",
                body=report.report or "Mission complete; terminal review clean.",
            )
            self.store.save_state(self.project_id, Done())
            return StepResult.terminal("done")
        self._raise_attention([attn_factory.terminal_review(mid, report)])
        return StepResult.attention_needed("terminal_review")

    # ------------------------------------------------------------------
    # Attention queue
    # ------------------------------------------------------------------

    def _raise_attention(self, items: list[AttentionItemInternal]) -> None:
        existing = self.store.load_attention(self.project_id)
        existing.extend(items)
        self.store.save_attention(self.project_id, existing)
        self.store.save_state(
            self.project_id,
            AttentionNeeded(items=public_attention_items(existing)),
        )

    # ------------------------------------------------------------------
    # Resume from disk
    # ------------------------------------------------------------------

    def _reconcile_pending_attempts(
        self, mid: str, tl: TaskList, task_state: TaskStateFile
    ) -> StepResult | None:
        attention: list[AttentionItemInternal] = []
        saw_running = False
        for task in tl.tasks:
            if task_state.status_of(task.id) != "running":
                continue
            saw_running = True
            attempts = self.store.list_attempts(self.project_id, mid, node_id=task.id)
            if not attempts:
                entry = task_state.tasks.get(task.id)
                spawn_ts = entry.last_attempt if entry is not None else None
                if spawn_ts is None:
                    spawn_ts = utc_now_filesafe()
                handoff = self._synthesize_handoff(
                    task,
                    "Coordinator resumed with task marked running but no attempt file was present.",
                )
                self.store.save_attempt(
                    self.project_id,
                    mid,
                    spawn_ts,
                    task.id,
                    handoff,
                )
                attention.extend(
                    self._apply_handoff_collect(mid, task, handoff, spawn_ts)
                )
                continue
            last = attempts[-1]
            read_handoff = self.store.read_attempt(
                self.project_id, mid, last.spawn_ts, task.id
            )
            if read_handoff is None:
                continue
            attention.extend(
                self._apply_handoff_collect(mid, task, read_handoff, last.spawn_ts)
            )
        if not saw_running:
            return None
        if attention:
            self._raise_attention(attention)
            return StepResult.attention_needed("resume_attention")
        return StepResult.advanced("reconciled pending attempts")

    # ------------------------------------------------------------------
    # Mission id helper
    # ------------------------------------------------------------------

    def _lookup_mid_for_state(self) -> str:
        state = self.store.load_state(self.project_id)
        if isinstance(state, (MissionRunning, MissionPlanning)):
            return state.mission_id
        missions = self.store.list_missions(self.project_id)
        if not missions:
            raise RuntimeError("no mission in this project")
        return missions[-1]


# ---------------------------------------------------------------------------
# Internal records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _BatchAttempt:
    task: Task
    spawn_ts: str


@dataclass(frozen=True)
class _GateResult:
    cleared: bool
    reason: str | None = None
    failed_items: list[str] | None = None
    validator_verdicts: dict[str, dict[str, bool]] = field(default_factory=dict)
    attempt_paths: dict[str, str] = field(default_factory=dict)
    missing_items: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class _GateEvent:
    gate: Task
    result: _GateResult


__all__ = ["MissionCoordinator", "StepResult"]
