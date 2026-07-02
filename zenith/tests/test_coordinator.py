"""Coordinator state-machine tests with the in-process mock dispatcher.

See `specs/task_list/PRODUCT.md` §Dispatch.
"""
from __future__ import annotations

from pathlib import Path

import pytest

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
    MissionRunning,
    Task,
    TaskList,
    TaskListPatch,
    TerminalReviewHandoff,
    ValidateHandoff,
    ValidationItem,
    WorkHandoff,
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


def _task(
    tid: str,
    ttype: str,
    targets: list[str],
    skill: str | None = None,
    depends_on: list[str] | None = None,
    body: str = "body",
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
        body="" if ttype == "gate" else body,
        targets=targets,
        skill=skill,
        depends_on=depends_on or [],
    )


def _simple_tl() -> TaskList:
    return TaskList(
        tasks=[
            _task("w1", "work", ["VAL-001"]),
            _task("v1", "validate", ["VAL-001"], depends_on=["w1"]),
            _task("g1", "gate", ["VAL-001"], depends_on=["v1"]),
        ]
    )


def _validate_no_gate_tl() -> TaskList:
    return TaskList(
        tasks=[
            _task("w1", "work", ["VAL-001"]),
            _task("v1", "validate", ["VAL-001"], depends_on=["w1"]),
        ]
    )


def _seed_project(
    controller: ProjectController,
    workspace: Path,
    *,
    brief: str = "Brief.",
    mission_id: str = "mission-001",
    assertion: str = "VAL-001",
) -> str:
    controller.start_project(brief, str(workspace))
    pid = controller.store.list_projects()[0].id
    contract_dir = controller.store.ensure_contract_dir(pid, mission_id)
    (contract_dir / f"{assertion}.md").write_text(
        f"# {assertion}\n\nStatement body.\n"
    )
    return pid


