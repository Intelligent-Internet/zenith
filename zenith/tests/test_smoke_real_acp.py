"""Real-ACP smoke tests — drive an end-to-end tiny mission through
production `ACPNodeDispatcher` against actual `claude-agent-acp` and
`codex-acp` binaries.

Gated by env var to keep the default test suite hermetic and free of
LLM-credit consumption:

    ZENITH_SMOKE_REAL_ACP=claude pytest tests/test_smoke_real_acp.py -s
    ZENITH_SMOKE_REAL_ACP=codex  pytest tests/test_smoke_real_acp.py -s
    ZENITH_SMOKE_REAL_ACP=both   pytest tests/test_smoke_real_acp.py -s

Per-test timeouts default to 300 seconds (covers a cold-cache LLM run);
override via ZENITH_SMOKE_TIMEOUT_SECONDS=N.

The mission is trivially small — one work node writes `hello.txt` with
the literal content `world\\n`, one validate node checks the file exists
with that content. We verify:

  1. The orchestrator advances through the state machine to a stable
     state (gate_checkpoint, then terminal review → done).
  2. The attempt JSON handoffs land in the runtime cursor tree
     (`<bucket>/.zenith-runtime/missions/<mid>/attempts/<ts>__<node>.json`)
     and the agent-readable MD mirrors in the durable `.zenith/` record.
  3. `hello.txt` actually got written by the worker session.
  4. The validator's per-item verdict is `passed=True`.

These tests are slow (typical wall time ~60-120s each); skip locally
unless you're validating an ACP wiring change.
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest

from zenith_harness.acp_runner import ACPNodeDispatcher, ACPTerminalReviewer
from zenith_harness.config import HarnessConfig
from zenith_harness.controller import ProjectController
from zenith_harness.models import (
    Decision,
    Task,
    TaskList,
)
from zenith_harness.storage import ProjectStore


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------


_FLAG = os.environ.get("ZENITH_SMOKE_REAL_ACP", "").strip().lower()
_TIMEOUT_S = int(os.environ.get("ZENITH_SMOKE_TIMEOUT_SECONDS", "300"))


def _provider_enabled(name: str) -> bool:
    if _FLAG in ("1", "true", "yes", "all", "both"):
        return True
    return _FLAG == name


def _binary_present(cmd: str) -> bool:
    return shutil.which(cmd) is not None


# ---------------------------------------------------------------------------
# Mission scaffolding
# ---------------------------------------------------------------------------


CONTRACT_BODY = """# VAL-HELLO-001: hello.txt exists

The file `hello.txt` in the workspace root must exist with EXACTLY this content:

```
world
```

(That is the literal six bytes `w`, `o`, `r`, `l`, `d`, `\\n`.)

No other files modified.
"""


WORKER_BODY = """Use your Bash or Write tool to create `hello.txt` in the workspace
root (cwd) with the exact 6-byte content:

    world

(That is `world` followed by a single newline.)

After verifying the file exists and contains exactly that content, call
`end_node(done=True, report="wrote hello.txt with content 'world'")`
and exit. Do not modify any other files.
"""


VALIDATOR_BODY = """Audit assertion `VAL-HELLO-001`:

1. `Read hello.txt` from the cwd.
2. Check that its content is exactly `world\\n` (6 bytes).
3. Report verdict:

   - if matches: `passed=True`
   - else:       `passed=False` with a note explaining what you observed.

Call `end_node(done=True, report="<what you saw>",
items=[{"item_id": "VAL-HELLO-001", "passed": <bool>}], passed=<bool>)`.
Do not edit any files.
"""


def _build_task_list() -> TaskList:
    return TaskList(tasks=[
        Task(
            id="w1",
            type="work",
            body=WORKER_BODY,
            targets=["VAL-HELLO-001"],
            skill="hello-file-worker",
        ),
        Task(
            id="v1",
            type="validate",
            body=VALIDATOR_BODY,
            targets=["VAL-HELLO-001"],
            skill="scrutiny-validator",
            depends_on=["w1"],
        ),
        Task(
            id="g1",
            type="gate",
            body="",
            targets=["VAL-HELLO-001"],
            skill=None,
            depends_on=["v1"],
        ),
    ])


def _write_contract(store: ProjectStore, pid: str, mission_id: str) -> None:
    d = store.ensure_contract_dir(pid, mission_id)
    (d / "VAL-HELLO-001.md").write_text(CONTRACT_BODY)


def _write_worker_skill(store: ProjectStore, pid: str) -> None:
    d = store.zenith_dir(pid) / "skills" / "hello-file-worker"
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        """---
name: hello-file-worker
description: Project-authored worker procedure for the smoke hello-file node.
---

# hello-file-worker

