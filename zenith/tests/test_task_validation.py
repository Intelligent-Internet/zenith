"""Submit-time task-list validation. See `specs/task_list/PRODUCT.md`."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from zenith_harness.models import ApiGrantRequest, BillingPolicy, Task, TaskList
from zenith_harness.task_validation import (
    check_acyclic,
    check_coverage,
    check_deps_resolve,
    check_task_ids,
    check_task_shape,
    parse_contract_dir,
    validate_task_list_submission,
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
        skill = "s"
    return Task(
        id=tid,
        type=ttype,  # type: ignore[arg-type]
        body="" if ttype == "gate" else body,
        targets=targets,
        skill=skill,
        depends_on=depends_on or [],
    )


class TestParseContractDir:
    def test_missing_dir(self, tmp_path: Path) -> None:
        ids, errs = parse_contract_dir(tmp_path / "nope")
        assert ids == set()
        assert errs[0].code == "contract_dir_missing"

    def test_lists_files(self, tmp_path: Path) -> None:
        for name in ["VAL-001.md", "VAL-002.md", "README.md"]:
            (tmp_path / name).write_text("body")
        ids, errs = parse_contract_dir(tmp_path)
        assert ids == {"VAL-001", "VAL-002"}
        assert errs == []

    def test_invalid_filename(self, tmp_path: Path) -> None:
        (tmp_path / "VAL-001.md").write_text("ok")
        (tmp_path / "lowercase.md").write_text("bad")
        ids, errs = parse_contract_dir(tmp_path)
        assert ids == {"VAL-001"}
        assert any(e.code == "invalid_assertion_filename" for e in errs)


class TestTaskIds:
    def test_duplicate_task_id(self) -> None:
        tl = TaskList(tasks=[
            _task("w1", "work", ["X"]),
            _task("w1", "work", ["Y"]),
        ])
        errs = check_task_ids(tl)
        assert any(e.code == "duplicate_task_id" for e in errs)

    def test_invalid_task_id(self) -> None:
        tl = TaskList(tasks=[_task("9bad", "work", ["X"])])
        errs = check_task_ids(tl)
        assert any(e.code == "invalid_task_id" for e in errs)


class TestTaskShape:
    def test_gate_with_skill_rejected(self) -> None:
        # Bypass the helper to construct a malformed gate.
        tl = TaskList(tasks=[
            Task(id="g1", type="gate", body="", targets=["X"], skill="some-skill")
        ])
        errs = check_task_shape(tl)
        assert any(e.code == "gate_with_skill" for e in errs)

    def test_gate_with_body_rejected(self) -> None:
        tl = TaskList(tasks=[
            Task(id="g1", type="gate", body="must be empty", targets=["X"], skill=None)
        ])
        errs = check_task_shape(tl)
        assert any(e.code == "gate_with_body" for e in errs)

    def test_work_without_skill_rejected(self) -> None:
        tl = TaskList(tasks=[
            Task(id="w1", type="work", body="b", targets=["X"], skill=None)
        ])
        errs = check_task_shape(tl)
        assert any(e.code == "non_gate_without_skill" for e in errs)

    def test_work_without_body_rejected(self) -> None:
        tl = TaskList(tasks=[
            Task(id="w1", type="work", body="", targets=["X"], skill="s")
        ])
        errs = check_task_shape(tl)
        assert any(e.code == "missing_body" for e in errs)

    def test_empty_targets_work_allowed(self) -> None:
        tl = TaskList(tasks=[_task("w1", "work", [])])
        errs = check_task_shape(tl)
        assert not any(e.code == "empty_targets" for e in errs)

    def test_empty_targets_validate_rejected(self) -> None:
        tl = TaskList(tasks=[_task("v1", "validate", [])])
        errs = check_task_shape(tl)
        assert any(e.code == "empty_targets" for e in errs)

    def test_empty_targets_gate_rejected(self) -> None:
        tl = TaskList(tasks=[_task("g1", "gate", [])])
        errs = check_task_shape(tl)
        assert any(e.code == "empty_targets" for e in errs)

    def test_gate_with_api_billing_rejected(self) -> None:
        task = _task("g1", "gate", ["X"])
        task = task.model_copy(
            update={
                "billing": BillingPolicy(
                    mode="api",
                    api_grant=ApiGrantRequest(
                        grant_id="grant-001",
                        api_project="project",
                        max_usd="1.00",
                        expires_at=datetime.now(UTC) + timedelta(hours=1),
                    ),
                )
            }
        )
        errs = check_task_shape(TaskList(tasks=[task]))
        assert any(e.code == "gate_with_api_billing" for e in errs)


class TestDepsResolve:
    def test_dep_unknown_task(self) -> None:
        tl = TaskList(tasks=[
            _task("w1", "work", ["X"], depends_on=["ghost"]),
        ])
        errs = check_deps_resolve(tl)
        assert any(e.code == "dep_unknown_task" for e in errs)

    def test_self_loop(self) -> None:
        tl = TaskList(tasks=[
            _task("w1", "work", ["X"], depends_on=["w1"]),
        ])
        errs = check_deps_resolve(tl)
        assert any(e.code == "self_loop" for e in errs)


class TestAcyclic:
    def test_acyclic(self) -> None:
        tl = TaskList(tasks=[
            _task("a", "work", ["X"]),
            _task("b", "work", ["Y"], depends_on=["a"]),
        ])
        assert check_acyclic(tl) == []

    def test_mutual_cycle(self) -> None:
        tl = TaskList(tasks=[
            _task("a", "work", ["X"], depends_on=["b"]),
            _task("b", "work", ["Y"], depends_on=["a"]),
        ])
        errs = check_acyclic(tl)
        assert any(e.code == "cycle_detected" for e in errs)

    def test_transitive_cycle(self) -> None:
        tl = TaskList(tasks=[
            _task("a", "work", ["X"], depends_on=["c"]),
            _task("b", "work", ["Y"], depends_on=["a"]),
            _task("c", "work", ["Z"], depends_on=["b"]),
        ])
        errs = check_acyclic(tl)
        assert any(e.code == "cycle_detected" for e in errs)


class TestCoverage:
    def test_uncovered(self) -> None:
        tl = TaskList(tasks=[_task("v1", "validate", ["X"])])
        errs = check_coverage({"X"}, tl)
        assert any(e.code == "uncovered_assertion" for e in errs)

    def test_over_covered(self) -> None:
        tl = TaskList(tasks=[
            _task("w1", "work", ["X"]),
            _task("w2", "work", ["X"]),
        ])
        errs = check_coverage({"X"}, tl)
        assert any(e.code == "over_covered_assertion" for e in errs)

    def test_unknown_assertion_target(self) -> None:
        tl = TaskList(tasks=[_task("w1", "work", ["X", "UNKNOWN"])])
        errs = check_coverage({"X"}, tl)
        assert any(e.code == "task_targets_unknown_assertion" for e in errs)


class TestValidateSubmission:
    def test_full_pipeline_clean(self) -> None:
        tl = TaskList(tasks=[
            _task("w1", "work", ["X"]),
            _task("v1", "validate", ["X"], skill="aud", depends_on=["w1"]),
            _task("g1", "gate", ["X"], depends_on=["v1"]),
        ])
        assert validate_task_list_submission({"X"}, tl) == []

    def test_empty_task_list_rejected(self) -> None:
        tl = TaskList(tasks=[])
        errs = validate_task_list_submission({"X"}, tl)
        assert errs and errs[0].code == "empty_task_list"

    def test_empty_contract_rejected(self) -> None:
        # Targetless work tasks over an empty contract pass every other
        # check vacuously; the contract itself must be non-empty.
        tl = TaskList(tasks=[_task("w1", "work", [])])
        errs = validate_task_list_submission(set(), tl)
        assert errs and errs[0].code == "empty_contract"

    def test_empty_contract_reported_before_empty_task_list(self) -> None:
        # Contract authoring precedes task authoring; point at the
        # earliest missing artifact first.
        errs = validate_task_list_submission(set(), TaskList(tasks=[]))
        assert errs and errs[0].code == "empty_contract"

    def test_validator_requires_targets(self) -> None:
        tl = TaskList(tasks=[
            _task("v1", "validate", []),
        ])
        errs = validate_task_list_submission({"X"}, tl)
        assert errs and errs[0].code == "empty_targets"
