"""Terminal review wiring tests — drive a mission to drain + verify outcomes.

See docs/v5/10-implementation-plan.md §2 Phase 7.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from zenith_harness.config import HarnessConfig
from zenith_harness.controller import ProjectController
from zenith_harness.dispatcher import (
    DispatchRequest,
    MockDispatcher,
    MockTerminalReviewer,
    NodeHandoff,
)
from zenith_harness.models import (
    Decision,
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
        max_parallel_nodes=1,
    )


def _task(tid: str, ttype: str, targets: list[str], skill: str | None = None,
          depends_on: list[str] | None = None) -> Task:
    if skill is None and ttype != "gate":
        skill = (
            "scrutiny-validator"
            if ttype == "validate"
            else "engineering-mission-playbook"
        )
    return Task(
        id=tid,
        type=ttype,  # type: ignore[arg-type]
        body="" if ttype == "gate" else "b",
        targets=targets,
        skill=skill,
        depends_on=depends_on or [],
    )


def _simple_tl() -> TaskList:
    return TaskList(tasks=[
        _task("w1", "work", ["VAL-001"]),
        _task("v1", "validate", ["VAL-001"], depends_on=["w1"]),
        _task("g1", "gate", ["VAL-001"], depends_on=["v1"]),
    ])


def _start_and_seed_contract(
    controller: ProjectController, workspace: Path
) -> str:
    """Run start_project, then seed mission-001 contract VAL-001 inside the bucket."""
    controller.start_project("brief", str(workspace))
    pid = controller.store.list_projects()[0].id
    contract_dir = controller.store.ensure_contract_dir(pid, "mission-001")
    (contract_dir / "VAL-001.md").write_text("# VAL-001\n\nstatement\n")
    return pid


def _responder(req: DispatchRequest) -> NodeHandoff:
    if req.task.type == "work":
        return WorkHandoff(node_id=req.task.id, done=True, report="")
    return ValidateHandoff(
        node_id=req.task.id,
        done=True,
        report="",
        items=[ValidationItem(item_id="VAL-001", passed=True)],
        passed=True,
    )


class TestCleanReview:
    def test_clean_review_seals_done(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        controller = ProjectController(
            config,
            MockDispatcher(_responder),
            MockTerminalReviewer(TerminalReviewHandoff(done=True, report="all clear")),
        )
        pid = _start_and_seed_contract(controller, workspace)
        controller.submit_plan(pid, _simple_tl())
        # First advance: gate_checkpoint
        env = controller.advance_project(pid)
        items = controller.store.load_attention(pid)
        controller.decide_attention(
            pid, [Decision(item_id=items[0].id, action="continue")]
        )
        env = controller.advance_project(pid)
        assert env.state.state == "mission_running"
        env = controller.end_mission(pid)
        assert env.state.state == "done"
        # Closeout written
        closeout = controller.store.mission_dir(pid, "mission-001") / "closeout.md"
        assert closeout.exists()
        assert "status: done" in closeout.read_text()


class TestGapsTransition:
    def test_terminal_review_report_then_next_mission_seals(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        reviewer = MockTerminalReviewer(
            TerminalReviewHandoff(
                done=False,
                report=(
                    "Terminal review found a blocking gap.\n"
                    "- brief_reference: brief quote\n"
                    "- description: missing endpoint"
                ),
            )
        )
        controller = ProjectController(config, MockDispatcher(_responder), reviewer)
        pid = _start_and_seed_contract(controller, workspace)
        controller.submit_plan(pid, _simple_tl())
        env = controller.advance_project(pid)
        assert env.state.state == "attention_needed"
        items = controller.store.load_attention(pid)
        controller.decide_attention(
            pid, [Decision(item_id=items[0].id, action="continue")]
        )
        env = controller.advance_project(pid)
        assert env.state.state == "mission_running"
        controller.end_mission(pid)
        review_dir = controller.store.terminal_reviews_dir(pid, "mission-001")
        assert review_dir.exists() and any(review_dir.iterdir())
        # Resolve via next_mission
        items = controller.store.load_attention(pid)
        controller.decide_attention(
            pid, [Decision(item_id=items[0].id, action="next_mission")]
        )
        # mission-002 should be the new current mission
        record = ProjectStore(config).load_project(pid)
        assert record.current_mission_id == "mission-002"


class TestAbortRoundtripFromTerminalReview:
    def test_abort_via_decision(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        reviewer = MockTerminalReviewer(
            TerminalReviewHandoff(done=False, report="blocking gap: x\nbrief: y")
        )
        controller = ProjectController(config, MockDispatcher(_responder), reviewer)
        pid = _start_and_seed_contract(controller, workspace)
        controller.submit_plan(pid, _simple_tl())
        env = controller.advance_project(pid)
        assert env.state.state == "attention_needed"
        items = controller.store.load_attention(pid)
        controller.decide_attention(
            pid, [Decision(item_id=items[0].id, action="continue")]
        )
        env = controller.advance_project(pid)
        assert env.state.state == "mission_running"
        controller.end_mission(pid)
        items = controller.store.load_attention(pid)
        env = controller.decide_attention(
            pid,
            [
                Decision(
                    item_id=items[0].id,
                    action="abort",
                    justification="user decision",
                )
            ],
        )
        assert env.state.state == "aborted"
