"""Real-ACP PARALLEL smoke tests for workspace-backed worker dispatch.

Unlike `test_smoke_real_acp.py` (a single serial work->validate->gate chain),
this drives TWO independent work tasks that become runnable at T+0, so with
`max_parallel_nodes=2` the coordinator dispatches them as a parallel batch —
each in the current workspace, each spawning its own real ACP adapter.

Goal: observe what actually happens (success, or the session error / stderr
captured in the synthesized handoff) when ACP adapters launch concurrently.

Run:

    PATH="/home/pvduy/.npm/_npx/d820eb7d96bc2600/node_modules/.bin:$PATH" \
    ZENITH_SMOKE_REAL_ACP=claude \
    uv run pytest tests/test_smoke_parallel_acp.py -s

Gated by ZENITH_SMOKE_REAL_ACP so the default suite stays hermetic.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from zenith_harness.acp_runner import ACPNodeDispatcher
from zenith_harness.config import HarnessConfig
from zenith_harness.controller import ProjectController
from zenith_harness.models import Task, TaskList, TerminalReviewHandoff
from zenith_harness.storage import ProjectStore

_FLAG = os.environ.get("ZENITH_SMOKE_REAL_ACP", "").strip().lower()
_CLAUDE_ENABLED = _FLAG in ("1", "true", "yes", "all", "both", "claude")
_CODEX_ENABLED = _FLAG in ("all", "both", "codex")
_CLAUDE_ACP = (
    os.environ.get("ZENITH_SMOKE_CLAUDE_ACP_CMD")
    or os.environ.get("ZENITH_SMOKE_ACP_CMD")
    or "claude-agent-acp"
)
_CODEX_ACP = (
    os.environ.get("ZENITH_SMOKE_CODEX_ACP_CMD")
    or os.environ.get("ZENITH_SMOKE_ACP_CMD")
    or "codex-acp"
)
_MID = "mission-001"
_N = int(os.environ.get("ZENITH_SMOKE_N", "2") or "2")


def _have_command(command: str) -> bool:
    return bool(os.environ.get("ZENITH_SMOKE_ACP_CMD")) or bool(shutil.which(command))


CONTRACT = "# {aid}: file {fname} exists\n\n`{fname}` must exist with content `{word}\\n`.\n"

WORKER_BODY = """Use your Write or Bash tool to create the file `{fname}` in the
current working directory (cwd) with the exact content:

    {word}

(that is `{word}` followed by one newline). Then call
`end_node(done=True, report="wrote {fname}")` and stop. Do nothing else.
"""


def _write_skill(store: ProjectStore, pid: str) -> None:
    d = store.zenith_dir(pid) / "skills" / "noop-file-worker"
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        "---\nname: noop-file-worker\ndescription: write one file then end_node.\n---\n"
        "# noop-file-worker\nFollow the assigned body exactly; create only the "
        "requested file in cwd, then call end_node once.\n",
        encoding="utf-8",
    )


def _write_contract(store: ProjectStore, pid: str, aid: str, fname: str, word: str) -> None:
    d = store.ensure_contract_dir(pid, _MID)
    (d / f"{aid}.md").write_text(CONTRACT.format(aid=aid, fname=fname, word=word))


def _task_ids(n: int) -> list[str]:
    return [f"w{i}" for i in range(n)]


def _tasks(n: int) -> TaskList:
    # N independent work tasks, no deps -> all runnable at T+0 -> one parallel
    # batch with max_parallel_nodes=N. Forces N concurrent claude adapters.
    return TaskList(tasks=[
        Task(id=f"w{i}", type="work", targets=[f"VAL-{i}"], skill="noop-file-worker",
             body=WORKER_BODY.format(fname=f"f{i}.txt", word=f"word{i}"))
        for i in range(n)
    ])


class _CleanReviewer:
    def review(self, project_id: str, mission_id: str, spawn_ts: str):
        return TerminalReviewHandoff(done=True, report="clean")


@pytest.mark.skipif(
    not (_CLAUDE_ENABLED and _have_command(_CLAUDE_ACP)),
    reason=(
        "Set ZENITH_SMOKE_REAL_ACP=claude and put claude-agent-acp on PATH "
        "(or set ZENITH_SMOKE_CLAUDE_ACP_CMD) to enable this smoke test."
    ),
)
def test_parallel_workspace_claude(workspace: Path, harness_home: Path):
    _run_parallel_workspace_acp(
        provider="claude",
        acp_command=_CLAUDE_ACP,
        workspace=workspace,
        harness_home=harness_home,
    )


@pytest.mark.skipif(
    not (_CODEX_ENABLED and _have_command(_CODEX_ACP)),
    reason=(
        "Set ZENITH_SMOKE_REAL_ACP=codex and put codex-acp on PATH "
        "(or set ZENITH_SMOKE_CODEX_ACP_CMD) to enable this smoke test."
    ),
)
def test_parallel_workspace_codex(workspace: Path, harness_home: Path):
    _run_parallel_workspace_acp(
        provider="codex",
        acp_command=_CODEX_ACP,
        workspace=workspace,
        harness_home=harness_home,
    )


def _run_parallel_workspace_acp(
    *,
    provider: str,
    acp_command: str,
    workspace: Path,
    harness_home: Path,
) -> None:
    config = HarnessConfig(
        bundled_dir=Path(__file__).resolve().parents[1] / "src" / "zenith_harness" / "bundled",
        harness_home=harness_home,
        projects_dir=harness_home / "projects",
        orchestrator_provider_name=provider,
        worker_provider_name=provider,
        worker_acp_command=acp_command,
        validator_provider_name=None,
        validator_acp_command=None,
        terminal_reviewer_provider_name=None,
        terminal_reviewer_acp_command=None,
        max_parallel_nodes=_N,
    )
    dispatcher = ACPNodeDispatcher(config)
    controller = ProjectController(config, dispatcher, _CleanReviewer())

    controller.start_project("parallel smoke", str(workspace), "test-owner")
    store = ProjectStore(config)
    pid = store.list_projects()[0].id

    _write_skill(store, pid)
    for i in range(_N):
        _write_contract(store, pid, f"VAL-{i}", f"f{i}.txt", f"word{i}")
    controller.submit_plan(pid, _tasks(_N))
    print(f"\n=== dispatching provider={provider} N={_N} parallel work tasks ===")

    # Single advance: all work tasks dispatch as one parallel batch.
    env = controller.advance_project(pid)
    print(f"=== state after advance: {env.state.state} ===")

    rt = store.attempts_runtime_dir(pid, _MID)
    reports: dict[str, dict] = {}
    for tid in _task_ids(_N):
        files = sorted(rt.glob(f"*__{tid}.json"))
        if not files:
            print(f"[{tid}] NO attempt file")
            continue
        data = json.loads(files[-1].read_text())
        reports[tid] = data
        ok = data.get("done")
        print(f"[{tid}] done={ok}" + ("" if ok else f"  <<< {(data.get('report') or '')[:600]}"))

    for tid in _task_ids(_N):
        assert tid in reports, f"{tid} produced no handoff at all"
    failed = {t: r for t, r in reports.items() if not r.get("done")}
    assert not failed, (
        f"parallel {provider} worker(s) failed:\n"
        + "\n".join(f"{t}: {r.get('report')}" for t, r in failed.items())
    )
