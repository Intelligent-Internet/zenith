"""ACP runner adaptation tests — direct-to-PROJECT handoff path discipline.

We don't run a real `claude-agent-acp` here; we use the bundled
`mock_acp_agent.py` to exercise the ACP client + the handoff polling
mechanic. The worker MCP server subprocess is bypassed: the mock agent
writes directly to ZENITH_HANDOFF_PATH itself.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from zenith_harness.acp_runner import (
    ACPNodeRunner,
    _acp_subprocess_env,
    _augment_acp_command,
)
from zenith_harness.providers import PROVIDERS
from zenith_harness.assets import AssetLoader
from zenith_harness.config import HarnessConfig
from zenith_harness.models import Task, WorkHandoff
from zenith_harness.storage import ProjectStore


@pytest.fixture
def mock_acp_command() -> str:
    """Wrap the mock agent script so it's invocable from a shell."""
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
        terminal_reviewer_acp_command=None,
    )


@pytest.fixture
def project_setup(config: HarnessConfig, workspace: Path):
    store = ProjectStore(config)
    store.create_project("brief", workspace, project_id="p1")
    contract_dir = store.ensure_contract_dir("p1", "mission-001")
    (contract_dir / "VAL-001.md").write_text("# VAL-001\n\nTest.\n")
    return store


# ---------------------------------------------------------------------------
# Mock-agent integration: the agent writes directly to ZENITH_HANDOFF_PATH
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not shutil.which("python3") and not Path(sys.executable).exists(),
    reason="Python interpreter unavailable",
)
def test_run_node_with_mock_agent(
    config: HarnessConfig, project_setup, workspace: Path
):
    """End-to-end via the mock agent (NO real worker MCP server subprocess —
    we point at a free port that nothing binds to and rely on the mock to
    write the handoff file itself).
    """
    store = project_setup
    task = Task(id="w1", type="work", body="do it", targets=["VAL-001"], skill="s")
    spawn_ts = "2026-05-17T00-00-00Z"
    handoff_path = store.attempt_path("p1", "mission-001", spawn_ts, "w1")
    handoff_path.parent.mkdir(parents=True, exist_ok=True)

    os.environ["ZENITH_HANDOFF_PATH"] = str(handoff_path)
    os.environ["ZENITH_NODE_ID"] = task.id
    os.environ["ZENITH_NODE_TYPE"] = task.type
    try:
        loader = AssetLoader(config)
        runner = ACPNodeRunner(config=config, loader=loader)

        async def _no_op_server(*args, **kwargs):
            return await asyncio.create_subprocess_exec(
                "sleep", "30",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

        async def _ready_immediately(*args, **kwargs):
            return None

        runner._start_worker_mcp_server = _no_op_server  # type: ignore[method-assign]
        runner._wait_for_server_ready = _ready_immediately  # type: ignore[method-assign]

        handoff = asyncio.run(
            runner.run_node(
                project_id="p1",
                mission_id="mission-001",
                task=task,
                spawn_ts=spawn_ts,
                store=store,
            )
        )
    finally:
        for k in ("ZENITH_HANDOFF_PATH", "ZENITH_NODE_ID", "ZENITH_NODE_TYPE"):
            os.environ.pop(k, None)

    assert isinstance(handoff, WorkHandoff)
    assert handoff.done is True
    # The file should be at the durable audit path.
    assert handoff_path.exists()
    data = json.loads(handoff_path.read_text())
    assert data["node_id"] == "w1"


def test_synthesize_missing_handoff_records_failure(
    config: HarnessConfig, project_setup, workspace: Path
):
    """If the agent exits without writing, the runner synthesizes a failure
    handoff and persists it to the durable audit path.
    """
    store = project_setup
    task = Task(id="w1", type="work", body="b", targets=["VAL-001"], skill="s")
    runner = ACPNodeRunner(config=config, loader=AssetLoader(config))
    handoff_path = store.attempt_path("p1", "mission-001", "2026-05-17T00-00-00Z", "w1")
    handoff = runner._synthesize_and_persist_missing_handoff(
        handoff_path=handoff_path,
        task=task,
        stop_reason="cancelled",
        exit_code=1,
        stderr="boom",
        session_error=None,
    )
    assert handoff.done is False
    assert "stop_reason=cancelled" in handoff.report
    assert handoff_path.exists()


def test_augment_acp_command_codex_appends_bypass_flags():
    out = _augment_acp_command("codex-acp", PROVIDERS["codex"])
    assert 'sandbox_mode="danger-full-access"' in out
    assert 'approval_policy="never"' in out
    assert 'model_reasoning_effort="xhigh"' in out
    assert out.startswith("codex-acp ")


def test_augment_acp_command_claude_untouched():
    assert _augment_acp_command("claude-agent-acp", PROVIDERS["claude"]) == "claude-agent-acp"


def test_codex_acp_env_preserves_node_path_when_bwrap_is_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for executable in ("node", "bwrap"):
        path = bin_dir / executable
        path.write_text("#!/bin/sh\n", encoding="utf-8")
        path.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))

    env = _acp_subprocess_env(PROVIDERS["codex"])

    assert str(bin_dir) in env["PATH"].split(os.pathsep)
    assert env["CODEX_SANDBOX"] == "danger-full-access"
    assert env["CODEX_DISABLE_SANDBOX"] == "1"


def test_attempt_path_naming(config: HarnessConfig, project_setup):
    store = project_setup
    p = store.attempt_path("p1", "mission-001", "2026-05-17T10-00-00Z", "w1")
    assert p.name == "2026-05-17T10-00-00Z__w1.json"
    assert "attempts" in p.parts
    # JSON handoff lives in the runtime cursor tree, not the durable .zenith record.
    assert ".zenith-runtime" in p.parts


def test_terminal_review_path_naming(config: HarnessConfig, project_setup):
    store = project_setup
    p = store.terminal_review_path("p1", "mission-001", "2026-05-17T10-00-00Z")
    assert p.name == "2026-05-17T10-00-00Z.json"
    assert "terminal-reviews" in p.parts
    # JSON handoff lives in the runtime cursor tree, not the durable .zenith record.
    assert ".zenith-runtime" in p.parts