Follow the assigned node body exactly. Use the workspace cwd, create only the
requested file, verify its exact contents, then call `end_node` once.
""",
        encoding="utf-8",
    )


def _make_config(
    harness_home: Path,
    provider: str,
    *,
    use_for_terminal: bool = False,
) -> HarnessConfig:
    bundled = Path(__file__).resolve().parents[1] / "src" / "zenith_harness" / "bundled"
    acp_command = "claude-agent-acp" if provider == "claude" else "codex-acp"
    return HarnessConfig(
        bundled_dir=bundled,
        harness_home=harness_home,
        projects_dir=harness_home / "projects",
        orchestrator_provider_name=provider,
        worker_provider_name=provider,
        worker_acp_command=acp_command,
        validator_provider_name=None,
        validator_acp_command=None,
        terminal_reviewer_provider_name=provider if use_for_terminal else None,
        terminal_reviewer_acp_command=acp_command if use_for_terminal else None,
    )


# ---------------------------------------------------------------------------
# In-process clean terminal reviewer (skip real LLM call for the L3 layer)
# ---------------------------------------------------------------------------


class _CleanTerminalReviewer:
    """Bypass the real terminal reviewer for smoke tests with a clean report.

    The smoke test focuses on validating worker + validator ACP integration.
    Spawning a third LLM call (terminal review) doubles the wall time + LLM
    cost without testing anything new about the ACP wiring. We swap in a
    no-op clean reviewer; see `test_real_terminal_reviewer` below for a
    dedicated test that exercises the real terminal-review path.
    """

    def review(self, project_id: str, mission_id: str, spawn_ts: str):
        from zenith_harness.models import TerminalReviewHandoff

        return TerminalReviewHandoff(done=True, report="smoke test: clean")


# ---------------------------------------------------------------------------
# Per-provider smoke
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provider",
    [
        pytest.param(
            "claude",
            marks=pytest.mark.skipif(
                not _provider_enabled("claude") or not _binary_present("claude-agent-acp"),
                reason=(
                    "Set ZENITH_SMOKE_REAL_ACP=claude (or both) and install "
                    "claude-agent-acp to enable this smoke test."
                ),
            ),
        ),
        pytest.param(
            "codex",
            marks=pytest.mark.skipif(
                not _provider_enabled("codex") or not _binary_present("codex-acp"),
                reason=(
                    "Set ZENITH_SMOKE_REAL_ACP=codex (or both) and install "
                    "codex-acp to enable this smoke test."
                ),
            ),
        ),
    ],
)
def test_smoke_hello_mission(
    provider: str,
    workspace: Path,
    harness_home: Path,
    tmp_path: Path,
):
    """Drive a tiny mission end-to-end against the real ACP for `provider`."""
    config = _make_config(harness_home, provider)
    dispatcher = ACPNodeDispatcher(config)
    controller = ProjectController(
        config, dispatcher, _CleanTerminalReviewer()
    )

    # 1) start_project
    start_env = controller.start_project("smoke test brief", str(workspace))
    pid = controller.store.list_projects()[0].id
    assert start_env.state.state == "mission_planning"

    # 2) contract + submit_plan
    _write_contract(controller.store, pid, "mission-001")
    _write_worker_skill(controller.store, pid)
    plan_env = controller.submit_plan(pid, _build_task_list())
    assert plan_env.state.state == "mission_running"

    # 3) advance_project — this is the slow part (real LLM calls)
    deadline = time.monotonic() + _TIMEOUT_S
    state_history: list[str] = []

    # Drive: w1 → v1 → g1, acknowledge the gate checkpoint, then request
    # closure via end_mission.
    # Each `advance_project` call returns at the next attention/terminal/idle.
    # We expect: first call → gate_checkpoint; we say continue;
    # second call → mission_running with no runnable task work;
    # end_mission → Done (via clean terminal reviewer).
    advance_env = controller.advance_project(pid)
    state_history.append(advance_env.state.state)
    assert (
        advance_env.state.state == "attention_needed"
    ), f"expected gate_checkpoint, got state={advance_env.state.state}"

    items = controller.store.load_attention(pid)
    assert items and items[0].kind == "gate_checkpoint", (
        f"expected gate_checkpoint kind, got {items[0].kind if items else 'no items'}; "
        f"report={items[0].report if items else 'n/a'}"
    )

    controller.decide_attention(
        pid, [Decision(item_id=items[0].id, action="continue")]
    )

    if time.monotonic() > deadline:
        pytest.fail(f"smoke test exceeded {_TIMEOUT_S}s before terminal review")

    post_gate = controller.advance_project(pid)
    state_history.append(post_gate.state.state)
    assert post_gate.state.state == "mission_running", (
        f"expected mission_running after gate acknowledgement, got {post_gate.state.state}; "
        f"history={state_history}"
    )
    final = controller.end_mission(pid)
    state_history.append(final.state.state)
    assert final.state.state == "done", (
        f"expected done after terminal review, got {final.state.state}; "
        f"history={state_history}"
    )

    # 4) Workspace artifact: hello.txt with the literal content
    hello = workspace / "hello.txt"
    assert hello.exists(), f"worker did not create {hello}"
    content = hello.read_text(encoding="utf-8")
    expected_bytes = b"world\n"
    assert content == "world\n", (
        f"hello.txt content mismatch: expected {expected_bytes!r}, got {content!r}"
    )

    # 5) Attempt JSON handoffs in the runtime cursor tree (.zenith-runtime/)
    rt_attempts = controller.store.attempts_runtime_dir(pid, "mission-001")
    assert rt_attempts.is_dir(), f"missing {rt_attempts}"
    work_attempts = list(rt_attempts.glob("*__w1.json"))
    val_attempts = list(rt_attempts.glob("*__v1.json"))
    assert work_attempts, f"no work attempt files in {rt_attempts}: {list(rt_attempts.iterdir())}"
    assert val_attempts, f"no validate attempt files in {rt_attempts}: {list(rt_attempts.iterdir())}"

    # ...and agent-readable MD mirrors in the durable .zenith/ record.
    durable_attempts = controller.store.attempts_dir(pid, "mission-001")
    assert durable_attempts.is_dir(), f"missing {durable_attempts}"
    assert list(durable_attempts.glob("*__w1.md")), (
        f"no work MD mirror in {durable_attempts}: {list(durable_attempts.iterdir())}"
    )

    # 6) Validator verdict on disk
    from zenith_harness.models import ValidateHandoff

    val_handoff = ValidateHandoff.model_validate_json(
        val_attempts[-1].read_text()
    )
    assert val_handoff.passed is True, (
        f"validator did not pass: items={val_handoff.items}, report={val_handoff.report}"
    )
    item_passed = any(
        it.item_id == "VAL-HELLO-001" and it.passed for it in val_handoff.items
    )
    assert item_passed, f"VAL-HELLO-001 not marked passed: items={val_handoff.items}"

    # 7) Closeout written
    closeout = controller.store.mission_dir(pid, "mission-001") / "closeout.md"
    assert closeout.exists(), f"missing closeout at {closeout}"


# ---------------------------------------------------------------------------
# Real terminal reviewer (optional — extra coverage of the L3 ACP path)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_provider_enabled("claude") and _binary_present("claude-agent-acp")),
    reason="Set ZENITH_SMOKE_REAL_ACP=claude (or both) + install claude-agent-acp.",
)
def test_smoke_real_terminal_reviewer_claude(
    workspace: Path, harness_home: Path
):
    """Exercise the real terminal-review ACP path with claude-agent-acp.

    This is a separate test because it adds another minutes-scale LLM call.
    """
    _run_with_real_terminal_reviewer("claude", workspace, harness_home)


@pytest.mark.skipif(
    not (_provider_enabled("codex") and _binary_present("codex-acp")),
    reason="Set ZENITH_SMOKE_REAL_ACP=codex (or both) + install codex-acp.",
)
def test_smoke_real_terminal_reviewer_codex(
    workspace: Path, harness_home: Path
):
    _run_with_real_terminal_reviewer("codex", workspace, harness_home)


def _run_with_real_terminal_reviewer(
    provider: str, workspace: Path, harness_home: Path
) -> None:
    config = _make_config(harness_home, provider, use_for_terminal=True)
    dispatcher = ACPNodeDispatcher(config)
    reviewer = ACPTerminalReviewer(config)
    controller = ProjectController(config, dispatcher, reviewer)

    controller.start_project("smoke test brief", str(workspace))
    pid = controller.store.list_projects()[0].id
    _write_contract(controller.store, pid, "mission-001")
    _write_worker_skill(controller.store, pid)
    controller.submit_plan(pid, _build_task_list())

    deadline = time.monotonic() + _TIMEOUT_S
    env = controller.advance_project(pid)
    assert env.state.state == "attention_needed"
    items = controller.store.load_attention(pid)
    assert items[0].kind == "gate_checkpoint"
    controller.decide_attention(
        pid, [Decision(item_id=items[0].id, action="continue")]
    )
    if time.monotonic() > deadline:
        pytest.fail("smoke test ran out of budget before terminal review")
    post_gate = controller.advance_project(pid)
    assert post_gate.state.state == "mission_running"
    final = controller.end_mission(pid)
    # Either Done (clean review) or attention_needed (reviewer found gaps).
    # We accept both — the goal is to confirm the L3 ACP wiring works.
    assert final.state.state in ("done", "attention_needed"), (
        f"unexpected post-terminal state: {final.state.state}"
    )

    review_dir = controller.store.terminal_reviews_dir(pid, "mission-001")
    assert review_dir.is_dir() and any(review_dir.iterdir()), (
        f"terminal reviewer did not write terminal review at {review_dir}"
    )
