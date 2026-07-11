"""Regression tests for the per-project wave flock (`_run_project_locked`).

Proves the fix for the concurrent-wave disk race: an advisory lock whose
lifetime is tied to the worker THREAD (not the async request) so that an
aborted `advance_project` cannot let a retried call run concurrently and stub
still-in-flight validators. See server.py `_run_project_locked`.
"""
from __future__ import annotations

import asyncio
import threading
import time
import types
from pathlib import Path

import pytest

from zenith_harness.config import HarnessConfig
from zenith_harness.controller import ToolError
from zenith_harness.server import _run_project_locked

PID = "proj-1"


@pytest.fixture
def controller(harness_home: Path):
    bundled = Path(__file__).resolve().parents[1] / "src" / "zenith_harness" / "bundled"
    cfg = HarnessConfig(
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
    )
    # The helper only touches controller.config.zenith_runtime_dir(pid).
    return types.SimpleNamespace(config=cfg)


def test_runs_fn_and_returns_result(controller):
    assert _run_project_locked(controller, PID, lambda a, b: a + b, 2, 3) == 5
    assert (controller.config.zenith_runtime_dir(PID) / ".wave.lock").exists()


def test_second_call_is_rejected_while_first_holds_lock(controller):
    started, release = threading.Event(), threading.Event()

    def slow():
        started.set()
        release.wait(5)
        return "first"

    t = threading.Thread(target=lambda: _run_project_locked(controller, PID, slow))
    t.start()
    assert started.wait(5)
    try:
        with pytest.raises(ToolError) as ei:
            _run_project_locked(controller, PID, lambda: "second")
        assert ei.value.code == "wave_in_progress"
    finally:
        release.set()
        t.join(5)
    # lock freed after the holder returns
    assert _run_project_locked(controller, PID, lambda: "third") == "third"


def test_lock_survives_async_cancellation(controller):
    """The exact bug: aborting the MCP request must NOT free the wave lock while
    the orphaned worker thread keeps running."""

    async def scenario():
        started, release = threading.Event(), threading.Event()

        def slow():
            started.set()
            release.wait(5)
            return "done"

        task = asyncio.create_task(
            asyncio.to_thread(_run_project_locked, controller, PID, slow)
        )
        await asyncio.to_thread(started.wait, 5)  # thread now in critical section

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # async request is gone, but the thread still runs and still holds the lock
        with pytest.raises(ToolError) as ei:
            _run_project_locked(controller, PID, lambda: "x")
        assert ei.value.code == "wave_in_progress"

        # let the orphaned wave finish; the lock frees only then
        release.set()
        for _ in range(50):
            await asyncio.to_thread(time.sleep, 0.05)
            try:
                assert _run_project_locked(controller, PID, lambda: "ok") == "ok"
                return
            except ToolError:
                continue
        pytest.fail("lock never released after the wave completed")

    asyncio.run(scenario())


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
