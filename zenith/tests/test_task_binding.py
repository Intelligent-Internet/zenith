"""Controller tests for one-shot post-submit task placeholder binding."""
from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from zenith_harness.config import HarnessConfig
from zenith_harness.controller import ProjectController, ToolError
from zenith_harness.dispatcher import (
    MockDispatcher,
    MockTerminalReviewer,
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
from zenith_harness import storage as storage_module


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
    task_id: str,
    task_type: str,
    targets: list[str],
    *,
    body: str,
    skill: str | None = "worker",
    depends_on: list[str] | None = None,
) -> Task:
    return Task(
        id=task_id,
        type=task_type,  # type: ignore[arg-type]
        body=body,
        targets=targets,
        skill=None if task_type == "gate" else skill,
        depends_on=depends_on or [],
    )


def _controller(config: HarnessConfig) -> ProjectController:
    return ProjectController(
        config,
        MockDispatcher(
            lambda request: WorkHandoff(node_id=request.task.id, done=True, report="unused")
        ),
        MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
    )


def _seed_project(
    controller: ProjectController,
    workspace: Path,
    *,
    task_body: str = "launch={{RECEIPT}} path={{PATH}}",
) -> str:
    controller.start_project("Bind a launch receipt.", str(workspace))
    project_id = controller.store.list_projects()[0].id
    contract_dir = controller.store.ensure_contract_dir(project_id, "mission-001")
    (contract_dir / "VAL-001.md").write_text("# VAL-001\n\nReceipt is consumed.\n")
    controller.submit_plan(
        project_id,
        TaskList(
            tasks=[
                _task(
                    "w1",
                    "work",
                    ["VAL-001"],
                    body=task_body,
                    skill="worker",
                ),
                _task(
                    "v1",
                    "validate",
                    ["VAL-001"],
                    body="audit receipt consumption",
                    skill="auditor",
                    depends_on=["w1"],
                ),
                _task(
                    "g1",
                    "gate",
                    ["VAL-001"],
                    body="",
                    skill=None,
                    depends_on=["v1"],
                ),
            ]
        ),
    )
    return project_id


