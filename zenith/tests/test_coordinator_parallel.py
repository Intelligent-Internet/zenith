"""Parallel coordinator behaviour (task-list shape)."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from zenith_harness.config import HarnessConfig
from zenith_harness.controller import ProjectController
from zenith_harness.dispatcher import DispatchRequest, MockDispatcher, MockTerminalReviewer
from zenith_harness.models import (
    MissionRunning,
    Task,
    TaskList,
    TerminalReviewHandoff,
    ValidateHandoff,
    ValidationItem,
    WorkHandoff,
)
from zenith_harness.storage import ProjectStore


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
    )


def _task(tid: str, target: str) -> Task:
    return Task(
        id=tid,
        type="work",
        body="b",
        targets=[target],
        skill="engineering-mission-playbook",
    )


def _write_contract(store: ProjectStore, pid: str, mission_id: str, assertion: str) -> None:
    d = store.ensure_contract_dir(pid, mission_id)
    (d / f"{assertion}.md").write_text(f"# {assertion}\n\nStatement body.\n")


def _parallel_config(config: HarnessConfig, n: int = 2) -> HarnessConfig:
    object.__setattr__(config, "max_parallel_nodes", n)
    return config


def test_max_parallel_one_uses_current_workspace(
    config: HarnessConfig,
    workspace: Path,
) -> None:
    seen_cwds: dict[str, str | None] = {}

    def responder(req: DispatchRequest) -> WorkHandoff:
        seen_cwds[req.task.id] = req.cwd
        (workspace / f"{req.task.id}.txt").write_text(f"{req.task.id}\n")
        return WorkHandoff(node_id=req.task.id, done=True, report="ok")

    serial_config = _parallel_config(config, n=1)
    controller = ProjectController(
        serial_config,
        MockDispatcher(responder),
        MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
    )
    controller.start_project("Brief.", str(workspace))
    pid = controller.store.list_projects()[0].id
    _write_contract(controller.store, pid, "mission-001", "VAL-A")
    _write_contract(controller.store, pid, "mission-001", "VAL-B")
    controller.submit_plan(pid, TaskList(tasks=[_task("a", "VAL-A"), _task("b", "VAL-B")]))

    controller.advance_project(pid, max_steps=1)
    controller.advance_project(pid, max_steps=1)

    assert seen_cwds == {"a": None, "b": None}
    assert (workspace / "a.txt").read_text() == "a\n"
    assert (workspace / "b.txt").read_text() == "b\n"


def test_auto_merge_false_still_uses_current_workspace(
    config: HarnessConfig,
    workspace: Path,
) -> None:
    seen_cwd: Path | None = None

    def responder(req: DispatchRequest) -> WorkHandoff:
        nonlocal seen_cwd
        seen_cwd = Path(req.cwd) if req.cwd is not None else workspace
        (workspace / "candidate.txt").write_text("candidate\n")
        return WorkHandoff(node_id=req.task.id, done=True, report="ok")

    serial_config = _parallel_config(config, n=1)
    controller = ProjectController(
        serial_config,
        MockDispatcher(responder),
        MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
    )
    controller.start_project("Brief.", str(workspace))
    pid = controller.store.list_projects()[0].id
    _write_contract(controller.store, pid, "mission-001", "EXP-A")
    controller.submit_plan(
        pid,
        TaskList(
            tasks=[
                Task(
                    id="exp-a",
                    type="work",
                    body="b",
                    targets=["EXP-A"],
                    skill="engineering-mission-playbook",
                    auto_merge=False,
                )
            ]
        ),
    )

    env = controller.advance_project(pid, max_steps=1)

    assert env.state.state == "mission_running"
    assert seen_cwd == workspace
    assert (workspace / "candidate.txt").read_text() == "candidate\n"
    assert controller.store.load_attention(pid) == []


def test_serial_mode_batches_ready_gate_validators_before_more_work(
    config: HarnessConfig,
    workspace: Path,
) -> None:
    starts: dict[str, float] = {}
    finishes: dict[str, float] = {}
    seen_cwds: dict[str, str | None] = {}
    lock = threading.Lock()

    def responder(req: DispatchRequest) -> WorkHandoff | ValidateHandoff:
        seen_cwds[req.task.id] = req.cwd
        if req.task.type == "work":
            return WorkHandoff(node_id=req.task.id, done=True, report="ok")

        with lock:
            starts[req.task.id] = time.monotonic()
        time.sleep(0.5)
        with lock:
            finishes[req.task.id] = time.monotonic()
        return ValidateHandoff(
            node_id=req.task.id,
            done=True,
            report="audited",
            items=[ValidationItem(item_id="VAL-A", passed=True)],
            passed=True,
        )

    serial_config = _parallel_config(config, n=1)
    controller = ProjectController(
        serial_config,
        MockDispatcher(responder),
        MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
    )
    controller.start_project("Brief.", str(workspace))
    pid = controller.store.list_projects()[0].id
    _write_contract(controller.store, pid, "mission-001", "VAL-A")
    controller.submit_plan(
        pid,
        TaskList(
            tasks=[
                _task("w1", "VAL-A"),
                Task(
                    id="w2",
                    type="work",
                    body="later work",
                    targets=[],
                    skill="engineering-mission-playbook",
                    depends_on=["w1"],
                ),
                Task(
                    id="v-scrutiny",
                    type="validate",
                    body="audit implementation",
                    targets=["VAL-A"],
                    skill="scrutiny-validator",
                    depends_on=["w1"],
                ),
                Task(
                    id="v-user-surface",
                    type="validate",
                    body="audit user surface",
                    targets=["VAL-A"],
                    skill="user-testing-validator",
                    depends_on=["w1"],
                ),
                Task(
                    id="g1",
                    type="gate",
                    body="",
                    targets=["VAL-A"],
                    skill=None,
                    depends_on=["v-scrutiny", "v-user-surface"],
                ),
            ]
        ),
    )
    controller.advance_project(pid, max_steps=1)

    started = time.monotonic()
    env = controller.advance_project(pid, max_steps=1)
    elapsed = time.monotonic() - started

    assert env.state.state == "mission_running"
    assert set(starts) == {"v-scrutiny", "v-user-surface"}
    assert max(starts.values()) < min(finishes.values())
    assert elapsed < 0.9
    assert seen_cwds == {
        "w1": None,
        "v-scrutiny": None,
        "v-user-surface": None,
    }


def test_serial_mode_prioritizes_remaining_gate_validator_before_more_work(
    config: HarnessConfig,
    workspace: Path,
) -> None:
    spawn_order: list[str] = []

    def responder(req: DispatchRequest) -> WorkHandoff | ValidateHandoff:
        spawn_order.append(req.task.id)
        if req.task.type == "work":
            return WorkHandoff(node_id=req.task.id, done=True, report="ok")
        return ValidateHandoff(
            node_id=req.task.id,
            done=True,
            report="audited",
            items=[ValidationItem(item_id="VAL-A", passed=True)],
            passed=True,
        )

    serial_config = _parallel_config(config, n=1)
    controller = ProjectController(
        serial_config,
        MockDispatcher(responder),
        MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
    )
    controller.start_project("Brief.", str(workspace))
    pid = controller.store.list_projects()[0].id
    _write_contract(controller.store, pid, "mission-001", "VAL-A")
    controller.submit_plan(
        pid,
        TaskList(
            tasks=[
                _task("w1", "VAL-A"),
                Task(
                    id="w2",
                    type="work",
                    body="later work",
                    targets=[],
                    skill="engineering-mission-playbook",
                    depends_on=["w1"],
                ),
                Task(
                    id="v-cleared",
                    type="validate",
                    body="already audited",
                    targets=["VAL-A"],
                    skill="scrutiny-validator",
                    depends_on=["w1"],
                ),
                Task(
                    id="v-ready",
                    type="validate",
                    body="remaining audit",
                    targets=["VAL-A"],
                    skill="user-testing-validator",
                    depends_on=["w1"],
                ),
                Task(
                    id="g1",
                    type="gate",
                    body="",
                    targets=["VAL-A"],
                    skill=None,
                    depends_on=["v-cleared", "v-ready"],
                ),
            ]
        ),
    )
    controller.advance_project(pid, max_steps=1)
    task_state = controller.store.load_task_state(pid, "mission-001")
    task_state.set_status("v-cleared", "cleared")
    controller.store.save_task_state(pid, "mission-001", task_state)

    controller.advance_project(pid, max_steps=1)

    assert spawn_order == ["w1", "v-ready"]


def test_parallel_fanout_dispatches_concurrently(
    config: HarnessConfig,
    workspace: Path,
) -> None:
    starts: dict[str, float] = {}
    finishes: dict[str, float] = {}
    lock = threading.Lock()

    def responder(req: DispatchRequest) -> WorkHandoff:
        with lock:
            starts[req.task.id] = time.monotonic()
        time.sleep(0.5)
        with lock:
            finishes[req.task.id] = time.monotonic()
        return WorkHandoff(node_id=req.task.id, done=True, report="ok")

    controller = ProjectController(
        _parallel_config(config),
        MockDispatcher(responder),
        MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
    )
    controller.start_project("Brief.", str(workspace))
    pid = controller.store.list_projects()[0].id
    _write_contract(controller.store, pid, "mission-001", "VAL-A")
    _write_contract(controller.store, pid, "mission-001", "VAL-B")
    controller.submit_plan(pid, TaskList(tasks=[_task("a", "VAL-A"), _task("b", "VAL-B")]))

    started = time.monotonic()
    env = controller.advance_project(pid, max_steps=1)
    elapsed = time.monotonic() - started

    assert env.state.state == "mission_running"
    assert elapsed < 0.9
    assert set(starts) == {"a", "b"}
    assert starts["b"] < finishes["a"]


def test_parallel_work_tasks_run_in_current_workspace(
    config: HarnessConfig,
    workspace: Path,
) -> None:
    seen_cwds: dict[str, Path] = {}

    def responder(req: DispatchRequest) -> WorkHandoff:
        cwd = Path(req.cwd) if req.cwd is not None else workspace
        seen_cwds[req.task.id] = cwd
        assert cwd == workspace
        (workspace / f"{req.task.id}.txt").write_text(f"{req.task.id}\n")
        return WorkHandoff(node_id=req.task.id, done=True, report="ok")

    parallel_config = _parallel_config(config)
    controller = ProjectController(
        parallel_config,
        MockDispatcher(responder),
        MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
    )
    controller.start_project("Brief.", str(workspace))
    pid = controller.store.list_projects()[0].id
    _write_contract(controller.store, pid, "mission-001", "VAL-A")
    _write_contract(controller.store, pid, "mission-001", "VAL-B")
    controller.submit_plan(pid, TaskList(tasks=[_task("a", "VAL-A"), _task("b", "VAL-B")]))

    controller.advance_project(pid, max_steps=1)

    assert (workspace / "a.txt").read_text() == "a\n"
    assert (workspace / "b.txt").read_text() == "b\n"
    assert seen_cwds == {"a": workspace, "b": workspace}


def test_parallel_non_git_workspace_runs_in_workspace(
    config: HarnessConfig,
    workspace: Path,
) -> None:
    parallel_config = _parallel_config(config)
    controller = ProjectController(
        parallel_config,
        MockDispatcher(lambda r: WorkHandoff(node_id=r.task.id, done=True, report="")),
        MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
    )
    controller.start_project("Brief.", str(workspace))
    pid = controller.store.list_projects()[0].id
    _write_contract(controller.store, pid, "mission-001", "VAL-A")
    controller.submit_plan(pid, TaskList(tasks=[_task("a", "VAL-A")]))

    env = controller.advance_project(pid)

    assert env.state.state == "mission_running"


def test_reconcile_applies_multiple_running_attempts(
    config: HarnessConfig,
    workspace: Path,
) -> None:
    controller = ProjectController(
        config,
        MockDispatcher(lambda r: WorkHandoff(node_id=r.task.id, done=True, report="unused")),
        MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
    )
    controller.start_project("Brief.", str(workspace))
    pid = controller.store.list_projects()[0].id
    _write_contract(controller.store, pid, "mission-001", "VAL-A")
    _write_contract(controller.store, pid, "mission-001", "VAL-B")
    tl = TaskList(tasks=[_task("a", "VAL-A"), _task("b", "VAL-B")])
    controller.submit_plan(pid, tl)

    task_state = controller.store.load_task_state(pid, "mission-001")
    for tid, spawn_ts in {"a": "2026-01-01T00-00-00Z-a", "b": "2026-01-01T00-00-00Z-b"}.items():
        task_state.set_status(tid, "running")
        task_state.set_last_attempt(tid, spawn_ts)
        controller.store.save_attempt(
            pid, "mission-001", spawn_ts, tid,
            WorkHandoff(node_id=tid, done=True, report="ok"),
        )
    controller.store.save_task_state(pid, "mission-001", task_state)
    controller.store.save_state(pid, MissionRunning(mission_id="mission-001"))

    controller.advance_project(pid, max_steps=1)
    task_state = controller.store.load_task_state(pid, "mission-001")

    assert task_state.status_of("a") == "cleared"
    assert task_state.status_of("b") == "cleared"
