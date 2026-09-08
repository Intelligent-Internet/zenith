"""Bounded dispatch wait — advance_project must never hold the orchestrator
call for a whole worker run.

The ACP dispatcher blocks on the worker's entire session; an orchestrator MCP
call held that long gets aborted by clients (Prime Agent: "Request was
aborted"). The bounded wait + .dispatched markers make advance return
in_progress while workers run, and reconcile applies their handoff files when
they land.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from zenith_harness.config import HarnessConfig
from zenith_harness.controller import ProjectController
from zenith_harness.dispatcher import DispatchRequest, MockDispatcher, MockTerminalReviewer
from zenith_harness.models import (
    AttentionNeeded,
    Task,
    TaskList,
    TerminalReviewHandoff,
    WorkHandoff,
)
from zenith_harness.storage import ProjectStore


@pytest.fixture
def config(harness_home: Path) -> HarnessConfig:
    bundled = Path(__file__).resolve().parents[1] / "src" / "zenith_harness" / "bundled"
    cfg = HarnessConfig(
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
    object.__setattr__(cfg, "dispatch_wait_s", 0.2)
    return cfg


def _task(tid: str, target: str) -> Task:
    return Task(id=tid, type="work", body="b", targets=[target], skill="s")


def _write_contract(store: ProjectStore, pid: str, mission_id: str, assertion: str) -> None:
    d = store.ensure_contract_dir(pid, mission_id)
    (d / f"{assertion}.md").write_text(f"# {assertion}\n\nStatement body.\n")


def _started_controller(config, workspace, responder):
    controller = ProjectController(
        config,
        MockDispatcher(responder),
        MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
    )
    controller.start_project("Brief.", str(workspace))
    pid = controller.store.list_projects()[0].id
    _write_contract(controller.store, pid, "mission-001", "VAL-A")
    controller.submit_plan(pid, TaskList(tasks=[_task("a", "VAL-A")]))
    return controller, pid


def test_advance_returns_promptly_while_worker_runs(config, workspace) -> None:
    """A slow worker must not hold advance_project: returns fast, task running."""
    release = []

    def slow(req: DispatchRequest) -> WorkHandoff:
        release.append(req.task.id)
        time.sleep(5)  # far beyond dispatch_wait_s=0.2
        return WorkHandoff(node_id=req.task.id, done=True, report="late")

    controller, pid = _started_controller(config, workspace, slow)
    t0 = time.monotonic()
    env = controller.advance_project(pid)
    elapsed = time.monotonic() - t0
    assert elapsed < 3.0, f"advance held the call for {elapsed:.1f}s"
    assert env.state.state == "mission_running"
    ts = controller.store.load_task_state(pid, "mission-001")
    assert ts.status_of("a") == "running"
    # in-flight marker present (worker still writing its handoff)
    spawn_ts = ts.tasks["a"].last_attempt
    marker = controller.store.attempts_runtime_dir(pid, "mission-001") / f"{spawn_ts}__a.dispatched"
    assert marker.exists()


def test_reconcile_reports_in_progress_then_applies_late_handoff(config, workspace) -> None:
    """Second advance while the worker runs: in_progress, no fake failure.
    After the handoff file lands: applied, task cleared."""
    held: list[DispatchRequest] = []

    def slow(req: DispatchRequest) -> WorkHandoff:
        held.append(req)
        time.sleep(5)
        return WorkHandoff(node_id=req.task.id, done=True, report="late")

    controller, pid = _started_controller(config, workspace, slow)
    controller.advance_project(pid)

    # Worker still in flight: reconcile must NOT synthesize a failure.
    env = controller.advance_project(pid)
    assert env.state.state == "mission_running"  # not attention_needed
    ts = controller.store.load_task_state(pid, "mission-001")
    assert ts.status_of("a") == "running"

    # Worker finishes: its handoff file lands (what the worker MCP server writes).
    spawn_ts = ts.tasks["a"].last_attempt
    controller.store.save_attempt(
        pid, "mission-001", spawn_ts, "a", WorkHandoff(node_id="a", done=True, report="done")
    )
    env = controller.advance_project(pid)
    ts = controller.store.load_task_state(pid, "mission-001")
    assert ts.status_of("a") == "cleared"
    # marker cleared on application
    marker = controller.store.attempts_runtime_dir(pid, "mission-001") / f"{spawn_ts}__a.dispatched"
    assert not marker.exists()


def test_lost_attempt_without_marker_still_synthesizes_failure(config, workspace) -> None:
    """Legacy crash-recovery: running + no marker + no attempt = attention."""
    def instant(req: DispatchRequest) -> WorkHandoff:
        return WorkHandoff(node_id=req.task.id, done=True, report="ok")

    controller, pid = _started_controller(config, workspace, instant)
    # Simulate a pre-fix/crashed dispatch: running, last_attempt set, no marker.
    ts = controller.store.load_task_state(pid, "mission-001")
    ts.set_status("a", "running")
    ts.set_last_attempt("a", "2000-01-01T00-00-00Z-0000")
    controller.store.save_task_state(pid, "mission-001", ts)

    env = controller.advance_project(pid)
    assert env.state.state == "attention_needed"


def test_stale_marker_counts_as_lost(config, workspace) -> None:
    """A marker older than attempt_stale_s with no handoff = lost attempt."""
    object.__setattr__(config, "attempt_stale_s", 0.05)

    def instant(req: DispatchRequest) -> WorkHandoff:
        return WorkHandoff(node_id=req.task.id, done=True, report="ok")

    controller, pid = _started_controller(config, workspace, instant)
    ts = controller.store.load_task_state(pid, "mission-001")
    ts.set_status("a", "running")
    spawn_ts = "2000-01-01T00-00-00Z-0000"
    ts.set_last_attempt("a", spawn_ts)
    controller.store.save_task_state(pid, "mission-001", ts)
    d = controller.store.attempts_runtime_dir(pid, "mission-001")
    d.mkdir(parents=True, exist_ok=True)
    marker = d / f"{spawn_ts}__a.dispatched"
    marker.write_text("{}")
    old = time.time() - 3600
    os.utime(marker, (old, old))

    env = controller.advance_project(pid)
    assert env.state.state == "attention_needed"