class TestHappyPath:
    def test_full_pipeline_to_done(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        def responder(req: DispatchRequest) -> NodeHandoff:
            if req.task.type == "work":
                return WorkHandoff(node_id=req.task.id, done=True, report="ok")
            return ValidateHandoff(
                node_id=req.task.id,
                done=True,
                report="audited",
                items=[ValidationItem(item_id="VAL-001", passed=True)],
                passed=True,
            )

        dispatcher = MockDispatcher(responder)
        reviewer = MockTerminalReviewer(TerminalReviewHandoff(done=True, report=""))
        controller = ProjectController(config, dispatcher, reviewer)

        pid = _seed_project(controller, workspace)
        controller.submit_plan(pid, _simple_tl())

        env = controller.advance_project(pid)
        assert env.state.state == "attention_needed"
        items = controller.store.load_attention(pid)
        assert items and items[0].kind == "gate_checkpoint"
        assert items[0].report.startswith("Gate checkpoint from g1")
        assert "passing gate already cleared" in items[0].report
        assert (
            controller.store.load_task_state(pid, "mission-001").status_of("g1")
            == "cleared"
        )

        env = controller.decide_attention(
            pid, [Decision(item_id=items[0].id, action="continue")]
        )
        assert env.state.state in ("mission_running", "done")
        assert (
            controller.store.load_task_state(pid, "mission-001").status_of("g1")
            == "cleared"
        )

        env = controller.advance_project(pid)
        assert env.state.state == "mission_running"
        env = controller.end_mission(pid)
        assert env.state.state == "done"

    def test_advance_syncs_bucket_skill_to_real_host_dir_before_dispatch(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        codex_skills = workspace / ".codex" / "skills"
        codex_skills.mkdir(parents=True)
        (codex_skills / "user-skill" / "SKILL.md").parent.mkdir()
        (codex_skills / "user-skill" / "SKILL.md").write_text("# User skill\n")

        saw_synced_skill = False

        def responder(req: DispatchRequest) -> NodeHandoff:
            nonlocal saw_synced_skill
            saw_synced_skill = (
                codex_skills / "new-worker" / "SKILL.md"
            ).exists()
            return WorkHandoff(node_id=req.task.id, done=True, report="ok")

        controller = ProjectController(
            config,
            MockDispatcher(responder),
            MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
        )
        pid = _seed_project(controller, workspace)
        bucket_skill = (
            controller.store.zenith_dir(pid)
            / "skills"
            / "new-worker"
            / "SKILL.md"
        )
        bucket_skill.parent.mkdir(parents=True)
        bucket_skill.write_text("# New worker\n")

        controller.submit_plan(
            pid,
            TaskList(tasks=[_task("w1", "work", ["VAL-001"], skill="new-worker")]),
        )
        controller.advance_project(pid, max_steps=1)

        assert saw_synced_skill
        assert codex_skills.is_dir()
        assert not codex_skills.is_symlink()

    def test_submit_plan_rejects_unknown_skill(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        controller = ProjectController(
            config,
            MockDispatcher(lambda r: WorkHandoff(node_id=r.task.id, done=True, report="")),
            MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
        )
        pid = _seed_project(controller, workspace)
        plan = TaskList(
            tasks=[
                _task(
                    "w1",
                    "work",
                    ["VAL-001"],
                    skill="missing-worker-skill",
                ),
                _task("v1", "validate", ["VAL-001"], depends_on=["w1"]),
                _task("g1", "gate", ["VAL-001"], depends_on=["v1"]),
            ]
        )

        with pytest.raises(ToolError) as err:
            controller.submit_plan(pid, plan)

        assert err.value.code == "invalid_task_list"
        assert err.value.details is not None
        assert any(detail.code == "unknown_skill" for detail in err.value.details)

    def test_patch_rejects_unknown_skill(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        controller = ProjectController(
            config,
            MockDispatcher(lambda r: WorkHandoff(node_id=r.task.id, done=True, report="")),
            MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
        )
        pid = _seed_project(controller, workspace)
        controller.submit_plan(pid, _simple_tl())
        contract_dir = controller.store.ensure_contract_dir(pid, "mission-001")
        (contract_dir / "NEW-001.md").write_text("# NEW-001\n\nStatement body.\n")
        patch = TaskListPatch(
            add_items=["NEW-001"],
            add=[
                _task(
                    "w2",
                    "work",
                    ["NEW-001"],
                    skill="missing-worker-skill",
                    depends_on=["g1"],
                ),
                _task("v2", "validate", ["NEW-001"], depends_on=["w2"]),
                _task("g2", "gate", ["NEW-001"], depends_on=["v2"]),
            ],
        )

        with pytest.raises(ToolError) as err:
            controller._apply_task_list_patch(pid, "mission-001", patch)

        assert err.value.code == "invalid_patch"
        assert err.value.details is not None
        assert any(detail.code == "unknown_skill" for detail in err.value.details)


class TestNodeFailedFlow:
    def test_work_failure_raises_attention(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        def responder(req: DispatchRequest) -> NodeHandoff:
            return WorkHandoff(node_id=req.task.id, done=False, report="blocked")

        controller = ProjectController(
            config, MockDispatcher(responder), MockTerminalReviewer(TerminalReviewHandoff(done=True, report=""))
        )
        pid = _seed_project(controller, workspace)
        controller.submit_plan(pid, _simple_tl())
        env = controller.advance_project(pid)
        assert env.state.state == "attention_needed"
        items = controller.store.load_attention(pid)
        assert items[0].kind == "node_failed"
        assert "blocked" in items[0].report


class TestRequestAttentionRaisesNodeAttention:
    def test_request_attention_true_raises(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        def responder(req: DispatchRequest) -> NodeHandoff:
            return WorkHandoff(
                node_id=req.task.id,
                done=True,
                report="finished",
                request_attention=True,
            )

        controller = ProjectController(
            config, MockDispatcher(responder), MockTerminalReviewer(TerminalReviewHandoff(done=True, report=""))
        )
        pid = _seed_project(controller, workspace)
        controller.submit_plan(pid, _simple_tl())
        env = controller.advance_project(pid)
        assert env.state.state == "attention_needed"
        items = controller.store.load_attention(pid)
        assert items[0].kind == "node_attention"
        assert "finished" in items[0].report


class TestGateFailed:
    def test_validator_failing_raises_gate_failed(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        def responder(req: DispatchRequest) -> NodeHandoff:
            if req.task.type == "work":
                return WorkHandoff(node_id=req.task.id, done=True, report="")
            return ValidateHandoff(
                node_id=req.task.id,
                done=True,
                report="found bug",
                items=[ValidationItem(item_id="VAL-001", passed=False)],
                passed=False,
            )

        controller = ProjectController(
            config, MockDispatcher(responder), MockTerminalReviewer(TerminalReviewHandoff(done=True, report=""))
        )
        pid = _seed_project(controller, workspace)
        controller.submit_plan(pid, _simple_tl())
        env = controller.advance_project(pid)
        assert env.state.state == "attention_needed"
        items = controller.store.load_attention(pid)
        assert items[0].kind == "gate_failed"


class TestGateOptional:
    def test_validator_failure_without_downstream_gate_raises_attention(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        def responder(req: DispatchRequest) -> NodeHandoff:
            if req.task.type == "work":
                return WorkHandoff(node_id=req.task.id, done=True, report="")
            return ValidateHandoff(
                node_id=req.task.id,
                done=True,
                report="found bug",
                items=[ValidationItem(item_id="VAL-001", passed=False)],
                passed=False,
            )

        controller = ProjectController(
            config, MockDispatcher(responder), MockTerminalReviewer(TerminalReviewHandoff(done=True, report=""))
        )
        pid = _seed_project(controller, workspace)
        controller.submit_plan(pid, _validate_no_gate_tl())
        env = controller.advance_project(pid)
        assert env.state.state == "attention_needed"
        items = controller.store.load_attention(pid)
        assert items[0].kind == "node_attention"
        assert "VAL-001: failed" in items[0].report


class TestValidatorDissentFailsGate:
    @staticmethod
    def _two_validator_tl() -> TaskList:
        return TaskList(
            tasks=[
                _task("w1", "work", ["VAL-001"]),
                _task("v-scrutiny", "validate", ["VAL-001"], skill="scrutiny-validator", depends_on=["w1"]),
                _task("v-user-surface", "validate", ["VAL-001"], skill="user-testing-validator", depends_on=["w1"]),
                _task("g1", "gate", ["VAL-001"], depends_on=["v-scrutiny", "v-user-surface"]),
            ]
        )

    def test_dissent_raises_gate_failed_not_checkpoint(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        def responder(req: DispatchRequest) -> NodeHandoff:
            if req.task.type == "work":
                return WorkHandoff(node_id=req.task.id, done=True, report="ok")
            passed = req.task.id == "v-scrutiny"
            return ValidateHandoff(
                node_id=req.task.id,
                done=True,
                report="scrutiny ok" if passed else "user-surface broken",
                items=[ValidationItem(item_id="VAL-001", passed=passed)],
                passed=passed,
            )

        controller = ProjectController(
            config, MockDispatcher(responder), MockTerminalReviewer(TerminalReviewHandoff(done=True, report=""))
        )
        pid = _seed_project(controller, workspace)
        controller.submit_plan(pid, self._two_validator_tl())
        env = controller.advance_project(pid)
        assert env.state.state == "attention_needed"
        items = controller.store.load_attention(pid)
        assert items[0].kind == "gate_failed"
        report = items[0].report
        assert "v-user-surface" in report
        assert "dissenting: VAL-001" in report
        assert "v-scrutiny: 1/1 passed" in report

    def test_all_validators_pass_clears_with_explicit_summary(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        def responder(req: DispatchRequest) -> NodeHandoff:
            if req.task.type == "work":
                return WorkHandoff(node_id=req.task.id, done=True, report="ok")
            return ValidateHandoff(
                node_id=req.task.id,
                done=True,
                report="audited",
                items=[ValidationItem(item_id="VAL-001", passed=True)],
                passed=True,
            )

        controller = ProjectController(
            config, MockDispatcher(responder), MockTerminalReviewer(TerminalReviewHandoff(done=True, report=""))
        )
        pid = _seed_project(controller, workspace)
        controller.submit_plan(pid, self._two_validator_tl())
        env = controller.advance_project(pid)
        assert env.state.state == "attention_needed"
        items = controller.store.load_attention(pid)
        assert items[0].kind == "gate_checkpoint"
        report = items[0].report
        assert "v-scrutiny: 1/1 passed" in report
        assert "v-user-surface: 1/1 passed" in report

    def test_validator_omitting_items_fails_gate(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        def responder(req: DispatchRequest) -> NodeHandoff:
            if req.task.type == "work":
                return WorkHandoff(node_id=req.task.id, done=True, report="ok")
            if req.task.id == "v-scrutiny":
                return ValidateHandoff(
                    node_id=req.task.id,
                    done=True,
                    report="scrutiny ok",
                    items=[ValidationItem(item_id="VAL-001", passed=True)],
                    passed=True,
                )
            return ValidateHandoff(
                node_id=req.task.id,
                done=True,
                report="ran but rendered no verdict",
                items=[],
                passed=False,
            )

        controller = ProjectController(
            config, MockDispatcher(responder), MockTerminalReviewer(TerminalReviewHandoff(done=True, report=""))
        )
        pid = _seed_project(controller, workspace)
        controller.submit_plan(pid, self._two_validator_tl())
        env = controller.advance_project(pid)
        assert env.state.state == "attention_needed"
        items = controller.store.load_attention(pid)
        assert items[0].kind == "gate_failed"
        report = items[0].report
        assert "v-user-surface" in report
        assert "missing: VAL-001" in report


class TestDecideAttentionValidation:
    def test_atomic_rejection(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        def responder(req: DispatchRequest) -> NodeHandoff:
            return WorkHandoff(node_id=req.task.id, done=False, report="blocked")

        controller = ProjectController(
            config, MockDispatcher(responder), MockTerminalReviewer(TerminalReviewHandoff(done=True, report=""))
        )
        pid = _seed_project(controller, workspace)
        controller.submit_plan(pid, _simple_tl())
        controller.advance_project(pid)
        items = controller.store.load_attention(pid)
        with pytest.raises(ToolError) as exc:
            controller.decide_attention(
                pid,
                [Decision(item_id=items[0].id, action="next_mission")],
            )
        assert exc.value.code == "invalid_decisions"

    def test_missing_decision_rejected(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        def responder(req: DispatchRequest) -> NodeHandoff:
            return WorkHandoff(node_id=req.task.id, done=False, report="blocked")

        controller = ProjectController(
            config, MockDispatcher(responder), MockTerminalReviewer(TerminalReviewHandoff(done=True, report=""))
        )
        pid = _seed_project(controller, workspace)
        controller.submit_plan(pid, _simple_tl())
        controller.advance_project(pid)
        with pytest.raises(ToolError) as exc:
            controller.decide_attention(pid, [])
        assert any(
            "unresolved_attention_item" in str(d) for d in (exc.value.details or [])
        )


class TestTerminalReview:
    def test_clean_review_to_done(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        responses: list[NodeHandoff] = [
            WorkHandoff(node_id="w1", done=True, report=""),
            ValidateHandoff(
                node_id="v1",
                done=True,
                report="",
                items=[ValidationItem(item_id="VAL-001", passed=True)],
                passed=True,
            ),
        ]
        gen = iter(responses)

        def responder(req: DispatchRequest) -> NodeHandoff:
            return next(gen)

        controller = ProjectController(
            config,
            MockDispatcher(responder),
            MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
        )
        pid = _seed_project(controller, workspace)
        controller.submit_plan(pid, _simple_tl())
        controller.advance_project(pid)
        items = controller.store.load_attention(pid)
        controller.decide_attention(
            pid, [Decision(item_id=items[0].id, action="continue")]
        )
        env = controller.advance_project(pid)
        assert env.state.state == "mission_running"
        env = controller.end_mission(pid)
        assert env.state.state == "done"

    def test_terminal_review_report_raises_attention(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        def responder(req: DispatchRequest) -> NodeHandoff:
            if req.task.type == "work":
                return WorkHandoff(node_id=req.task.id, done=True, report="")
            return ValidateHandoff(
                node_id=req.task.id,
                done=True,
                report="",
                items=[ValidationItem(item_id="VAL-001", passed=True)],
                passed=True,
            )

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
        controller = ProjectController(config, MockDispatcher(responder), reviewer)
        pid = _seed_project(controller, workspace)
        controller.submit_plan(pid, _simple_tl())
        controller.advance_project(pid)
        items = controller.store.load_attention(pid)
        controller.decide_attention(
            pid, [Decision(item_id=items[0].id, action="continue")]
        )
        env = controller.advance_project(pid)
        assert env.state.state == "mission_running"
        env = controller.end_mission(pid)
        assert env.state.state == "attention_needed"
        items = controller.store.load_attention(pid)
        assert items[0].kind == "terminal_review"
        assert "missing endpoint" in items[0].report


class TestDecideAttentionPatchAddItems:
    """Regression: decide_attention(patch) with add_items must source
    old_ids from contract-state, not from disk listing."""

    def test_add_items_through_decide_attention_succeeds(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        def responder(req: DispatchRequest) -> NodeHandoff:
            if req.task.type == "work":
                return WorkHandoff(node_id=req.task.id, done=True, report="")
            return ValidateHandoff(
                node_id=req.task.id,
                done=True,
                report="audited",
                items=[ValidationItem(item_id="VAL-001", passed=True)],
                passed=True,
            )

        controller = ProjectController(
            config, MockDispatcher(responder), MockTerminalReviewer(TerminalReviewHandoff(done=True, report=""))
        )
        pid = _seed_project(controller, workspace)
        controller.submit_plan(pid, _simple_tl())
        env = controller.advance_project(pid)
        assert env.state.state == "attention_needed"
        items = controller.store.load_attention(pid)
        assert items[0].kind == "gate_checkpoint"

        contract_dir = controller.store.ensure_contract_dir(pid, "mission-001")
        (contract_dir / "NEW-001.md").write_text("# NEW-001\n\nNew assertion.\n")

        # Patch declaring NEW-001 + supporting tasks. The new gate depends on
        # g1 transitively via the new work task (which depends on g1).
        patch = TaskListPatch(
            add_items=["NEW-001"],
            add=[
                _task("w2", "work", ["NEW-001"], depends_on=["g1"]),
                _task("v2", "validate", ["NEW-001"], depends_on=["w2"]),
                _task("g2", "gate", ["NEW-001"], depends_on=["v2"]),
            ],
        )
        env2 = controller.decide_attention(
            pid,
            [Decision(item_id=items[0].id, action="patch", patch=patch)],
        )
        assert env2.state.state == "mission_running"


class TestEnvelopeProjectId:
    def test_envelope_carries_project_id(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        controller = ProjectController(
            config, MockDispatcher(lambda r: WorkHandoff(node_id=r.task.id, done=True, report="")),
            MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
        )
        pid = _seed_project(controller, workspace)
        env = controller.inspect_project(pid)
        assert env.projectId == pid
        env2 = controller.inspect_project(env.projectId)
        assert env2.projectId == env.projectId

    def test_tool_specific_dag_modes(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        def responder(req: DispatchRequest) -> NodeHandoff:
            if req.task.type == "work":
                return WorkHandoff(node_id=req.task.id, done=True, report="ok")
            return ValidateHandoff(
                node_id=req.task.id,
                done=True,
                report="audited",
                items=[ValidationItem(item_id="VAL-001", passed=True)],
                passed=True,
            )

        controller = ProjectController(
            config,
            MockDispatcher(responder),
            MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
        )
        start = controller.start_project("Brief.", str(workspace))
        assert start.dag is None
        pid = start.projectId
        contract_dir = controller.store.ensure_contract_dir(pid, "mission-001")
        (contract_dir / "VAL-001.md").write_text("# VAL-001\n\nStatement body.\n")

        submitted = controller.submit_plan(pid, _simple_tl())
        assert submitted.dag is not None
        assert "    w1  [work:engineering-mission-playbook]  pending  → VAL-001  ← (root)" in submitted.dag
        assert "focus-subgraph" not in submitted.dag

        inspected = controller.inspect_project(pid)
        assert inspected.dag is not None
        assert "    w1" in inspected.dag
        assert "    v1" in inspected.dag
        assert "    g1" in inspected.dag
        assert "focus-subgraph" not in inspected.dag

        advanced = controller.advance_project(pid, max_steps=1)
        assert advanced.dag is not None
        assert "focus-subgraph" not in advanced.dag

        attention = controller.advance_project(pid)
        assert attention.state.state == "attention_needed"
        assert attention.dag is not None
        assert "focus-subgraph" not in attention.dag
        items = controller.store.load_attention(pid)

        decided = controller.decide_attention(
            pid, [Decision(item_id=items[0].id, action="continue")]
        )
        assert decided.dag is None

        controller.advance_project(pid)
        ended = controller.end_mission(pid)
        assert ended.dag is None


class TestAbortProject:
    def test_aborts(self, config: HarnessConfig, workspace: Path) -> None:
        controller = ProjectController(
            config, MockDispatcher(lambda r: WorkHandoff(node_id=r.task.id, done=True, report="")),
            MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
        )
        pid = _seed_project(controller, workspace)
        controller.submit_plan(pid, _simple_tl())
        env = controller.abort_project(pid, "user requested")
        assert env.state.state == "aborted"
        assert env.dag is None


class TestResume:
    def test_resume_picks_up_attempt_landed_while_down(
        self, config: HarnessConfig, workspace: Path
    ) -> None:
        controller = ProjectController(
            config,
            MockDispatcher(lambda r: WorkHandoff(node_id=r.task.id, done=True, report="")),
            MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
        )
        pid = _seed_project(controller, workspace)
        store = controller.store
        controller.submit_plan(pid, _simple_tl())

        ts = store.load_task_state(pid, "mission-001")
        ts.set_status("w1", "running")
        ts.set_last_attempt("w1", "2026-01-01T00-00-00Z")
        store.save_task_state(pid, "mission-001", ts)
        store.save_attempt(
            pid,
            "mission-001",
            "2026-01-01T00-00-00Z",
            "w1",
            WorkHandoff(node_id="w1", done=True, report="landed"),
        )
        store.save_state(pid, MissionRunning(mission_id="mission-001"))
        controller.advance_project(pid)
        ts = store.load_task_state(pid, "mission-001")
        assert ts.status_of("w1") == "cleared"