def _task_list_digest(task_list: TaskList) -> str:
    canonical = json.dumps(
        task_list.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _audit_path(controller: ProjectController, project_id: str) -> Path:
    return controller.store.mission_runtime_dir(project_id, "mission-001") / "tasks.json"


def _has_audit(controller: ProjectController, project_id: str) -> bool:
    path = _audit_path(controller, project_id)
    if not path.exists():
        return False
    return "_binding_audit" in json.loads(path.read_text(encoding="utf-8"))


def test_bind_task_placeholders_replaces_only_one_task_and_records_safe_audit(
    config: HarnessConfig, workspace: Path
) -> None:
    controller = _controller(config)
    project_id = _seed_project(controller, workspace)
    store = controller.store
    before = store.load_task_list(project_id, "mission-001")
    before_state = store.load_task_state(project_id, "mission-001")
    before_contract_state = store.load_contract_state(project_id, "mission-001")

    controller.bind_task_placeholders(
        project_id,
        "w1",
        {"{{RECEIPT}}": "/tmp/launch-receipt.json", "{{PATH}}": "receipt.json"},
    )

    after = store.load_task_list(project_id, "mission-001")
    target_before = next(task for task in before.tasks if task.id == "w1")
    target_after = next(task for task in after.tasks if task.id == "w1")
    assert target_after.body == "launch=/tmp/launch-receipt.json path=receipt.json"
    assert target_after.model_dump(exclude={"body"}) == target_before.model_dump(
        exclude={"body"}
    )
    assert [task for task in after.tasks if task.id != "w1"] == [
        task for task in before.tasks if task.id != "w1"
    ]
    assert store.load_task_state(project_id, "mission-001") == before_state
    assert store.load_contract_state(project_id, "mission-001") == before_contract_state
    assert store.list_attempts(project_id, "mission-001") == []

    audit_path = _audit_path(controller, project_id)
    assert audit_path.exists()
    audit_text = audit_path.read_text(encoding="utf-8")
    audit_payload = json.loads(audit_text)
    assert "_binding_audit" in audit_payload
    audit = audit_payload["_binding_audit"]
    assert audit["task_id"] == "w1"
    assert audit["before_task_list_sha256"] == _task_list_digest(before)
    assert audit["after_task_list_sha256"] == _task_list_digest(after)
    assert audit["bindings"] == {
        "{{PATH}}": hashlib.sha256(b"receipt.json").hexdigest(),
        "{{RECEIPT}}": hashlib.sha256(b"/tmp/launch-receipt.json").hexdigest(),
    }
    audit_metadata_text = json.dumps(audit)
    assert "/tmp/launch-receipt.json" not in audit_metadata_text
    assert "receipt.json" not in audit_metadata_text


def test_ordinary_task_list_save_preserves_internal_audit(
    config: HarnessConfig, workspace: Path
) -> None:
    controller = _controller(config)
    project_id = _seed_project(controller, workspace)
    controller.bind_task_placeholders(project_id, "w1", {"{{RECEIPT}}": "bound"})
    audit_before = controller.store.load_task_binding_audit(project_id, "mission-001")
    task_list = controller.store.load_task_list(project_id, "mission-001")

    controller.store.save_task_list(project_id, "mission-001", task_list)

    assert controller.store.load_task_binding_audit(project_id, "mission-001") == audit_before


def test_atomic_task_file_failure_keeps_complete_old_json(
    config: HarnessConfig, workspace: Path, monkeypatch
) -> None:
    controller = _controller(config)
    project_id = _seed_project(controller, workspace)
    path = _audit_path(controller, project_id)
    before_bytes = path.read_bytes()
    before = controller.store.load_task_list(project_id, "mission-001")

    monkeypatch.setattr(
        storage_module.os,
        "replace",
        lambda source, target: (_ for _ in ()).throw(OSError("injected replace failure")),
    )
    with pytest.raises(OSError, match="injected replace failure"):
        controller.bind_task_placeholders(project_id, "w1", {"{{RECEIPT}}": "bound"})

    assert path.read_bytes() == before_bytes
    assert controller.store.load_task_list(project_id, "mission-001") == before
    assert controller.store.load_task_binding_audit(project_id, "mission-001") is None


def test_valid_json_with_malformed_audit_is_rejected(
    config: HarnessConfig, workspace: Path
) -> None:
    controller = _controller(config)
    project_id = _seed_project(controller, workspace)
    path = _audit_path(controller, project_id)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["_binding_audit"] = {
        "version": 1,
        "task_id": "w1",
        "before_task_list_sha256": "not-a-digest",
        "after_task_list_sha256": "0" * 64,
        "bindings": {"{{RECEIPT}}": "0" * 64},
        "bound_at": "2026-01-01T00:00:00Z",
    }
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ToolError) as exc:
        controller.advance_project(project_id)

    assert exc.value.code == "invalid_task_binding_audit"


def test_bind_task_placeholders_rejects_repeat_without_touching_task_list(
    config: HarnessConfig, workspace: Path
) -> None:
    controller = _controller(config)
    project_id = _seed_project(controller, workspace)
    controller.bind_task_placeholders(project_id, "w1", {"{{RECEIPT}}": "first"})
    store = controller.store
    before_tasks = store.load_task_list(project_id, "mission-001")
    before_audit = _audit_path(controller, project_id).read_bytes()

    with pytest.raises(ToolError) as exc:
        controller.bind_task_placeholders(project_id, "w1", {"{{PATH}}": "second"})

    assert exc.value.code == "task_binding_already_applied"
    assert exc.value.message == "task placeholders already bound for this mission"
    assert store.load_task_list(project_id, "mission-001") == before_tasks
    assert _audit_path(controller, project_id).read_bytes() == before_audit


