"""Terminal review wiring tests — drive a mission to drain + verify outcomes.

See docs/v5/10-implementation-plan.md §2 Phase 7.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from zenith_harness.acp_runner import ACPNodeRunner
from zenith_harness.assets import AssetLoader
from zenith_harness.config import HarnessConfig
from zenith_harness.controller import ProjectController, ToolError
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
    TerminalReviewConfig,
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
        skill = "s"
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
        _task("v1", "validate", ["VAL-001"], skill="aud", depends_on=["w1"]),
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


def _advance_to_closure(controller: ProjectController, pid: str) -> None:
    controller.submit_plan(pid, _simple_tl())
    env = controller.advance_project(pid)
    assert env.state.state == "attention_needed"
    items = controller.store.load_attention(pid)
    controller.decide_attention(
        pid, [Decision(item_id=items[0].id, action="continue")]
    )
    env = controller.advance_project(pid)
    assert env.state.state == "mission_running"


def _resume_after_terminal_gap(controller: ProjectController, pid: str) -> None:
    items = controller.store.load_attention(pid)
    assert len(items) == 1
    assert items[0].kind == "terminal_review"
    env = controller.decide_attention(
        pid, [Decision(item_id=items[0].id, action="continue")]
    )
    assert env.state.state == "mission_running"


@dataclass(frozen=True)
class _ReviewerInput:
    deliverable_roots: list[str]
    prompt: str
    contents_read: dict[str, str]


class _ScriptedRecordingReviewer:
    """Render the real reviewer prompt and read only its declared file roots."""

    def __init__(
        self,
        config: HarnessConfig,
        *,
        expected_report: Path | None = None,
        expected_content: str = "",
        succeed_when_visible: bool = True,
    ) -> None:
        self.store = ProjectStore(config)
        self.runner = ACPNodeRunner(config, AssetLoader(config))
        self.expected_report = expected_report
        self.expected_content = expected_content
        self.succeed_when_visible = succeed_when_visible
        self.inputs: list[_ReviewerInput] = []

    def review(
        self, project_id: str, mission_id: str, spawn_ts: str
    ) -> TerminalReviewHandoff:
        del spawn_ts
        roots = self.store.load_terminal_review_config(
            project_id, mission_id
        ).deliverable_roots
        prompt = self.runner._render_terminal_reviewer_prompts(
            project_bucket=str(self.store.zenith_dir(project_id)),
            workspace_dir=str(self.store.workspace_dir(project_id)),
            deliverable_roots=roots,
        )
        contents = {
            root: Path(root).read_text(encoding="utf-8")
            for root in roots
            if Path(root).is_file()
        }
        self.inputs.append(
            _ReviewerInput(
                deliverable_roots=list(roots),
                prompt=prompt,
                contents_read=contents,
            )
        )
        expected_root = (
            str(self.expected_report.resolve())
            if self.expected_report is not None
            else None
        )
        visible = (
            expected_root is not None
            and contents.get(expected_root) == self.expected_content
        )
        if visible and self.succeed_when_visible:
            return TerminalReviewHandoff(
                done=True, report="Declared final report content verified."
            )
        return TerminalReviewHandoff(
            done=False,
            report="GAP-ARTIFACT-NOT-VISIBLE: final report is not authorized.",
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
        report = controller.store.mission_dir(pid, "mission-001") / "evidence" / "report.md"
        report.parent.mkdir(parents=True)
        report.write_text("final report")
        env = controller.end_mission(pid, [str(report)])
        assert env.state.state == "done"
        review_config = controller.store.load_terminal_review_config(
            pid, "mission-001"
        )
        assert review_config.deliverable_roots == [str(report.resolve())]
        # Closeout written
        closeout = controller.store.mission_dir(pid, "mission-001") / "closeout.md"
        assert closeout.exists()
        assert "status: done" in closeout.read_text()


class TestDeclaredRootClosure:
    def test_report_is_invisible_without_root_then_visible_with_exact_root(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        report_content = "release-status: complete\n"
        reviewer = _ScriptedRecordingReviewer(
            config,
            expected_content=report_content,
        )
        controller = ProjectController(config, MockDispatcher(_responder), reviewer)
        pid = _start_and_seed_contract(controller, workspace)
        _advance_to_closure(controller, pid)

        report = (
            controller.store.mission_dir(pid, "mission-001")
            / "evidence"
            / "final"
            / "report.md"
        )
        report.parent.mkdir(parents=True)
        report.write_text(report_content, encoding="utf-8")
        reviewer.expected_report = report

        mission = controller.store.mission_dir(pid, "mission-001")
        process_history = {
            mission / "mission.md": "mission-charter-sentinel",
            mission / "contract" / "VAL-001.md": "contract-sentinel",
            mission / "attempts" / "prior-worker.md": "worker-report-sentinel",
            mission / "regressions" / "VAL-001.md": "validator-report-sentinel",
            mission / "terminal-reviews" / "prior.md": "prior-review-sentinel",
            mission / "closeout.md": "closeout-history-sentinel",
            controller.store.zenith_dir(pid) / "decisions" / "prior.md": (
                "decision-sentinel"
            ),
            controller.store.zenith_dir(pid) / "MEMORY.md": "mission-memory-sentinel",
            controller.store.zenith_dir(pid) / "AGENTS.md": (
                "agent-guidance-sentinel"
            ),
            controller.store.mission_runtime_dir(pid, "mission-001")
            / "private-cursor.json": "runtime-cursor-sentinel",
            controller.store.zenith_dir(pid)
            / "skills"
            / "private-provider"
            / "SKILL.md": "provider-control-sentinel",
        }
        for path, content in process_history.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        env = controller.end_mission(pid)
        assert env.state.state == "attention_needed"
        assert reviewer.inputs[0].deliverable_roots == []
        assert reviewer.inputs[0].contents_read == {}
        state = controller.store.load_state(pid)
        assert state is not None
        assert state.state != "done"

        _resume_after_terminal_gap(controller, pid)
        env = controller.end_mission(pid, [str(report)])
        assert env.state.state == "done"

        canonical_report = str(report.resolve())
        declared_input = reviewer.inputs[1]
        assert declared_input.deliverable_roots == [canonical_report]
        assert declared_input.contents_read == {canonical_report: report_content}
        assert canonical_report in declared_input.prompt
        persisted = controller.store.load_terminal_review_config(pid, "mission-001")
        assert persisted.deliverable_roots == [canonical_report]
        state = controller.store.load_state(pid)
        assert state is not None
        assert state.state == "done"

        for reviewer_input in reviewer.inputs:
            for path, sentinel in process_history.items():
                assert str(path.resolve()) not in reviewer_input.prompt
                assert sentinel not in reviewer_input.prompt

    def test_aliased_allowed_bases_are_canonicalized_on_retry(
        self, config: HarnessConfig, tmp_path: Path
    ) -> None:
        physical_root = tmp_path / "physical"
        physical_root.mkdir()
        aliased_root = tmp_path / "aliased"
        aliased_root.symlink_to(physical_root, target_is_directory=True)
        harness_home = aliased_root / "harness-home"
        aliased_config = replace(
            config,
            harness_home=harness_home,
            projects_dir=harness_home / "projects",
        )
        workspace = aliased_root / "workspace"
        workspace.mkdir()
        report_content = "release-status: complete\n"
        reviewer = _ScriptedRecordingReviewer(
            aliased_config,
            expected_content=report_content,
        )
        controller = ProjectController(
            aliased_config, MockDispatcher(_responder), reviewer
        )
        pid = _start_and_seed_contract(controller, workspace)
        _advance_to_closure(controller, pid)

        report = (
            controller.store.mission_dir(pid, "mission-001")
            / "evidence"
            / "final"
            / "report.md"
        )
        report.parent.mkdir(parents=True)
        report.write_text(report_content, encoding="utf-8")
        reviewer.expected_report = report
        product = workspace / "product.md"
        product.write_text("product", encoding="utf-8")

        first = controller.end_mission(pid, None)
        assert first.state.state == "attention_needed"
        assert reviewer.inputs[0].deliverable_roots == []
        _resume_after_terminal_gap(controller, pid)

        second = controller.end_mission(pid, [str(product), str(report)])
        expected_roots = sorted([str(product.resolve()), str(report.resolve())])
        assert second.state.state == "done"
        assert reviewer.inputs[1].deliverable_roots == expected_roots
        assert reviewer.inputs[1].contents_read == {
            str(product.resolve()): "product",
            str(report.resolve()): report_content,
        }
        assert controller.store.load_terminal_review_config(
            pid, "mission-001"
        ).deliverable_roots == expected_roots

    def test_none_clear_and_replace_persist_across_failed_review_retries(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        reviewer = _ScriptedRecordingReviewer(
            config, succeed_when_visible=False
        )
        controller = ProjectController(config, MockDispatcher(_responder), reviewer)
        pid = _start_and_seed_contract(controller, workspace)
        _advance_to_closure(controller, pid)

        evidence = controller.store.mission_dir(pid, "mission-001") / "evidence"
        report_a = evidence / "a.md"
        report_b = evidence / "b.md"
        evidence.mkdir(parents=True)
        report_a.write_text("a", encoding="utf-8")
        report_b.write_text("b", encoding="utf-8")
        config_path = controller.store.terminal_review_config_path(
            pid, "mission-001"
        )

        controller.end_mission(pid, None)
        assert reviewer.inputs[-1].deliverable_roots == []
        assert not config_path.exists()

        _resume_after_terminal_gap(controller, pid)
        controller.end_mission(
            pid, [str(report_b), str(report_a), str(report_b)]
        )
        replaced = sorted([str(report_a.resolve()), str(report_b.resolve())])
        assert reviewer.inputs[-1].deliverable_roots == replaced
        assert controller.store.load_terminal_review_config(
            pid, "mission-001"
        ).deliverable_roots == replaced

        _resume_after_terminal_gap(controller, pid)
        controller.end_mission(pid, None)
        assert reviewer.inputs[-1].deliverable_roots == replaced

        _resume_after_terminal_gap(controller, pid)
        controller.end_mission(pid, [])
        assert reviewer.inputs[-1].deliverable_roots == []
        assert controller.store.load_terminal_review_config(
            pid, "mission-001"
        ).deliverable_roots == []

        _resume_after_terminal_gap(controller, pid)
        controller.end_mission(pid, None)
        assert reviewer.inputs[-1].deliverable_roots == []

    def test_invalid_new_roots_block_reviewer_dispatch(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        reviewer = _ScriptedRecordingReviewer(config)
        controller = ProjectController(config, MockDispatcher(_responder), reviewer)
        pid = _start_and_seed_contract(controller, workspace)
        _advance_to_closure(controller, pid)

        mission = controller.store.mission_dir(pid, "mission-001")
        evidence = mission / "evidence"
        escaping = evidence / "escaping"
        broken = evidence / "broken"
        escaping.mkdir(parents=True)
        broken.mkdir(parents=True)
        (escaping / "contract-link").symlink_to(mission / "contract")
        (broken / "missing-link").symlink_to(evidence / "does-not-exist")
        product = workspace / "product.md"
        product.write_text("product", encoding="utf-8")
        direct_escape = evidence / "direct-escape"
        direct_escape.symlink_to(product)
        control_path = evidence / "bad\nname.md"
        control_path.write_text("bad", encoding="utf-8")
        mission_md = mission / "mission.md"
        mission_md.write_text("mission", encoding="utf-8")
        workspace_git = workspace / ".git"
        workspace_git.mkdir()

        invalid_roots = [
            evidence / "missing.md",
            control_path,
            escaping,
            broken,
            direct_escape,
            mission_md,
            mission,
            workspace_git,
            workspace,
        ]
        for invalid_root in invalid_roots:
            with pytest.raises(ToolError) as exc_info:
                controller.end_mission(pid, [str(invalid_root)])
            assert exc_info.value.code == "invalid_deliverable_roots"
        assert reviewer.inputs == []

    def test_invalid_persisted_root_blocks_coordinator_dispatch(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        reviewer = _ScriptedRecordingReviewer(config)
        controller = ProjectController(config, MockDispatcher(_responder), reviewer)
        pid = _start_and_seed_contract(controller, workspace)
        _advance_to_closure(controller, pid)

        report = (
            controller.store.mission_dir(pid, "mission-001")
            / "evidence"
            / "report.md"
        )
        report.parent.mkdir(parents=True)
        report.write_text("report", encoding="utf-8")
        resolved = controller.store.resolve_terminal_review_roots(
            pid, "mission-001", [str(report)]
        )
        controller.store.save_terminal_review_config(
            pid,
            "mission-001",
            TerminalReviewConfig(deliverable_roots=resolved),
        )
        report.unlink()

        with pytest.raises(ToolError) as exc_info:
            controller.end_mission(pid, None)
        assert exc_info.value.code == "invalid_deliverable_roots"
        assert reviewer.inputs == []


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
