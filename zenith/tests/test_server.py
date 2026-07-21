"""MCP server tests — tool surface per mode + in-process integration."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from zenith_harness.config import HarnessConfig
from zenith_harness.controller import ProjectController
from zenith_harness.dispatcher import (
    DispatchRequest,
    MockDispatcher,
    MockTerminalReviewer,
)
from zenith_harness.models import (
    TerminalReviewHandoff,
    ValidateHandoff,
    ValidationItem,
    WorkHandoff,
)
from zenith_harness.server import (
    create_orchestrator_server,
    create_terminal_reviewer_server,
    create_worker_server,
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


async def _tool_names(server) -> set[str]:
    return {t.name for t in await server.list_tools()}


# ---------------------------------------------------------------------------
# Tool surface per mode (structural isolation)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_tools_registered(config: HarnessConfig) -> None:
    server = create_orchestrator_server(config)
    names = await _tool_names(server)
    assert names == {
        "start_project",
        "submit_plan",
        "advance_project",
        "end_mission",
        "decide_attention",
        "inspect_project",
        "abort_project",
        "release_project",
        "recover_workspace_lease",
    }


@pytest.mark.asyncio
async def test_worker_tool_isolated() -> None:
    server = create_worker_server()
    assert await _tool_names(server) == {"end_node"}


@pytest.mark.asyncio
async def test_terminal_reviewer_tool_isolated() -> None:
    server = create_terminal_reviewer_server()
    assert await _tool_names(server) == {"submit_terminal_review"}


# ---------------------------------------------------------------------------
# end_node writes to ZENITH_HANDOFF_PATH
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_node_writes_handoff_file(tmp_path: Path, monkeypatch) -> None:
    handoff_path = tmp_path / "handoff.json"
    monkeypatch.setenv("ZENITH_HANDOFF_PATH", str(handoff_path))
    monkeypatch.setenv("ZENITH_NODE_TYPE", "work")
    monkeypatch.setenv("ZENITH_NODE_ID", "w1")
    server = create_worker_server()
    await server.call_tool(
        "end_node",
        {"done": True, "report": "ok"},
    )
    assert handoff_path.exists()
    data = json.loads(handoff_path.read_text())
    assert data == {
        "node_id": "w1",
        "done": True,
        "report": "ok",
        "request_attention": False,
    }


@pytest.mark.asyncio
async def test_end_node_validate_writes_items(tmp_path: Path, monkeypatch) -> None:
    handoff_path = tmp_path / "handoff.json"
    monkeypatch.setenv("ZENITH_HANDOFF_PATH", str(handoff_path))
    monkeypatch.setenv("ZENITH_NODE_TYPE", "validate")
    monkeypatch.setenv("ZENITH_NODE_ID", "v1")
    server = create_worker_server()
    await server.call_tool(
        "end_node",
        {
            "done": True,
            "report": "audited",
            "items": [{"item_id": "VAL-001", "passed": True}],
            "passed": True,
        },
    )
    data = json.loads(handoff_path.read_text())
    assert data["items"][0]["item_id"] == "VAL-001"
    assert data["passed"] is True


@pytest.mark.asyncio
async def test_end_node_requires_env_node_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ZENITH_HANDOFF_PATH", str(tmp_path / "h.json"))
    monkeypatch.setenv("ZENITH_NODE_TYPE", "work")
    monkeypatch.delenv("ZENITH_NODE_ID", raising=False)
    server = create_worker_server()
    with pytest.raises(Exception):
        await server.call_tool(
            "end_node",
            {"done": True, "report": ""},
        )


@pytest.mark.asyncio
async def test_end_node_idempotent_overwrite(tmp_path: Path, monkeypatch) -> None:
    handoff_path = tmp_path / "handoff.json"
    monkeypatch.setenv("ZENITH_HANDOFF_PATH", str(handoff_path))
    monkeypatch.setenv("ZENITH_NODE_TYPE", "work")
    monkeypatch.setenv("ZENITH_NODE_ID", "w1")
    server = create_worker_server()
    await server.call_tool(
        "end_node", {"done": True, "report": "first"}
    )
    await server.call_tool(
        "end_node", {"done": True, "report": "second"}
    )
    assert json.loads(handoff_path.read_text())["report"] == "second"


@pytest.mark.asyncio
async def test_submit_terminal_review_writes_file(tmp_path: Path, monkeypatch) -> None:
    review_path = tmp_path / "terminal-review.json"
    monkeypatch.setenv("ZENITH_TERMINAL_REVIEW_PATH", str(review_path))
    server = create_terminal_reviewer_server()
    await server.call_tool(
        "submit_terminal_review", {"done": True, "report": "all clean"}
    )
    data = json.loads(review_path.read_text())
    assert data == {"done": True, "report": "all clean"}


# ---------------------------------------------------------------------------
# Integration: orchestrator tools in-process
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_end_to_end_in_process(
    config: HarnessConfig, workspace: Path
) -> None:
    def responder(req):
        if req.node.type == "work":
            return WorkHandoff(node_id=req.node.id, done=True, report="ok")
        return ValidateHandoff(
            node_id=req.node.id,
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
    server = create_orchestrator_server(config, controller)

    await server.call_tool(
        "start_project",
        {"brief": "Ship it.", "workspace_dir": str(workspace)},
    )
    pid = ProjectStore(config).list_projects()[0].id
    contract_dir = controller.store.ensure_contract_dir(pid, "mission-001")
    (contract_dir / "VAL-001.md").write_text("# VAL-001\n")
    task_list_dict = {
        "tasks": [
            {"id": "w1", "type": "work", "body": "do", "targets": ["VAL-001"], "skill": "s", "depends_on": []},
            {"id": "v1", "type": "validate", "body": "audit", "targets": ["VAL-001"], "skill": "aud", "depends_on": ["w1"]},
            {"id": "g1", "type": "gate", "body": "", "targets": ["VAL-001"], "skill": None, "depends_on": ["v1"]},
        ],
    }
    await server.call_tool("submit_plan", {"project_id": pid, "task_list": task_list_dict})
    await server.call_tool("advance_project", {"project_id": pid})
    items = controller.store.load_attention(pid)
    assert len(items) == 1
    await server.call_tool(
        "decide_attention",
        {
            "project_id": pid,
            "decisions": [{"item_id": items[0].id, "action": "continue"}],
        },
    )
    await server.call_tool("advance_project", {"project_id": pid})
    await server.call_tool("inspect_project", {"project_id": pid})


@pytest.mark.asyncio
async def test_second_server_cannot_mutate_owned_workspace(
    config: HarnessConfig, workspace: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ZENITH_CONTROLLER_ID", "owner-a")
    first = create_orchestrator_server(config)
    monkeypatch.setenv("ZENITH_CONTROLLER_ID", "owner-b")
    second = create_orchestrator_server(config)
    started = await first.call_tool(
        "start_project", {"brief": "Owned.", "workspace_dir": str(workspace)}
    )
    pid = started.structured_content["projectId"]

    blocked = await second.call_tool(
        "abort_project", {"project_id": pid, "reason": "should not mutate"}
    )
    assert blocked.structured_content["error"] == "workspace_owned"
    assert "owner=" in blocked.structured_content["message"]


@pytest.mark.asyncio
async def test_second_server_can_inspect_owned_workspace(
    config: HarnessConfig, workspace: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ZENITH_CONTROLLER_ID", "owner-a")
    first = create_orchestrator_server(config)
    monkeypatch.setenv("ZENITH_CONTROLLER_ID", "owner-b")
    second = create_orchestrator_server(config)
    started = await first.call_tool(
        "start_project", {"brief": "Owned.", "workspace_dir": str(workspace)}
    )
    pid = started.structured_content["projectId"]

    inspected = await second.call_tool("inspect_project", {"project_id": pid})
    assert inspected.structured_content["projectId"] == pid
    assert "error" not in inspected.structured_content


@pytest.mark.asyncio
async def test_explicit_release_allows_controller_handoff(
    config: HarnessConfig, workspace: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ZENITH_CONTROLLER_ID", "owner-a")
    first = create_orchestrator_server(config)
    monkeypatch.setenv("ZENITH_CONTROLLER_ID", "owner-b")
    second = create_orchestrator_server(config)
    started = await first.call_tool(
        "start_project", {"brief": "Owned.", "workspace_dir": str(workspace)}
    )
    pid = started.structured_content["projectId"]

    released = await first.call_tool("release_project", {"project_id": pid})
    assert released.structured_content["released"] is True
    taken_over = await second.call_tool(
        "abort_project", {"project_id": pid, "reason": "intentional handoff"}
    )
    assert taken_over.structured_content["state"]["state"] == "aborted"


@pytest.mark.asyncio
async def test_non_owner_cannot_release_project(
    config: HarnessConfig, workspace: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ZENITH_CONTROLLER_ID", "owner-a")
    first = create_orchestrator_server(config)
    monkeypatch.setenv("ZENITH_CONTROLLER_ID", "owner-b")
    second = create_orchestrator_server(config)
    started = await first.call_tool(
        "start_project", {"brief": "Owned.", "workspace_dir": str(workspace)}
    )
    pid = started.structured_content["projectId"]

    blocked = await second.call_tool("release_project", {"project_id": pid})
    assert blocked.structured_content["error"] == "workspace_owned"


@pytest.mark.asyncio
async def test_owner_cannot_release_project_while_task_is_running(
    config: HarnessConfig, workspace: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ZENITH_CONTROLLER_ID", "owner-a")
    server = create_orchestrator_server(config)
    started = await server.call_tool(
        "start_project", {"brief": "Owned.", "workspace_dir": str(workspace)}
    )
    pid = started.structured_content["projectId"]
    store = ProjectStore(config)
    contract_dir = store.ensure_contract_dir(pid, "mission-001")
    (contract_dir / "VAL-001.md").write_text("# VAL-001\n")
    await server.call_tool(
        "submit_plan",
        {
            "project_id": pid,
            "task_list": {
                "tasks": [
                    {
                        "id": "w1",
                        "type": "work",
                        "body": "do",
                        "targets": ["VAL-001"],
                        "skill": "s",
                        "depends_on": [],
                    }
                ]
            },
        },
    )
    task_state = store.load_task_state(pid, "mission-001")
    task_state.set_status("w1", "running")
    store.save_task_state(pid, "mission-001", task_state)

    blocked = await server.call_tool("release_project", {"project_id": pid})
    assert blocked.structured_content["error"] == "workspace_busy"
    assert "w1" in blocked.structured_content["message"]

    inspected = await server.call_tool("inspect_project", {"project_id": pid})
    assert inspected.structured_content["state"]["state"] == "mission_running"

    blocked_abort = await server.call_tool(
        "abort_project", {"project_id": pid, "reason": "must stay fenced"}
    )
    assert blocked_abort.structured_content["error"] == "workspace_busy"
    inspected = await server.call_tool("inspect_project", {"project_id": pid})
    assert inspected.structured_content["state"]["state"] == "mission_running"


@pytest.mark.asyncio
async def test_second_server_cannot_start_another_project_in_owned_workspace(
    config: HarnessConfig, workspace: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ZENITH_CONTROLLER_ID", "owner-a")
    first = create_orchestrator_server(config)
    monkeypatch.setenv("ZENITH_CONTROLLER_ID", "owner-b")
    second = create_orchestrator_server(config)
    await first.call_tool(
        "start_project", {"brief": "First.", "workspace_dir": str(workspace)}
    )

    blocked = await second.call_tool(
        "start_project", {"brief": "Second.", "workspace_dir": str(workspace)}
    )
    assert blocked.structured_content["error"] == "workspace_owned"
    assert len(ProjectStore(config).list_projects()) == 1


@pytest.mark.asyncio
async def test_missing_controller_identity_uses_unique_process_owners(
    config: HarnessConfig, workspace: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ZENITH_CONTROLLER_ID", "   ")
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    first = create_orchestrator_server(config)
    second = create_orchestrator_server(config)
    started = await first.call_tool(
        "start_project", {"brief": "Owned.", "workspace_dir": str(workspace)}
    )
    pid = started.structured_content["projectId"]

    blocked = await second.call_tool(
        "abort_project", {"project_id": pid, "reason": "must not share blank id"}
    )
    assert blocked.structured_content["error"] == "workspace_owned"


@pytest.mark.asyncio
async def test_invalid_controller_identity_returns_structured_error(
    config: HarnessConfig, workspace: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ZENITH_CONTROLLER_ID", "owner with spaces")
    server = create_orchestrator_server(config)

    started = await server.call_tool(
        "start_project", {"brief": "Owned.", "workspace_dir": str(workspace)}
    )

    assert started.structured_content["error"] == "invalid_owner"


@pytest.mark.asyncio
async def test_abort_releases_workspace_for_next_controller(
    config: HarnessConfig, workspace: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ZENITH_CONTROLLER_ID", "owner-a")
    first = create_orchestrator_server(config)
    started = await first.call_tool(
        "start_project", {"brief": "Owned.", "workspace_dir": str(workspace)}
    )
    pid = started.structured_content["projectId"]
    aborted = await first.call_tool(
        "abort_project", {"project_id": pid, "reason": "intentional"}
    )
    assert aborted.structured_content["state"]["state"] == "aborted"

    monkeypatch.setenv("ZENITH_CONTROLLER_ID", "owner-b")
    second = create_orchestrator_server(config)
    restarted = await second.call_tool(
        "start_project", {"brief": "Next.", "workspace_dir": str(workspace)}
    )
    assert "error" not in restarted.structured_content


@pytest.mark.asyncio
async def test_dead_orphan_lease_can_be_recovered_without_project_record(
    config: HarnessConfig, workspace: Path, monkeypatch
) -> None:
    store = ProjectStore(config)
    lease = store.claim_workspace_lease_for_workspace(
        workspace, "ghost-project", "dead-owner"
    )
    for name in ("claim.json", "owner.json"):
        path = lease.path.parent / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["pid"] = 999_999_999
        path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setenv("ZENITH_CONTROLLER_ID", "recovery-owner")
    server = create_orchestrator_server(config)
    recovered = await server.call_tool(
        "recover_workspace_lease",
        {
            "workspace_dir": str(workspace),
            "reason": "controller crashed before project creation",
        },
    )

    assert recovered.structured_content["recovered"] is True
    audit_path = config.harness_home / "leases" / "recovery-log.jsonl"
    audit = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[-1])
    assert audit["action"] == "dead_controller_recovery_completed"
    assert audit["project_id"] == "ghost-project"
    started = await server.call_tool(
        "start_project", {"brief": "Recovered.", "workspace_dir": str(workspace)}
    )
    assert "error" not in started.structured_content


@pytest.mark.asyncio
async def test_live_workspace_lease_cannot_be_recovered(
    config: HarnessConfig, workspace: Path, monkeypatch
) -> None:
    store = ProjectStore(config)
    store.claim_workspace_lease_for_workspace(workspace, "p1", "live-owner")
    monkeypatch.setenv("ZENITH_CONTROLLER_ID", "recovery-owner")
    server = create_orchestrator_server(config)

    recovered = await server.call_tool(
        "recover_workspace_lease",
        {"workspace_dir": str(workspace), "reason": "must remain fenced"},
    )

    assert recovered.structured_content["error"] == "workspace_recovery_blocked"
    assert "live workspace controller" in recovered.structured_content["message"]


@pytest.mark.asyncio
async def test_dead_controller_recovery_refuses_running_worker_records(
    config: HarnessConfig, workspace: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ZENITH_CONTROLLER_ID", "owner-a")
    server = create_orchestrator_server(config)
    started = await server.call_tool(
        "start_project", {"brief": "Owned.", "workspace_dir": str(workspace)}
    )
    pid = started.structured_content["projectId"]
    store = ProjectStore(config)
    contract_dir = store.ensure_contract_dir(pid, "mission-001")
    (contract_dir / "VAL-001.md").write_text("# VAL-001\n")
    await server.call_tool(
        "submit_plan",
        {
            "project_id": pid,
            "task_list": {
                "tasks": [
                    {
                        "id": "w1",
                        "type": "work",
                        "body": "do",
                        "targets": ["VAL-001"],
                        "skill": "s",
                        "depends_on": [],
                    }
                ]
            },
        },
    )
    task_state = store.load_task_state(pid, "mission-001")
    task_state.set_status("w1", "running")
    store.save_task_state(pid, "mission-001", task_state)
    lease_path = store.workspace_lease_path(pid)
    for name in ("claim.json", "owner.json"):
        path = lease_path.parent / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["pid"] = 999_999_999
        path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setenv("ZENITH_CONTROLLER_ID", "owner-b")
    recovery_server = create_orchestrator_server(config)
    recovered = await recovery_server.call_tool(
        "recover_workspace_lease",
        {"workspace_dir": str(workspace), "reason": "controller crashed"},
    )

    assert recovered.structured_content["error"] == "workspace_recovery_blocked"
    assert "running task records" in recovered.structured_content["message"]


# ---------------------------------------------------------------------------
# Regression: dispatcher that calls asyncio.run() must not crash the MCP
# event loop. Reproduces:
#   "asyncio.run() cannot be called from a running event loop"
# observed in the attempts/*.json report when a worker dispatch path
# inadvertently ran inside the FastMCP handler's loop.
# ---------------------------------------------------------------------------


class _AsyncioRunDispatcher:
    """Dispatcher whose dispatch() goes through asyncio.run(), mimicking
    ACPNodeDispatcher. If invoked from a running loop without thread
    isolation, raises the canonical RuntimeError.
    """

    def dispatch(self, request: DispatchRequest) -> WorkHandoff | ValidateHandoff:
        async def _do() -> WorkHandoff | ValidateHandoff:
            await asyncio.sleep(0)
            if request.task.type == "work":
                return WorkHandoff(node_id=request.task.id, done=True, report="ok")
            return ValidateHandoff(
                node_id=request.task.id,
                done=True,
                report="audited",
                items=[ValidationItem(item_id="VAL-001", passed=True)],
                passed=True,
            )

        return asyncio.run(_do())

    def dispatch_batch(
        self, requests: list[DispatchRequest]
    ) -> list[WorkHandoff | ValidateHandoff]:
        return [self.dispatch(r) for r in requests]


@pytest.mark.asyncio
async def test_advance_project_tolerates_asyncio_run_dispatcher(
    config: HarnessConfig, workspace: Path
) -> None:
    controller = ProjectController(
        config,
        _AsyncioRunDispatcher(),
        MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
    )
    server = create_orchestrator_server(config, controller)
    await server.call_tool(
        "start_project",
        {"brief": "Ship it.", "workspace_dir": str(workspace)},
    )
    pid = ProjectStore(config).list_projects()[0].id
    contract_dir = controller.store.ensure_contract_dir(pid, "mission-001")
    (contract_dir / "VAL-001.md").write_text("# VAL-001\n")
    task_list_dict = {
        "tasks": [
            {"id": "w1", "type": "work", "body": "do", "targets": ["VAL-001"], "skill": "s", "depends_on": []},
            {"id": "v1", "type": "validate", "body": "audit", "targets": ["VAL-001"], "skill": "aud", "depends_on": ["w1"]},
            {"id": "g1", "type": "gate", "body": "", "targets": ["VAL-001"], "skill": None, "depends_on": ["v1"]},
        ],
    }
    await server.call_tool("submit_plan", {"project_id": pid, "task_list": task_list_dict})
    # Before the fix this raised:
    #   RuntimeError: asyncio.run() cannot be called from a running event loop
    await server.call_tool("advance_project", {"project_id": pid})
    items = controller.store.load_attention(pid)
    assert len(items) == 1


def test_run_coro_blocking_works_inside_running_loop() -> None:
    """The dispatcher defense: if asyncio.run() is reached while a loop is
    already running, _run_coro_blocking falls back to a worker thread.
    """
    from zenith_harness.acp_runner import _run_coro_blocking

    async def _outer() -> int:
        async def _inner() -> int:
            await asyncio.sleep(0)
            return 42

        return _run_coro_blocking(_inner())

    assert asyncio.run(_outer()) == 42