@pytest.mark.parametrize(
    ("bindings", "code", "message"),
    [
        ({}, "empty_bindings", "bindings must not be empty"),
        ({"": "value"}, "empty_placeholder", "placeholder must not be empty"),
        ({"{{TOKEN}}": ""}, "empty_replacement", "replacement must not be empty"),
        (
            {"{{TOKEN}}": "{{TOKEN}}"},
            "identical_binding",
            "placeholder and replacement must differ",
        ),
        (
            {"{{MISSING}}": "value"},
            "placeholder_missing",
            "placeholder must occur exactly once in task body",
        ),
        (
            {"{{TOKEN}}": "value"},
            "ambiguous_placeholder",
            "placeholder occurs more than once in task body",
        ),
    ],
)
def test_bind_task_placeholders_rejects_invalid_binding_without_partial_write(
    config: HarnessConfig,
    workspace: Path,
    bindings: dict[str, str],
    code: str,
    message: str,
) -> None:
    controller = _controller(config)
    project_id = _seed_project(controller, workspace, task_body="{{TOKEN}} {{TOKEN}}")
    store = controller.store
    before = store.load_task_list(project_id, "mission-001")

    with pytest.raises(ToolError) as exc:
        controller.bind_task_placeholders(project_id, "w1", bindings)

    assert exc.value.code == code
    assert exc.value.message == message
    assert store.load_task_list(project_id, "mission-001") == before
    assert not _has_audit(controller, project_id)


def test_bind_task_placeholders_rejects_unknown_and_gate_tasks(
    config: HarnessConfig, workspace: Path
) -> None:
    controller = _controller(config)
    project_id = _seed_project(controller, workspace)

    with pytest.raises(ToolError) as unknown:
        controller.bind_task_placeholders(project_id, "unknown", {"{{RECEIPT}}": "x"})
    assert unknown.value.code == "unknown_task"

    with pytest.raises(ToolError) as gate:
        controller.bind_task_placeholders(project_id, "g1", {"{{RECEIPT}}": "x"})
    assert gate.value.code == "gate_task"

    assert not _has_audit(controller, project_id)


def test_bind_task_placeholders_requires_running_state(
    config: HarnessConfig, workspace: Path
) -> None:
    controller = _controller(config)
    controller.start_project("Still planning.", str(workspace))
    project_id = controller.store.list_projects()[0].id

    with pytest.raises(ToolError) as exc:
        controller.bind_task_placeholders(project_id, "w1", {"{{TOKEN}}": "x"})

    assert exc.value.code == "wrong_state"
    assert exc.value.message == "bind_task_placeholders requires MissionRunning; got mission_planning"


def test_bind_task_placeholders_rejects_any_task_state_or_attempt(
    config: HarnessConfig, workspace: Path
) -> None:
    controller = _controller(config)
    project_id = _seed_project(controller, workspace)
    store = controller.store

    task_state = store.load_task_state(project_id, "mission-001")
    task_state.set_status("v1", "cleared")
    store.save_task_state(project_id, "mission-001", task_state)
    with pytest.raises(ToolError) as non_pending:
        controller.bind_task_placeholders(project_id, "w1", {"{{RECEIPT}}": "x"})
    assert non_pending.value.code == "invalid_task_state"
    assert not _has_audit(controller, project_id)

    task_state.set_status("v1", "pending")
    task_state.set_last_attempt("v1", "2026-01-01T00-00-00Z")
    store.save_task_state(project_id, "mission-001", task_state)
    with pytest.raises(ToolError) as last_attempt:
        controller.bind_task_placeholders(project_id, "w1", {"{{RECEIPT}}": "x"})
    assert last_attempt.value.code == "invalid_task_state"
    assert not _has_audit(controller, project_id)

    task_state.tasks["v1"].last_attempt = None
    store.save_task_state(project_id, "mission-001", task_state)
    store.save_attempt(
        project_id,
        "mission-001",
        "2026-01-01T00-00-00Z",
        "v1",
        WorkHandoff(node_id="v1", done=True, report="already attempted"),
    )
    with pytest.raises(ToolError) as existing_attempt:
        controller.bind_task_placeholders(project_id, "w1", {"{{RECEIPT}}": "x"})
    assert existing_attempt.value.code == "attempts_exist"
    assert not _has_audit(controller, project_id)


