"""v5 MCP server. 3 modes: orchestrator / worker / terminal-reviewer.

See docs/v5/08-mcp-surface.md. Tool-surface isolation is structural:
each mode registers a disjoint tool set on its own MCP server.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from pydantic import Field

from .config import HarnessConfig
from .controller import ProjectController, ToolError
from .dispatcher import NodeDispatcher, TerminalReviewer
from .models import (
    Decision,
    TaskList,
    TerminalReviewHandoff,
    ValidateHandoff,
    ValidationItem,
    WorkHandoff,
)
from .storage import atomic_write_json

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_orchestrator_server(
    config: HarnessConfig,
    controller: ProjectController | None = None,
) -> FastMCP:
    """7 orchestrator tools, registered on a stdio MCP server."""
    if controller is None:
        from .dispatcher import MockDispatcher, MockTerminalReviewer

        controller = ProjectController(
            config,
            MockDispatcher(
                lambda r: WorkHandoff(node_id=r.task.id, done=False, report="no ACP wired")
            ),
            MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
        )

    mcp = FastMCP(
        name="zenith",
        instructions=(
            "Mission orchestration harness. Mode: orchestrator. "
            "7 tools: start_project, submit_plan, advance_project, "
            "end_mission, decide_attention, inspect_project, abort_project. "
            "Lifecycle: plan with submit_plan, run with advance_project, "
            "request closure with end_mission, resolve attention with decide_attention, "
            "then call advance_project again."
        ),
    )
    _register_orchestrator_tools(mcp, controller)
    return mcp


def create_worker_server() -> FastMCP:
    """1 worker tool. Configured at runtime via env: ZENITH_NODE_TYPE,
    ZENITH_NODE_ID, ZENITH_HANDOFF_PATH.
    """
    mcp = FastMCP(
        name="zenith-worker",
        instructions=(
            "Worker MCP server. Mode: worker. 1 tool: end_node. Call exactly once before exiting."
        ),
    )
    _register_worker_tools(mcp)
    return mcp


def create_terminal_reviewer_server() -> FastMCP:
    """1 reviewer tool. Configured via env: ZENITH_TERMINAL_REVIEW_PATH."""
    mcp = FastMCP(
        name="zenith-terminal-reviewer",
        instructions=(
            "Runtime closure-check MCP server. 1 tool: submit_terminal_review. "
            "Call exactly once with the structured gap list."
        ),
    )
    _register_terminal_reviewer_tools(mcp)
    return mcp


# ---------------------------------------------------------------------------
# Orchestrator tools
# ---------------------------------------------------------------------------


def _register_orchestrator_tools(mcp: FastMCP, controller: ProjectController) -> None:
    # Per-project lock around mutating controller calls. The thread hop in each
    # tool prevents event-loop blocking, but two same-project tool calls could
    # otherwise race on disk state (attention, attempts, task-state, tasks).
    # docs/v5/07-runtime-architecture.md §9 declares concurrent same-project
    # operations undefined behavior; this lock serializes them defensively
    # without requiring host coordination. `inspect_project` is read-only and
    # stays uncontended.
    project_locks: dict[str, asyncio.Lock] = {}
    locks_guard = asyncio.Lock()

    async def _project_lock(project_id: str) -> asyncio.Lock:
        async with locks_guard:
            lock = project_locks.get(project_id)
            if lock is None:
                lock = asyncio.Lock()
                project_locks[project_id] = lock
            return lock

    @mcp.tool(
        name="start_project",
        description=(
            "Create a new long-running project rooted at the workspace. "
            "Use when the user describes a goal that needs planning and decomposition. "
            "Writes brief.md, creates harness state, returns the envelope with "
            "state=mission_planning."
        ),
    )
    async def start_project(
        brief: Annotated[str, Field(description="The user's ask in prose; goes to brief.md")],
        workspace_dir: Annotated[str, Field(description="Absolute path to the user's workspace.")],
    ) -> dict[str, Any]:
        # No per-project lock: project_id does not exist until the call returns.
        try:
            return _to_payload(
                await asyncio.to_thread(controller.start_project, brief, workspace_dir)
            )
        except ToolError as exc:
            return _to_payload(exc)

    @mcp.tool(
        name="submit_plan",
        description=(
            "Submit the current mission's contract-backed task list. Before calling, "
            "write every targeted contract/<id>.md file under the mission contract "
            "directory. Runtime validates a non-empty contract, task shape, "
            "depends_on resolution, acyclicity, coverage (each assertion has exactly "
            "one non-superseded work task). On success state becomes "
            "mission_running; call advance_project to dispatch work."
        ),
    )
    async def submit_plan(
        project_id: Annotated[str, Field(description="Project id from start_project.")],
        task_list: Annotated[
            TaskList,
            Field(description=("Mission task list (tasks: list[Task] with depends_on).")),
        ],
    ) -> dict[str, Any]:
        async with await _project_lock(project_id):
            try:
                return _to_payload(
                    await asyncio.to_thread(controller.submit_plan, project_id, task_list)
                )
            except ToolError as exc:
                return _to_payload(exc)

    @mcp.tool(
        name="advance_project",
        description=(
            "Drive the runtime forward. BLOCKING — may run for many minutes while "
            "workers dispatch according to runtime scheduling. "
            "Call whenever state is mission_running. "
            "Returns when attention is needed, no runnable task work remains, or "
            "`max_steps` exhausts. It does not request mission closure; call "
            "end_mission when you intend to close after task work is quiescent. "
            "If it returns still mission_running with runnable work, call it again."
        ),
    )
    async def advance_project(
        project_id: Annotated[str, Field(description="Project id.")],
        max_steps: Annotated[
            int | None, Field(default=None, description="Optional cap on step() calls.")
        ] = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        async with await _project_lock(project_id):
            try:
                return _to_payload(
                    await asyncio.to_thread(controller.advance_project, project_id, max_steps)
                )
            except ToolError as exc:
                return _to_payload(exc)

    @mcp.tool(
        name="end_mission",
        description=(
            "Request runtime mission closure. Call only when state is mission_running "
            "and you believe task work is complete/quiescent. This tool does not "
            "dispatch workers. If work or gates are still runnable, returns "
            "mission_not_ready_to_close; call advance_project first. If closure "
            "passes, state becomes done. If closure finds gaps, state becomes "
            "attention_needed with a closure report."
        ),
    )
    async def end_mission(
        project_id: Annotated[str, Field(description="Project id.")],
        deliverable_roots: Annotated[
            list[str] | None,
            Field(
                default=None,
                description=(
                    "Exact existing product/report files or directories the independent "
                    "terminal reviewer may inspect in addition to the normal workspace. "
                    "Paths are security-checked and persisted for this mission."
                ),
            ),
        ] = None,
        force_terminal_review: Annotated[
            bool,
            Field(
                default=False,
                description=(
                    "Explicitly rerun despite unchanged observable inputs. Use only for a "
                    "transient reviewer failure; unchanged retries are blocked by default."
                ),
            ),
        ] = False,
    ) -> dict[str, Any]:
        async with await _project_lock(project_id):
            try:
                return _to_payload(
                    await asyncio.to_thread(
                        controller.end_mission,
                        project_id,
                        deliverable_roots,
                        force_terminal_review=force_terminal_review,
                    )
                )
            except ToolError as exc:
                return _to_payload(exc)

    @mcp.tool(
        name="decide_attention",
        description=(
            "Resolve all open AttentionItem(s). Every open item must be covered by "
            "exactly one Decision. Use retry only for transient node_failed attempts; "
            "use patch for changed work, missing assertions, failed validation, "
            "over-broad scope, or task-list adaptation. Patches must pass structural "
            "validation. After a valid decide, state usually returns to "
            "mission_running; call advance_project to dispatch more work."
        ),
    )
    async def decide_attention(
        project_id: Annotated[str, Field(description="Project id.")],
        decisions: Annotated[
            list[Decision], Field(description="One Decision per open attention item.")
        ],
    ) -> dict[str, Any]:
        async with await _project_lock(project_id):
            try:
                return _to_payload(
                    await asyncio.to_thread(controller.decide_attention, project_id, decisions)
                )
            except ToolError as exc:
                return _to_payload(exc)

    @mcp.tool(
        name="inspect_project",
        description=(
            "Pure read of current state, full task-list view, and open attention. "
            "No state change. Use when waking with no specific tool call in mind."
        ),
    )
    async def inspect_project(
        project_id: Annotated[str, Field(description="Project id.")],
    ) -> dict[str, Any]:
        try:
            return _to_payload(await asyncio.to_thread(controller.inspect_project, project_id))
        except ToolError as exc:
            return _to_payload(exc)

    @mcp.tool(
        name="abort_project",
        description=(
            "Cancel the current mission and project. Marks state=Aborted with the "
            "supplied reason. Preserves tasks.json + attempts/ + decisions/ for forensics."
        ),
    )
    async def abort_project(
        project_id: Annotated[str, Field(description="Project id.")],
        reason: Annotated[str, Field(description="Why we are aborting.")],
    ) -> dict[str, Any]:
        async with await _project_lock(project_id):
            try:
                return _to_payload(
                    await asyncio.to_thread(controller.abort_project, project_id, reason)
                )
            except ToolError as exc:
                return _to_payload(exc)


# ---------------------------------------------------------------------------
# Worker tool
# ---------------------------------------------------------------------------


def _register_worker_tools(mcp: FastMCP) -> None:
    @mcp.tool(
        name="end_node",
        description=(
            "Assigned-session runtime handoff. Report completion for the assigned "
            "work or validation task. Call exactly "
            "once before exiting. After this call, do not invoke any other tools — the "
            "session is finished. For validation tasks, include `items` (one per "
            "assigned contract target) and the aggregate `passed`."
        ),
    )
    async def end_node(
        done: Annotated[
            bool,
            Field(description="True if the assigned work or validation audit completed."),
        ],
        report: Annotated[
            str,
            Field(
                description="Free-form handoff report. Severity tags are authoring discipline, not runtime triggers."
            ),
        ],
        request_attention: Annotated[
            bool,
            Field(
                default=False,
                description="Set True to return this completed task's raw report to the orchestrator before the task list continues.",
            ),
        ] = False,
        items: Annotated[
            list[ValidationItem] | None,
            Field(
                default=None,
                description="Validation task only: one entry per assigned contract target with per-item passed verdict.",
            ),
        ] = None,
        passed: Annotated[
            bool | None,
            Field(
                default=None,
                description="Validation task only: aggregate True iff every items[].passed.",
            ),
        ] = None,
    ) -> dict[str, Any]:
        node_type = os.environ.get("ZENITH_NODE_TYPE", "work")
        handoff_path = os.environ.get("ZENITH_HANDOFF_PATH")
        if not handoff_path:
            raise RuntimeError("ZENITH_HANDOFF_PATH not set in worker env")
        node_id = os.environ.get("ZENITH_NODE_ID")
        if not node_id:
            raise RuntimeError("ZENITH_NODE_ID not set in worker env")

        handoff: WorkHandoff | ValidateHandoff
        if node_type == "validate":
            handoff = ValidateHandoff(
                node_id=node_id,
                done=done,
                report=report,
                items=items or [],
                passed=bool(passed) if passed is not None else all(i.passed for i in (items or [])),
                request_attention=request_attention,
            )
        else:
            handoff = WorkHandoff(
                node_id=node_id,
                done=done,
                report=report,
                request_attention=request_attention,
            )
        atomic_write_json(handoff_path, handoff.model_dump(mode="json"))
        return {
            "recorded": True,
            "message": "Session complete, your job is done now; do not call further tools and just end your job now.",
        }


# ---------------------------------------------------------------------------
# Terminal-reviewer tool
# ---------------------------------------------------------------------------


def _register_terminal_reviewer_tools(mcp: FastMCP) -> None:
    @mcp.tool(
        name="submit_terminal_review",
        description=(
            "Runtime-closure-check-only. Submit the mission closure result. "
            "`done=true` means clean enough to close; `done=false` returns the raw "
            "closure report to the orchestrator. Call exactly once."
        ),
    )
    async def submit_terminal_review(
        done: Annotated[
            bool,
            Field(description="True only when the mission should close as done."),
        ],
        report: Annotated[
            str,
            Field(description="Raw closure report for the orchestrator."),
        ] = "",
    ) -> dict[str, Any]:
        path = os.environ.get("ZENITH_TERMINAL_REVIEW_PATH")
        if not path:
            raise RuntimeError("ZENITH_TERMINAL_REVIEW_PATH not set in terminal-reviewer env")
        review = TerminalReviewHandoff(done=done, report=report)
        atomic_write_json(path, review.model_dump(mode="json"))
        return {
            "recorded": True,
            "message": "Terminal review submitted; do not call further tools.",
        }


# ---------------------------------------------------------------------------
# Envelope payload helper
# ---------------------------------------------------------------------------


def _to_payload(env_or_err) -> dict[str, Any]:
    if isinstance(env_or_err, ToolError):
        return {
            "error": env_or_err.code,
            "message": env_or_err.message,
            "details": [str(d) for d in (env_or_err.details or [])],
        }
    return env_or_err.model_dump(mode="json", by_alias=True)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Zenith MCP Server (v5)")
    parser.add_argument(
        "--mode",
        choices=["orchestrator", "worker", "terminal-reviewer"],
        default="orchestrator",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)  # 0 → ephemeral
    args = parser.parse_args()

    if args.mode == "orchestrator":
        config = HarnessConfig.discover()
        # Production: wire the ACP dispatcher from acp_runner.
        dispatcher: NodeDispatcher
        reviewer: TerminalReviewer
        try:
            from .acp_runner import ACPNodeDispatcher, ACPTerminalReviewer  # noqa: PLC0415

            dispatcher = ACPNodeDispatcher(config)
            reviewer = ACPTerminalReviewer(config)
        except Exception as exc:  # pragma: no cover — diagnostic
            logger.warning("Falling back to no-op dispatcher: %s", exc)
            from .dispatcher import MockDispatcher, MockTerminalReviewer  # noqa: PLC0415

            dispatcher = MockDispatcher(
                lambda r: WorkHandoff(
                    node_id=r.task.id, done=False, report="no ACP runtime available"
                )
            )
            reviewer = MockTerminalReviewer(TerminalReviewHandoff(done=True, report=""))
        controller = ProjectController(config, dispatcher, reviewer)
        server = create_orchestrator_server(config, controller)
    elif args.mode == "worker":
        server = create_worker_server()
    else:
        server = create_terminal_reviewer_server()

    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(transport=args.transport, host=args.host, port=args.port)


__all__ = [
    "create_orchestrator_server",
    "create_worker_server",
    "create_terminal_reviewer_server",
    "main",
]
