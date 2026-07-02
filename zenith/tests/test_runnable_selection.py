"""Runnable-task selection.

See `specs/task_list/PRODUCT.md` §Dispatch and Goal G4 (list order = topo
tie-breaker hint).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from zenith_harness.config import HarnessConfig
from zenith_harness.controller import ProjectController
from zenith_harness.coordinator import MissionCoordinator
from zenith_harness.dispatcher import (
    DispatchRequest,
    MockDispatcher,
    MockTerminalReviewer,
    NodeHandoff,
)
from zenith_harness.models import (
    Task,
    TaskList,
    TerminalReviewHandoff,
    ValidateHandoff,
    ValidationItem,
    WorkHandoff,
)


def _task(
    tid: str,
    ttype: str,
    targets: list[str],
    skill: str | None = None,
    depends_on: list[str] | None = None,
) -> Task:
    if skill is None and ttype != "gate":
        skill = (
            "scrutiny-validator"
            if ttype == "validate"
            else "engineering-mission-playbook"
        )
    return Task(
        id=tid,
        type=ttype,  # type: ignore[arg-type]
        body="" if ttype == "gate" else "body",
        targets=targets,
        skill=skill,
        depends_on=depends_on or [],
    )


@pytest.fixture
def config(harness_home: Path) -> HarnessConfig:
    bundled = Path(__file__).resolve().parents[1] / "src" / "zenith_harness" / "bundled"
    return HarnessConfig(
        bundled_dir=bundled,
        harness_home=harness_home,
        projects_dir=harness_home / "projects",
        orchestrator_provider_name="claude",
        worker_provider_name="claude",
        worker_acp_command=None,
        validator_provider_name=None,
        validator_acp_command=None,
        terminal_reviewer_provider_name=None,
        terminal_reviewer_acp_command=None,
        max_parallel_nodes=1,
    )


def _coordinator(config: HarnessConfig) -> MissionCoordinator:
    from zenith_harness.storage import ProjectStore
    dispatcher = MockDispatcher(lambda r: WorkHandoff(node_id=r.task.id, done=True, report=""))
    reviewer = MockTerminalReviewer(TerminalReviewHandoff(done=True, report=""))
    return MissionCoordinator(ProjectStore(config), "p", dispatcher, reviewer)


class TestRunnableSelection:
    def test_list_order_tie_break(self, config: HarnessConfig) -> None:
        """Two work tasks share `depends_on: []`. List order = tie-break."""
        tl = TaskList(tasks=[
            _task("a", "work", ["X"]),
            _task("b", "work", ["Y"]),
        ])
        from zenith_harness.models import TaskStateFile
        ts = TaskStateFile()
        ts.set_status("a", "pending")
        ts.set_status("b", "pending")
        c = _coordinator(config)
        runnable = c._all_runnable_tasks(tl, ts)
        assert [t.id for t in runnable] == ["a", "b"]

    def test_list_order_reversed_respected(self, config: HarnessConfig) -> None:
        tl = TaskList(tasks=[
            _task("b", "work", ["Y"]),
            _task("a", "work", ["X"]),
        ])
        from zenith_harness.models import TaskStateFile
        ts = TaskStateFile()
        ts.set_status("a", "pending")
        ts.set_status("b", "pending")
        c = _coordinator(config)
        runnable = c._all_runnable_tasks(tl, ts)
        assert [t.id for t in runnable] == ["b", "a"]

    def test_gate_excluded_from_runnable(self, config: HarnessConfig) -> None:
        tl = TaskList(tasks=[
            _task("g1", "gate", ["X"]),
        ])
        from zenith_harness.models import TaskStateFile
        ts = TaskStateFile()
        ts.set_status("g1", "pending")
        c = _coordinator(config)
        assert c._all_runnable_tasks(tl, ts) == []

    def test_blocked_by_pending_dep(self, config: HarnessConfig) -> None:
        tl = TaskList(tasks=[
            _task("w1", "work", ["X"]),
            _task("w2", "work", ["Y"], depends_on=["w1"]),
        ])
        from zenith_harness.models import TaskStateFile
        ts = TaskStateFile()
        ts.set_status("w1", "pending")
        ts.set_status("w2", "pending")
        c = _coordinator(config)
        runnable = c._all_runnable_tasks(tl, ts)
        assert [t.id for t in runnable] == ["w1"]

    def test_unblocked_when_dep_cleared(self, config: HarnessConfig) -> None:
        tl = TaskList(tasks=[
            _task("w1", "work", ["X"]),
            _task("w2", "work", ["Y"], depends_on=["w1"]),
        ])
        from zenith_harness.models import TaskStateFile
        ts = TaskStateFile()
        ts.set_status("w1", "cleared")
        ts.set_status("w2", "pending")
        c = _coordinator(config)
        runnable = c._all_runnable_tasks(tl, ts)
        assert [t.id for t in runnable] == ["w2"]

    def test_dep_on_superseded_does_not_become_runnable(
        self, config: HarnessConfig
    ) -> None:
        """With rewrite-on-patch, a task that still points at a superseded
        id is a contract violation (apply_patch would have rewritten the
        reference). The runtime is allowed to leave it un-runnable — only
        a `cleared` dep counts as satisfied.
        """
        tl = TaskList(tasks=[
            _task("w1", "work", ["X"]),
            _task("w2", "work", ["Y"], depends_on=["w1"]),
        ])
        from zenith_harness.models import TaskStateFile
        ts = TaskStateFile()
        ts.set_status("w1", "superseded")
        ts.set_status("w2", "pending")
        c = _coordinator(config)
        runnable = c._all_runnable_tasks(tl, ts)
        assert runnable == []


class TestSerialDispatchPicksFirstByListOrder:
    def test_serial_prioritizes_ready_gate_validation_before_later_work(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        spawn_order: list[str] = []

        def responder(req: DispatchRequest) -> NodeHandoff:
            spawn_order.append(req.task.id)
            if req.task.type == "validate":
                return ValidateHandoff(
                    node_id=req.task.id,
                    done=True,
                    report="",
                    items=[ValidationItem(item_id=t, passed=True) for t in req.task.targets],
                    passed=True,
                )
            return WorkHandoff(node_id=req.task.id, done=True, report="ok")

        controller = ProjectController(
            config,
            MockDispatcher(responder),
            MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
        )
        controller.start_project("Brief.", str(workspace))
        pid = controller.store.list_projects()[0].id
        contract_dir = controller.store.ensure_contract_dir(pid, "mission-001")
        (contract_dir / "VAL-A.md").write_text("# VAL-A\n")
        (contract_dir / "VAL-B.md").write_text("# VAL-B\n")

        # `b` is runnable after `a` clears, but `va` can now seal the first
        # gate, so validation runs before dispatching later independent work.
        controller.submit_plan(pid, TaskList(tasks=[
            _task("a", "work", ["VAL-A"]),
            _task("b", "work", ["VAL-B"]),
            _task("va", "validate", ["VAL-A"], depends_on=["a"]),
            _task("vb", "validate", ["VAL-B"], depends_on=["b"]),
            _task("ga", "gate", ["VAL-A"], depends_on=["va"]),
            _task("gb", "gate", ["VAL-B"], depends_on=["vb"]),
        ]))
        controller.advance_project(pid)
        assert spawn_order == ["a", "va"]