def test_bind_task_placeholders_requires_exact_task_state_entries(
    config: HarnessConfig, workspace: Path
) -> None:
    controller = _controller(config)
    project_id = _seed_project(controller, workspace)
    store = controller.store
    task_state = store.load_task_state(project_id, "mission-001")
    task_state.tasks.pop("v1")
    store.save_task_state(project_id, "mission-001", task_state)

    with pytest.raises(ToolError) as missing:
        controller.bind_task_placeholders(project_id, "w1", {"{{RECEIPT}}": "x"})
    assert missing.value.code == "invalid_task_state"

    task_state.set_status("v1", "pending")
    task_state.set_status("extra", "pending")
    store.save_task_state(project_id, "mission-001", task_state)
    with pytest.raises(ToolError) as extra:
        controller.bind_task_placeholders(project_id, "w1", {"{{RECEIPT}}": "x"})
    assert extra.value.code == "invalid_task_state"
    assert not _has_audit(controller, project_id)


def test_advance_rejects_marker_with_old_task_list_before_sync_or_dispatch(
    config: HarnessConfig, workspace: Path, monkeypatch
) -> None:
    dispatches: list[str] = []

    def responder(request):
        dispatches.append(request.task.id)
        return WorkHandoff(node_id=request.task.id, done=True, report="unexpected")

    controller = ProjectController(
        config,
        MockDispatcher(responder),
        MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
    )
    project_id = _seed_project(controller, workspace)
    original = controller.store.load_task_list(project_id, "mission-001")
    controller.bind_task_placeholders(project_id, "w1", {"{{RECEIPT}}": "bound"})
    controller.store.save_task_list(project_id, "mission-001", original)
    monkeypatch.setattr(
        controller.store,
        "sync_workspace_skill_surfaces",
        lambda project: pytest.fail("workspace sync must not run"),
    )

    with pytest.raises(ToolError) as exc:
        controller.advance_project(project_id)

    assert exc.value.code == "task_binding_digest_mismatch"
    assert exc.value.message == "task binding audit does not match current task list"
    assert dispatches == []


def test_advance_rejects_audit_with_task_state_or_task_list_inconsistency(
    config: HarnessConfig, workspace: Path, monkeypatch
) -> None:
    dispatches: list[str] = []
    controller = ProjectController(
        config,
        MockDispatcher(
            lambda request: dispatches.append(request.task.id)
            or WorkHandoff(node_id=request.task.id, done=True, report="unexpected")
        ),
        MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
    )
    project_id = _seed_project(controller, workspace)
    controller.bind_task_placeholders(project_id, "w1", {"{{RECEIPT}}": "bound"})
    path = _audit_path(controller, project_id)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["tasks"][0]["id"] = "renamed-before-attempt"
    path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(
        controller.store,
        "sync_workspace_skill_surfaces",
        lambda project: pytest.fail("workspace sync must not run"),
    )

    with pytest.raises(ToolError) as exc:
        controller.advance_project(project_id)

    assert exc.value.code == "invalid_task_state"
    assert dispatches == []

    path.write_text(json.dumps(raw), encoding="utf-8")
    task_state_path = controller.store.mission_runtime_dir(project_id, "mission-001") / "task-state.json"
    task_state_path.unlink()
    with pytest.raises(ToolError) as missing_state:
        controller.advance_project(project_id)
    assert missing_state.value.code == "invalid_task_state"


def test_advance_rejects_corrupt_binding_audit_before_sync_or_dispatch(
    config: HarnessConfig, workspace: Path, monkeypatch
) -> None:
    dispatches: list[str] = []
    controller = ProjectController(
        config,
        MockDispatcher(
            lambda request: dispatches.append(request.task.id)
            or WorkHandoff(node_id=request.task.id, done=True, report="unexpected")
        ),
        MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
    )
    project_id = _seed_project(controller, workspace)
    _audit_path(controller, project_id).write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(
        controller.store,
        "sync_workspace_skill_surfaces",
        lambda project: pytest.fail("workspace sync must not run"),
    )

    with pytest.raises(ToolError) as exc:
        controller.advance_project(project_id)

    assert exc.value.code == "invalid_task_binding_audit"
    assert exc.value.message == "task binding audit is invalid"
    assert dispatches == []


