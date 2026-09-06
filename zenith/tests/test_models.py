"""Unit tests for v5 schemas (task-list shape)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from zenith_harness.models import (
    ApiGrantRequest,
    AttentionNeeded,
    BillingPolicy,
    Decision,
    Draft,
    Envelope,
    Task,
    TaskList,
    TaskListPatch,
    TaskStateFile,
    TerminalReviewHandoff,
    ValidateHandoff,
    ValidationItem,
    WorkHandoff,
)


class TestTask:
    def test_minimal_work(self) -> None:
        t = Task(id="w1", type="work", body="do it", targets=["VAL-001"], skill="api-contract-worker")
        assert t.id == "w1"
        assert t.skill == "api-contract-worker"
        assert t.depends_on == []
        assert t.auto_merge is True
        assert t.billing.mode == "subscription"
        assert t.billing.api_grant is None

    def test_api_billing_requires_explicit_grant(self) -> None:
        with pytest.raises(PydanticValidationError):
            BillingPolicy(mode="api")

    def test_subscription_rejects_api_grant(self) -> None:
        from datetime import UTC, datetime, timedelta

        request = ApiGrantRequest(
            grant_id="grant-001",
            api_project="project",
            max_usd="1.00",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        with pytest.raises(PydanticValidationError):
            BillingPolicy(mode="subscription", api_grant=request)

    def test_task_rejects_inline_api_key(self) -> None:
        with pytest.raises(PydanticValidationError):
            Task(
                id="w1",
                type="work",
                body="work",
                targets=["VAL-001"],
                skill="s",
                billing={
                    "mode": "api",
                    "api_grant": {
                        "grant_id": "grant-001",
                        "api_project": "project",
                        "max_usd": "1.00",
                        "expires_at": "2026-09-04T18:00:00Z",
                        "api_key": "must-never-be-accepted",
                    },
                },
            )

    def test_work_accepts_legacy_auto_merge_field(self) -> None:
        t = Task(
            id="w1",
            type="work",
            body="do it",
            targets=["VAL-001"],
            skill="api-contract-worker",
            auto_merge=False,
        )
        assert t.auto_merge is False

    def test_gate_has_no_skill(self) -> None:
        t = Task(id="g1", type="gate", body="", targets=["VAL-001"])
        assert t.skill is None

    def test_depends_on_carries_ids(self) -> None:
        t = Task(id="v1", type="validate", body="check", targets=["X"], skill="aud",
                 depends_on=["w1", "w2"])
        assert t.depends_on == ["w1", "w2"]

    def test_unknown_type_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            Task(id="x", type="other", body="", targets=["VAL-001"], skill="s")  # type: ignore[arg-type]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            Task(  # type: ignore[call-arg]
                id="w1",
                type="work",
                body="",
                targets=["X"],
                skill="s",
                phase=2,
            )


class TestTaskList:
    def test_empty(self) -> None:
        tl = TaskList(tasks=[])
        assert tl.tasks == []

    def test_roundtrip(self) -> None:
        tl = TaskList(tasks=[
            Task(id="w1", type="work", body="b", targets=["X"], skill="s"),
            Task(id="g1", type="gate", body="", targets=["X"], depends_on=["w1"]),
        ])
        dumped = tl.model_dump()
        again = TaskList.model_validate(dumped)
        assert again == tl


class TestTaskListPatch:
    def test_is_empty_default(self) -> None:
        assert TaskListPatch().is_empty

    def test_not_empty(self) -> None:
        assert not TaskListPatch(add_items=["X"]).is_empty
        assert not TaskListPatch(supersede={"w1": "w2"}).is_empty
        assert not TaskListPatch(cancel=["w1"]).is_empty
        assert not TaskListPatch(
            add=[Task(id="w2", type="work", body="b", targets=["X"], skill="s")]
        ).is_empty

    def test_rejects_legacy_fields(self) -> None:
        with pytest.raises(PydanticValidationError):
            TaskListPatch(add_nodes=[])  # type: ignore[call-arg]
        with pytest.raises(PydanticValidationError):
            TaskListPatch(add_edges=[])  # type: ignore[call-arg]
        with pytest.raises(PydanticValidationError):
            TaskListPatch(supersede_nodes=[])  # type: ignore[call-arg]


class TestDecision:
    def test_basic(self) -> None:
        d = Decision(item_id="att-1", action="continue")
        assert d.action == "continue"
        assert d.patch is None

    def test_with_patch(self) -> None:
        d = Decision(
            item_id="att-1",
            action="patch",
            patch=TaskListPatch(add_items=["X"]),
        )
        assert d.patch is not None
        assert d.patch.add_items == ["X"]

    def test_unknown_action(self) -> None:
        with pytest.raises(PydanticValidationError):
            Decision(item_id="x", action="custom")  # type: ignore[arg-type]


class TestProjectState:
    @pytest.mark.parametrize(
        "payload",
        [
            {"state": "draft"},
            {"state": "mission_planning", "mission_id": "m1"},
            {"state": "mission_running", "mission_id": "m1"},
            {"state": "attention_needed", "items": []},
            {"state": "done"},
            {"state": "failed", "reason": "boom"},
            {"state": "aborted", "reason": "user"},
        ],
    )
    def test_discriminator(self, payload: dict[str, object]) -> None:
        env = Envelope(
            projectId="p1",
            state=payload,  # type: ignore[arg-type]
            projectRoot="/tmp/.zenith",
            harnessRoot="/home/u/.zenith/projects/p1",
        )
        assert env.state.state == payload["state"]

    def test_attention_carries_items(self) -> None:
        env = Envelope(
            projectId="p1",
            state={
                "state": "attention_needed",
                "items": [{"id": "a", "report": "Task report from w1\nreport:\nok"}],
            },  # type: ignore[arg-type]
            projectRoot="/tmp/.zenith",
            harnessRoot="/home/u/.zenith/projects/p1",
        )
        assert isinstance(env.state, AttentionNeeded)
        assert env.state.items[0].id == "a"


class TestEnvelope:
    def test_fields(self) -> None:
        env = Envelope(
            projectId="proj-1",
            state=Draft(),
            projectRoot="/tmp/.zenith",
            harnessRoot="/home/u/.zenith/projects/proj-1",
            dag=None,
        )
        dumped = env.model_dump()
        assert set(dumped.keys()) == {
            "projectId",
            "state",
            "projectRoot",
            "harnessRoot",
            "dag",
        }


class TestWorkerHandoffs:
    def test_work_handoff(self) -> None:
        h = WorkHandoff(node_id="w1", done=True, report="ok")
        assert h.request_attention is False

    def test_work_handoff_extra_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            WorkHandoff(node_id="w1", done=True, report="", commit_id="abc")  # type: ignore[call-arg]

    def test_validate_handoff(self) -> None:
        h = ValidateHandoff(
            node_id="v1",
            done=True,
            report="audited",
            items=[ValidationItem(item_id="VAL-001", passed=True)],
            passed=True,
        )
        assert h.items[0].passed is True

    def test_terminal_review_handoff(self) -> None:
        r = TerminalReviewHandoff(done=False, report="missing endpoint")
        assert r.report == "missing endpoint"


class TestTaskStateFile:
    def test_default_pending(self) -> None:
        ts = TaskStateFile()
        assert ts.status_of("w1") == "pending"

    def test_set_and_read(self) -> None:
        ts = TaskStateFile()
        ts.set_status("w1", "running")
        assert ts.status_of("w1") == "running"
        ts.set_status("w1", "cleared")
        assert ts.status_of("w1") == "cleared"
