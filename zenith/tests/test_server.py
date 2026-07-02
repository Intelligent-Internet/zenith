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
            {"id": "w1", "type": "work", "body": "do", "targets": ["VAL-001"], "skill": "engineering-mission-playbook", "depends_on": []},
            {"id": "v1", "type": "validate", "body": "audit", "targets": ["VAL-001"], "skill": "scrutiny-validator", "depends_on": ["w1"]},
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
            {"id": "w1", "type": "work", "body": "do", "targets": ["VAL-001"], "skill": "engineering-mission-playbook", "depends_on": []},
            {"id": "v1", "type": "validate", "body": "audit", "targets": ["VAL-001"], "skill": "scrutiny-validator", "depends_on": ["w1"]},
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