def _bind_result(controller: ProjectController, project_id: str) -> str:
    try:
        controller.bind_task_placeholders(project_id, "w1", {"{{RECEIPT}}": "winner"})
    except ToolError as exc:
        return exc.code
    return "success"


def test_concurrent_binding_has_one_exclusive_winner(
    config: HarnessConfig, workspace: Path
) -> None:
    seed = _controller(config)
    project_id = _seed_project(seed, workspace)
    controllers = [_controller(config), _controller(config)]

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(lambda controller: _bind_result(controller, project_id), controllers)
        )

    assert sorted(outcomes) == ["success", "task_binding_already_applied"]
    audit = json.loads(_audit_path(seed, project_id).read_text(encoding="utf-8"))[
        "_binding_audit"
    ]
    current = seed.store.load_task_list(project_id, "mission-001")
    assert audit["after_task_list_sha256"] == _task_list_digest(current)


def test_binding_audit_survives_failed_task_patch_recovery(
    config: HarnessConfig, workspace: Path
) -> None:
    def responder(request):
        if request.task.type == "work" and request.task.id == "w1":
            return WorkHandoff(node_id="w1", done=False, report="blocked")
        if request.task.type == "validate":
            return ValidateHandoff(
                node_id=request.task.id,
                done=True,
                report="audited",
                items=[ValidationItem(item_id="VAL-001", passed=True)],
                passed=True,
            )
        return WorkHandoff(node_id=request.task.id, done=True, report="ok")

    controller = ProjectController(
        config,
        MockDispatcher(responder),
        MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
    )
    project_id = _seed_project(controller, workspace)
    controller.bind_task_placeholders(project_id, "w1", {"{{RECEIPT}}": "bound"})
    audit_before = controller.store.load_task_binding_audit(project_id, "mission-001")
    controller.advance_project(project_id)
    attention = controller.store.load_attention(project_id)
    assert attention and attention[0].kind == "node_failed"

    patch = TaskListPatch(
        add=[
            _task(
                "w2",
                "work",
                ["VAL-001"],
                body="recovered",
                skill="worker",
            )
        ],
        supersede={"w1": "w2"},
    )
    controller.decide_attention(
        project_id,
        [Decision(item_id=attention[0].id, action="patch", patch=patch)],
    )
    controller.advance_project(project_id, max_steps=1)

    assert controller.store.load_task_binding_audit(project_id, "mission-001") == audit_before


def test_bind_task_placeholders_revalidates_complete_task_list_before_write(
    config: HarnessConfig, workspace: Path
) -> None:
    controller = _controller(config)
    project_id = _seed_project(controller, workspace)
    store = controller.store
    current = store.load_task_list(project_id, "mission-001")
    invalid = TaskList(
        tasks=[
            *current.tasks,
            _task(
                "w2",
                "work",
                ["VAL-001"],
                body="duplicate owner",
                skill="worker",
            ),
        ]
    )
    store.save_task_list(project_id, "mission-001", invalid)
    task_state = store.load_task_state(project_id, "mission-001")
    task_state.set_status("w2", "pending")
    store.save_task_state(project_id, "mission-001", task_state)

    with pytest.raises(ToolError) as exc:
        controller.bind_task_placeholders(project_id, "w1", {"{{RECEIPT}}": "x"})

    assert exc.value.code == "invalid_task_list"
    assert any(
        detail.code == "over_covered_assertion" for detail in (exc.value.details or [])
    )
    assert store.load_task_list(project_id, "mission-001") == invalid
    assert not _has_audit(controller, project_id)


def test_bind_task_placeholders_rejects_overlapping_occurrences(
    config: HarnessConfig, workspace: Path
) -> None:
    controller = _controller(config)
    project_id = _seed_project(controller, workspace, task_body="{{TOKEN}}")

    with pytest.raises(ToolError) as exc:
        controller.bind_task_placeholders(
            project_id,
            "w1",
            {"{{TOKEN}}": "one", "{{TOKEN": "two"},
        )

    assert exc.value.code == "ambiguous_placeholder"
    assert exc.value.message == "placeholder occurrences overlap"
    assert not _has_audit(controller, project_id)


