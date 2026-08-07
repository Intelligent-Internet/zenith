"""Terminal reviewer ambient-context isolation tests.

The terminal reviewer's system prompt declares the original user request
and the workspace as its only inputs and forbids reading provider skill
directories. These tests pin the runtime side of that contract: for the
claude provider, `session/new` must carry `_meta.claudeCode.options`
disabling filesystem setting sources and skill discovery, so the user's
global CLAUDE.md / settings.json / skills are not injected into the
reviewer's context by `claude-agent-acp` defaults.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from zenith_harness.acp_runner import (
    ACPNodeRunner,
    _terminal_reviewer_session_meta,
)
from zenith_harness.assets import AssetLoader
from zenith_harness.config import HarnessConfig
from zenith_harness.models import TerminalReviewHandoff
from zenith_harness.providers import PROVIDERS
from zenith_harness.storage import ProjectStore


# ---------------------------------------------------------------------------
# Unit: _terminal_reviewer_session_meta
# ---------------------------------------------------------------------------


def test_session_meta_claude_disables_setting_sources_and_skills():
    meta = _terminal_reviewer_session_meta(PROVIDERS["claude"])
    assert meta is not None
    options = meta["claudeCode"]["options"]
    assert options["settingSources"] == []
    assert options["skills"] == []


@pytest.mark.parametrize("provider_name", ["codex", "hermes"])
def test_session_meta_non_claude_is_none(provider_name: str):
    assert _terminal_reviewer_session_meta(PROVIDERS[provider_name]) is None


# ---------------------------------------------------------------------------
# Wiring: session/new carries the _meta through the real ACP client
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_acp_command() -> str:
    mock = Path(__file__).resolve().parent / "mock_acp_agent.py"
    return f"{sys.executable} {mock}"


@pytest.fixture
def config(harness_home: Path, mock_acp_command: str) -> HarnessConfig:
    bundled = Path(__file__).resolve().parents[1] / "src" / "zenith_harness" / "bundled"
    return HarnessConfig(
        bundled_dir=bundled,
        harness_home=harness_home,
        projects_dir=harness_home / "projects",
        orchestrator_provider_name="claude",
        worker_provider_name="claude",
        worker_acp_command=mock_acp_command,
        validator_provider_name=None,
        validator_acp_command=None,
        terminal_reviewer_provider_name=None,
        # Explicit: the resolution chain prefers the provider's default
        # command ("claude-agent-acp") over an inherited custom worker
        # command, so leaving this None would spawn the real adapter.
        terminal_reviewer_acp_command=mock_acp_command,
    )


def test_run_terminal_review_sends_isolation_meta(
    config: HarnessConfig, workspace: Path, tmp_path: Path
):
    """End-to-end via the mock agent: the reviewer session must be opened
    with settingSources/skills disabled, and the handoff must round-trip.
    """
    store = ProjectStore(config)
    store.create_project("brief", workspace, project_id="p1")
    spawn_ts = "2026-07-27T00-00-00Z"
    report_path = store.terminal_review_path("p1", "mission-001", spawn_ts)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    params_path = tmp_path / "session_params.json"

    os.environ["ZENITH_HANDOFF_PATH"] = str(report_path)
    os.environ["ZENITH_NODE_TYPE"] = "terminal_review"
    os.environ["MOCK_ACP_SESSION_PARAMS_PATH"] = str(params_path)
    try:
        runner = ACPNodeRunner(config=config, loader=AssetLoader(config))

        async def _no_op_server(*args, **kwargs):
            return await asyncio.create_subprocess_exec(
                "sleep", "30",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

        async def _ready_immediately(*args, **kwargs):
            return None

        runner._start_terminal_reviewer_mcp = _no_op_server  # type: ignore[method-assign]
        runner._wait_for_server_ready = _ready_immediately  # type: ignore[method-assign]

        handoff = asyncio.run(
            runner.run_terminal_review(
                project_id="p1",
                mission_id="mission-001",
                spawn_ts=spawn_ts,
                store=store,
            )
        )
    finally:
        for k in (
            "ZENITH_HANDOFF_PATH",
            "ZENITH_NODE_TYPE",
            "MOCK_ACP_SESSION_PARAMS_PATH",
        ):
            os.environ.pop(k, None)

    assert isinstance(handoff, TerminalReviewHandoff)
    assert handoff.done is True

    params = json.loads(params_path.read_text())
    options = params["_meta"]["claudeCode"]["options"]
    assert options["settingSources"] == []
    assert options["skills"] == []