def test_binding_does_not_change_project_state(
    config: HarnessConfig, workspace: Path
) -> None:
    controller = _controller(config)
    project_id = _seed_project(controller, workspace)
    controller.bind_task_placeholders(project_id, "w1", {"{{RECEIPT}}": "x"})

    state = controller.store.load_state(project_id)
    assert isinstance(state, MissionRunning)
    assert state.mission_id == "mission-001"


class _ProcessBodyDispatcher:
    def __init__(self, queue) -> None:
        self.queue = queue

    def dispatch(self, request):
        self.queue.put(("body", request.task.body))
        return WorkHandoff(node_id=request.task.id, done=True, report="ok")

    def dispatch_batch(self, requests):
        return [self.dispatch(request) for request in requests]


def _mp_bind_worker(config, project_id: str, start, queue) -> None:
    controller = _controller(config)
    start.wait()
    try:
        controller.bind_task_placeholders(project_id, "w1", {"{{RECEIPT}}": "winner"})
    except ToolError as exc:
        queue.put(("result", exc.code))
    else:
        queue.put(("result", "success"))


def _mp_bind_holding_lock_worker(config, project_id: str, locked, start, queue) -> None:
    controller = _controller(config)
    try:
        with controller.store.project_lock(project_id):
            locked.set()
            start.wait()
            controller._bind_task_placeholders(
                project_id, "w1", {"{{RECEIPT}}": "bound"}
            )
        queue.put(("bind", "success"))
    except ToolError as exc:
        queue.put(("bind", exc.code))


def _mp_advance_worker(config, project_id: str, start, queue) -> None:
    controller = ProjectController(
        config,
        _ProcessBodyDispatcher(queue),
        MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
    )
    start.wait()
    try:
        controller.advance_project(project_id, max_steps=1)
    except ToolError as exc:
        queue.put(("advance", exc.code))
    else:
        queue.put(("advance", "success"))


def _mp_context():
    methods = mp.get_all_start_methods()
    return mp.get_context("fork" if "fork" in methods else "spawn")


def test_multiprocess_binders_have_one_winner(config: HarnessConfig, workspace: Path) -> None:
    seed = _controller(config)
    project_id = _seed_project(seed, workspace)
    ctx = _mp_context()
    start = ctx.Event()
    queue = ctx.Queue()
    processes = [
        ctx.Process(target=_mp_bind_worker, args=(config, project_id, start, queue))
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    outcomes = [queue.get(timeout=5)[1] for _ in processes]
    assert sorted(outcomes) == ["success", "task_binding_already_applied"]
    audit = seed.store.load_task_binding_audit(project_id, "mission-001")
    assert audit is not None
    assert audit.after_task_list_sha256 == _task_list_digest(
        seed.store.load_task_list(project_id, "mission-001")
    )


def test_multiprocess_bind_holds_lock_before_advance(
    config: HarnessConfig, workspace: Path
) -> None:
    seed = _controller(config)
    project_id = _seed_project(seed, workspace)
    ctx = _mp_context()
    start = ctx.Event()
    locked = ctx.Event()
    queue = ctx.Queue()
    binder = ctx.Process(
        target=_mp_bind_holding_lock_worker,
        args=(config, project_id, locked, start, queue),
    )
    advance = ctx.Process(
        target=_mp_advance_worker,
        args=(config, project_id, start, queue),
    )
    binder.start()
    advance.start()
    assert locked.wait(timeout=10)
    start.set()
    binder.join(timeout=15)
    advance.join(timeout=15)
    assert binder.exitcode == 0
    assert advance.exitcode == 0

    messages = [queue.get(timeout=5) for _ in range(2)]
    assert ("bind", "success") in messages
    bodies = [value for kind, value in messages if kind == "body"]
    assert bodies == ["launch=bound path={{PATH}}"]
