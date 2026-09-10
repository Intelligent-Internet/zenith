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
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from zenith_harness import acp_runner
from zenith_harness.acp_runner import (
    ACPClient,
    ACPNodeRunner,
    _acp_subprocess_env,
    _augment_acp_command,
)
from zenith_harness.providers import PROVIDERS
from zenith_harness.assets import AssetLoader
from zenith_harness.config import HarnessConfig
from zenith_harness.models import Task, ValidateHandoff, WorkHandoff
from zenith_harness.runtime_identity import RuntimeIdentityRegistration
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
        validator_provider_name="claude",
        validator_acp_command=mock_acp_command,
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


def _prepare_runtime_identity(
    store: ProjectStore,
    workspace: Path,
    task: Task,
    spawn_ts: str,
) -> None:
    provider_config = workspace / ".claude/settings.json"
    provider_config.parent.mkdir(parents=True, exist_ok=True)
    provider_config.write_text("{}\n", encoding="utf-8")
    task_state = store.load_task_state("p1", "mission-001")
    task_state.set_status(task.id, "running")
    task_state.set_last_attempt(task.id, spawn_ts)
    store.save_task_state("p1", "mission-001", task_state)


# ---------------------------------------------------------------------------
# Mock-agent integration: the agent writes directly to ZENITH_HANDOFF_PATH
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not shutil.which("python3") and not Path(sys.executable).exists(),
    reason="Python interpreter unavailable",
)
def test_run_node_with_mock_agent(config: HarnessConfig, project_setup, workspace: Path):
    """End-to-end via the mock agent (NO real worker MCP server subprocess —
    we point at a free port that nothing binds to and rely on the mock to
    write the handoff file itself).
    """
    store = project_setup
    task = Task(id="w1", type="work", body="do it", targets=["VAL-001"], skill="s")
    spawn_ts = "2026-05-17T00-00-00Z"
    handoff_path = store.attempt_path("p1", "mission-001", spawn_ts, "w1")
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    _prepare_runtime_identity(store, workspace, task, spawn_ts)

    os.environ["ZENITH_HANDOFF_PATH"] = str(handoff_path)
    os.environ["ZENITH_NODE_ID"] = task.id
    os.environ["ZENITH_NODE_TYPE"] = task.type
    try:
        loader = AssetLoader(config)
        runner = ACPNodeRunner(config=config, loader=loader)

        async def _no_op_server(*args, **kwargs):
            return await asyncio.create_subprocess_exec(
                "sleep",
                "30",
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


def test_run_node_issues_identity_from_live_production_controller_and_blocks_fake(
    config: HarnessConfig,
    project_setup,
    workspace: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    store = project_setup
    task = Task(id="w-identity", type="work", body="identity", targets=[], skill="s")
    spawn_ts = "2026-07-23T00-00-00Z"
    task_state = store.load_task_state("p1", "mission-001")
    task_state.set_status(task.id, "running")
    task_state.set_last_attempt(task.id, spawn_ts)
    store.save_task_state("p1", "mission-001", task_state)
    handoff_path = store.attempt_path("p1", "mission-001", spawn_ts, task.id)
    identity_output = tmp_path / "runtime-identity.json"
    fake_controller_output = tmp_path / "fake-controller.json"
    fake_identity = tmp_path / "fake-identity.json"
    fake_verify_output = tmp_path / "fake-verify.json"
    fake_controller = Path(__file__).resolve().parent / "fake_runtime_identity_controller.py"
    product_root = Path("/home/lenovo/workspaces/cursor/projects/active/harness-belief-remediation")
    harness_source = Path(__file__).resolve().parents[1] / "src"
    python_path = os.pathsep.join(
        [str(product_root), str(harness_source), os.environ.get("PYTHONPATH", "")]
    )
    monkeypatch.setenv("PYTHONPATH", python_path)
    monkeypatch.setenv("ZENITH_HANDOFF_PATH", str(handoff_path))
    monkeypatch.setenv("ZENITH_NODE_ID", task.id)
    monkeypatch.setenv("ZENITH_NODE_TYPE", task.type)
    monkeypatch.setenv(
        "MOCK_ACP_RUNTIME_IDENTITY_COMMAND",
        json.dumps(
            [
                sys.executable,
                "-m",
                "self_improvement_release",
                "runtime-identity",
            ]
        ),
    )
    monkeypatch.setenv("MOCK_ACP_RUNTIME_IDENTITY_OUTPUT", str(identity_output))
    monkeypatch.setenv(
        "MOCK_ACP_FAKE_CONTROLLER_COMMAND",
        json.dumps(
            [
                sys.executable,
                str(fake_controller),
                str(config.harness_home),
                str(workspace),
                "p1",
                "mission-001",
                task.id,
                spawn_ts,
                str(fake_identity),
            ]
        ),
    )
    monkeypatch.setenv("MOCK_ACP_FAKE_CONTROLLER_OUTPUT", str(fake_controller_output))
    monkeypatch.setenv(
        "MOCK_ACP_FAKE_IDENTITY_VERIFY_COMMAND",
        json.dumps(
            [
                sys.executable,
                "-m",
                "self_improvement_release",
                "runtime-identity",
                "--input",
                str(fake_identity),
            ]
        ),
    )
    monkeypatch.setenv(
        "MOCK_ACP_FAKE_IDENTITY_VERIFY_OUTPUT",
        str(fake_verify_output),
    )
    captured_identity_environment: dict[str, str] = {}
    original_subprocess_env = acp_runner._acp_subprocess_env

    def _capture_subprocess_env(provider, **kwargs):
        environment = original_subprocess_env(provider, **kwargs)
        for name in (
            "SELF_IMPROVEMENT_ZENITH_AUTHORITY_ENDPOINT",
            "SELF_IMPROVEMENT_ZENITH_AUTHORITY_CAPABILITY",
        ):
            if value := environment.get(name):
                captured_identity_environment[name] = value
        return environment

    monkeypatch.setattr(acp_runner, "_acp_subprocess_env", _capture_subprocess_env)
    runner = ACPNodeRunner(config=config, loader=AssetLoader(config))

    async def _no_op_server(*args, **kwargs):
        return await asyncio.create_subprocess_exec(
            "sleep",
            "30",
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

    assert isinstance(handoff, WorkHandoff)
    assert handoff.done is True
    identity_probe = json.loads(identity_output.read_text(encoding="utf-8"))
    assert identity_probe["returncode"] == 0, identity_probe
    identity_result = json.loads(identity_probe["stdout"])
    assert identity_result["disposition"] == "PROMOTE"
    identity = identity_result["identity"]
    assert identity["project_id"] == "p1"
    assert identity["mission_id"] == "mission-001"
    assert identity["task_id"] == task.id
    assert identity["task_attempt_id"] == spawn_ts
    assert identity["executor"] == "claude-worker"
    assert identity["provider"] == "claude"
    fake_probe = json.loads(fake_controller_output.read_text(encoding="utf-8"))
    assert fake_probe["returncode"] == 0
    assert fake_probe["stdout"].strip() == "MINTED"
    fake_verify = json.loads(fake_verify_output.read_text(encoding="utf-8"))
    assert fake_verify["returncode"] == 30
    assert json.loads(fake_verify["stdout"])["reason_code"] == ("IDENTITY_ATTESTATION_INVALID")
    closed_registration = subprocess.run(
        [
            sys.executable,
            "-m",
            "self_improvement_release",
            "runtime-identity",
        ],
        cwd=product_root,
        env={
            **os.environ,
            **captured_identity_environment,
            "PYTHONPATH": python_path,
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert closed_registration.returncode == 20
    assert json.loads(closed_registration.stdout)["reason_code"] == (
        "RUNTIME_AUTHORITY_UNAVAILABLE"
    )


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


def test_send_request_cancellation_during_write_cleans_pending():
    client = ACPClient(object(), ".")  # type: ignore[arg-type]
    write_started = asyncio.Event()

    async def _blocked_write(message):
        write_started.set()
        await asyncio.Event().wait()

    client._write = _blocked_write  # type: ignore[method-assign]

    async def _scenario():
        request = asyncio.create_task(client.send_request("method", {}))
        await write_started.wait()
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        assert client._pending == {}

    asyncio.run(_scenario())


@pytest.mark.skipif(
    not shutil.which("python3") and not Path(sys.executable).exists(),
    reason="Python interpreter unavailable",
)
def test_run_node_repairs_end_turn_without_handoff(
    config: HarnessConfig,
    project_setup,
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """An ACP prose-only first turn gets one same-session end_node retry."""
    store = project_setup
    task = Task(
        id="v1",
        type="validate",
        body="validate it",
        targets=["VAL-001"],
        skill="s",
    )
    spawn_ts = "2026-05-17T00-00-01Z"
    handoff_path = store.attempt_path("p1", "mission-001", spawn_ts, "v1")
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    _prepare_runtime_identity(store, workspace, task, spawn_ts)

    monkeypatch.setenv("ZENITH_HANDOFF_PATH", str(handoff_path))
    monkeypatch.setenv("ZENITH_NODE_ID", task.id)
    monkeypatch.setenv("ZENITH_NODE_TYPE", task.type)
    monkeypatch.setenv("MOCK_ACP_SKIP_FIRST_HANDOFF", "1")
    monkeypatch.setenv("MOCK_ACP_DONE", "1")
    monkeypatch.setenv("ZENITH_VALIDATION_PASSED", "1")
    monkeypatch.setenv("MOCK_ACP_REQUEST_ATTENTION", "0")
    runner = ACPNodeRunner(config=config, loader=AssetLoader(config))

    async def _no_op_server(*args, **kwargs):
        return await asyncio.create_subprocess_exec(
            "sleep",
            "30",
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

    assert isinstance(handoff, ValidateHandoff)
    assert handoff.done is True
    assert handoff.passed is True
    assert handoff.items[0].item_id == "VAL-001"


@pytest.mark.skipif(
    not shutil.which("python3") and not Path(sys.executable).exists(),
    reason="Python interpreter unavailable",
)
def test_run_node_does_not_retry_mutation_capable_worker(
    config: HarnessConfig,
    project_setup,
    monkeypatch: pytest.MonkeyPatch,
):
    store = project_setup
    task = Task(id="w2", type="work", body="mutate", targets=[], skill="s")
    spawn_ts = "2026-05-17T00-00-02Z"
    handoff_path = store.attempt_path("p1", "mission-001", spawn_ts, "w2")
    _prepare_runtime_identity(
        store,
        store.workspace_dir("p1"),
        task,
        spawn_ts,
    )
    monkeypatch.setenv("ZENITH_HANDOFF_PATH", str(handoff_path))
    monkeypatch.setenv("ZENITH_NODE_ID", task.id)
    monkeypatch.setenv("ZENITH_NODE_TYPE", task.type)
    monkeypatch.setenv("MOCK_ACP_SKIP_FIRST_HANDOFF", "1")
    monkeypatch.setenv("MOCK_ACP_DONE", "1")
    monkeypatch.setenv("MOCK_ACP_REQUEST_ATTENTION", "0")
    runner = ACPNodeRunner(config=config, loader=AssetLoader(config))

    async def _no_op_server(*args, **kwargs):
        return await asyncio.create_subprocess_exec(
            "sleep",
            "30",
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

    assert isinstance(handoff, WorkHandoff)
    assert handoff.done is False
    assert "without calling end_node" in handoff.report


@pytest.mark.skipif(
    not shutil.which("python3") and not Path(sys.executable).exists(),
    reason="Python interpreter unavailable",
)
def test_run_node_times_out_nonresponsive_validator_repair(
    config: HarnessConfig,
    project_setup,
    monkeypatch: pytest.MonkeyPatch,
):
    store = project_setup
    task = Task(
        id="v2",
        type="validate",
        body="validate it",
        targets=["VAL-001"],
        skill="s",
    )
    spawn_ts = "2026-05-17T00-00-03Z"
    handoff_path = store.attempt_path("p1", "mission-001", spawn_ts, "v2")
    _prepare_runtime_identity(
        store,
        store.workspace_dir("p1"),
        task,
        spawn_ts,
    )
    monkeypatch.setenv("ZENITH_HANDOFF_PATH", str(handoff_path))
    monkeypatch.setenv("ZENITH_NODE_ID", task.id)
    monkeypatch.setenv("ZENITH_NODE_TYPE", task.type)
    monkeypatch.setenv("MOCK_ACP_SKIP_FIRST_HANDOFF", "1")
    monkeypatch.setenv("MOCK_ACP_HANG_ON_SECOND_PROMPT", "1")
    monkeypatch.setenv("MOCK_ACP_DONE", "1")
    monkeypatch.setenv("ZENITH_VALIDATION_PASSED", "1")
    monkeypatch.setenv("MOCK_ACP_REQUEST_ATTENTION", "0")
    monkeypatch.setattr(acp_runner, "HANDOFF_REPAIR_TIMEOUT_SECONDS", 0.1)
    runner = ACPNodeRunner(config=config, loader=AssetLoader(config))

    async def _no_op_server(*args, **kwargs):
        return await asyncio.create_subprocess_exec(
            "sleep",
            "30",
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

    assert isinstance(handoff, ValidateHandoff)
    assert handoff.done is False
    assert "protocol repair timed out" in handoff.report


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


def test_acp_environment_scrubs_ambient_authority_and_adds_only_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "SELF_IMPROVEMENT_ZENITH_AUTHORITY_ENDPOINT",
        "SELF_IMPROVEMENT_ZENITH_AUTHORITY_CAPABILITY",
        "SELF_IMPROVEMENT_ZENITH_AUTHORITY_TOKEN",
        "SELF_IMPROVEMENT_ZENITH_ISSUER_STATE",
    ):
        monkeypatch.setenv(name, "ambient")

    terminal_environment = _acp_subprocess_env(PROVIDERS["claude"])
    assert not any(
        name.startswith("SELF_IMPROVEMENT_ZENITH_AUTHORITY_") for name in terminal_environment
    )
    assert "SELF_IMPROVEMENT_ZENITH_ISSUER_STATE" not in terminal_environment

    dispatch_environment = _acp_subprocess_env(
        PROVIDERS["claude"],
        runtime_identity_environment={
            "SELF_IMPROVEMENT_ZENITH_AUTHORITY_ENDPOINT": "@endpoint",
            "SELF_IMPROVEMENT_ZENITH_AUTHORITY_CAPABILITY": "capability",
        },
    )
    assert dispatch_environment["SELF_IMPROVEMENT_ZENITH_AUTHORITY_ENDPOINT"] == "@endpoint"
    assert dispatch_environment["SELF_IMPROVEMENT_ZENITH_AUTHORITY_CAPABILITY"] == "capability"
    assert "SELF_IMPROVEMENT_ZENITH_AUTHORITY_TOKEN" not in dispatch_environment


def test_failed_identity_registration_refuses_agent_spawn(
    config: HarnessConfig,
    project_setup,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = Task(id="w-refuse", type="work", body="b", targets=[], skill="s")
    runner = ACPNodeRunner(config=config, loader=AssetLoader(config))

    async def _no_op_server(*args, **kwargs):
        return await asyncio.create_subprocess_exec(
            "sleep",
            "30",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

    async def _ready_immediately(*args, **kwargs):
        return None

    async def _unexpected_spawn(*args, **kwargs):
        raise AssertionError("ACP spawn must not occur")

    runner._start_worker_mcp_server = _no_op_server  # type: ignore[method-assign]
    runner._wait_for_server_ready = _ready_immediately  # type: ignore[method-assign]
    runner._register_runtime_identity = lambda **kwargs: RuntimeIdentityRegistration(  # type: ignore[method-assign]
        None,
        None,
        "REGISTRATION_INPUT_UNAVAILABLE",
    )
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _unexpected_spawn)

    handoff = asyncio.run(
        runner.run_node(
            "p1",
            "mission-001",
            task,
            "attempt-refuse",
            project_setup,
        )
    )
    assert handoff.done is False
    assert "REGISTRATION_INPUT_UNAVAILABLE" in handoff.report


@pytest.mark.parametrize("cancel_point", ["readiness", "spawn", "client_start"])
def test_run_node_cancellation_closes_acquired_resources(
    cancel_point: str,
    config: HarnessConfig,
    project_setup,
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = Task(
        id=f"w-cancel-{cancel_point}",
        type="work",
        body="b",
        targets=[],
        skill="s",
    )
    spawn_ts = f"attempt-{cancel_point}"
    _prepare_runtime_identity(project_setup, workspace, task, spawn_ts)
    runner = ACPNodeRunner(config=config, loader=AssetLoader(config))
    mcp_processes: list[asyncio.subprocess.Process] = []
    registrations: list[RuntimeIdentityRegistration] = []
    original_register = runner._register_runtime_identity

    async def _no_op_server(*args, **kwargs):
        process = await asyncio.create_subprocess_exec(
            "sleep",
            "30",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        mcp_processes.append(process)
        return process

    async def _ready(*args, **kwargs):
        if cancel_point == "readiness":
            raise asyncio.CancelledError

    def _register(**kwargs):
        registration = original_register(**kwargs)
        registrations.append(registration)
        return registration

    runner._start_worker_mcp_server = _no_op_server  # type: ignore[method-assign]
    runner._wait_for_server_ready = _ready  # type: ignore[method-assign]
    runner._register_runtime_identity = _register  # type: ignore[method-assign]
    if cancel_point == "spawn":

        async def _cancel_spawn(*args, **kwargs):
            raise asyncio.CancelledError

        monkeypatch.setattr(asyncio, "create_subprocess_shell", _cancel_spawn)
    elif cancel_point == "client_start":

        async def _cancel_start(self):
            raise asyncio.CancelledError

        monkeypatch.setattr(ACPClient, "start", _cancel_start)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            runner.run_node(
                "p1",
                "mission-001",
                task,
                spawn_ts,
                project_setup,
            )
        )
    assert mcp_processes and mcp_processes[0].returncode is not None
    if registrations:
        assert registrations[0].endpoint is None
        assert registrations[0].capability is None


@pytest.mark.parametrize("cancel_point", ["readiness", "spawn", "client_start"])
def test_terminal_review_cancellation_closes_acquired_resources(
    cancel_point: str,
    config: HarnessConfig,
    project_setup,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal_config = replace(
        config,
        terminal_reviewer_provider_name="claude",
        terminal_reviewer_acp_command=config.worker_acp_command,
    )
    runner = ACPNodeRunner(
        config=terminal_config,
        loader=AssetLoader(terminal_config),
    )
    mcp_processes: list[asyncio.subprocess.Process] = []
    acp_processes: list[asyncio.subprocess.Process] = []
    original_spawn = asyncio.create_subprocess_shell

    async def _no_op_server(*args, **kwargs):
        process = await asyncio.create_subprocess_exec(
            "sleep",
            "30",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        mcp_processes.append(process)
        return process

    async def _ready(*args, **kwargs):
        if cancel_point == "readiness":
            raise asyncio.CancelledError

    async def _spawn(*args, **kwargs):
        if cancel_point == "spawn":
            raise asyncio.CancelledError
        process = await original_spawn(*args, **kwargs)
        acp_processes.append(process)
        return process

    runner._start_terminal_reviewer_mcp = _no_op_server  # type: ignore[method-assign]
    runner._wait_for_server_ready = _ready  # type: ignore[method-assign]
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _spawn)
    if cancel_point == "client_start":

        async def _cancel_start(self):
            raise asyncio.CancelledError

        monkeypatch.setattr(ACPClient, "start", _cancel_start)

    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(
                runner.run_terminal_review(
                    "p1",
                    "mission-001",
                    f"attempt-{cancel_point}",
                    project_setup,
                )
            )
        assert mcp_processes and mcp_processes[0].returncode is not None
        if acp_processes:
            assert acp_processes[0].returncode is not None
    finally:
        for process in [*acp_processes, *mcp_processes]:
            if process.returncode is None:
                process.kill()


def test_chatty_mcp_subprocess_cannot_fill_parent_pipe(
    config: HarnessConfig,
    project_setup,
    workspace: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chatty_python = tmp_path / "chatty-python"
    chatty_python.write_text(
        (
            f"#!{sys.executable}\n"
            "import os\n"
            "os.write(1, b'x' * (1024 * 1024))\n"
            "os.write(2, b'y' * (1024 * 1024))\n"
        ),
        encoding="utf-8",
    )
    chatty_python.chmod(0o755)
    monkeypatch.setattr(acp_runner.sys, "executable", str(chatty_python))
    runner = ACPNodeRunner(config=config, loader=AssetLoader(config))
    task = Task(id="w-chatty", type="work", body="b", targets=[], skill="s")

    async def _exercise() -> tuple[int | None, object, object]:
        process = await runner._start_worker_mcp_server(
            task=task,
            project_id="p1",
            mission_id="mission-001",
            handoff_path=str(tmp_path / "handoff.json"),
            workspace_dir=str(workspace),
            mcp_port=runner._find_free_port(),
        )
        await asyncio.wait_for(process.wait(), timeout=2)
        return process.returncode, process.stdout, process.stderr

    returncode, stdout, stderr = asyncio.run(_exercise())
    assert returncode == 0
    assert stdout is None
    assert stderr is None


def test_progress_callback_exception_is_isolated() -> None:
    async def _raising_callback(_message: str) -> None:
        raise RuntimeError("progress callback failed")

    tracker = acp_runner.ACPProgressTracker(callback=_raising_callback)
    tracker.agent_buffer = "bounded progress."
    asyncio.run(tracker.flush())

    assert tracker.agent_buffer == ""
    assert tracker.last_emitted == "bounded progress."


def test_run_node_flush_exception_does_not_skip_cleanup(
    config: HarnessConfig,
    project_setup,
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = Task(id="w-flush-failure", type="work", body="b", targets=[], skill="s")
    spawn_ts = "attempt-flush-failure"
    _prepare_runtime_identity(project_setup, workspace, task, spawn_ts)
    handoff_path = project_setup.attempt_path("p1", "mission-001", spawn_ts, task.id)
    monkeypatch.setenv("ZENITH_HANDOFF_PATH", str(handoff_path))
    monkeypatch.setenv("ZENITH_NODE_ID", task.id)
    monkeypatch.setenv("ZENITH_NODE_TYPE", task.type)
    runner = ACPNodeRunner(config=config, loader=AssetLoader(config))
    mcp_processes: list[asyncio.subprocess.Process] = []
    acp_processes: list[asyncio.subprocess.Process] = []
    registrations: list[RuntimeIdentityRegistration] = []
    original_spawn = asyncio.create_subprocess_shell
    original_register = runner._register_runtime_identity

    async def _no_op_server(*args, **kwargs):
        process = await asyncio.create_subprocess_exec(
            "sleep",
            "30",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        mcp_processes.append(process)
        return process

    async def _ready(*args, **kwargs):
        return None

    async def _spawn(*args, **kwargs):
        process = await original_spawn(*args, **kwargs)
        acp_processes.append(process)
        return process

    def _register(**kwargs):
        registration = original_register(**kwargs)
        registrations.append(registration)
        return registration

    async def _raise_flush(self) -> None:
        raise RuntimeError("flush failed")

    runner._start_worker_mcp_server = _no_op_server  # type: ignore[method-assign]
    runner._wait_for_server_ready = _ready  # type: ignore[method-assign]
    runner._register_runtime_identity = _register  # type: ignore[method-assign]
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _spawn)
    monkeypatch.setattr(acp_runner.ACPProgressTracker, "flush", _raise_flush)
    try:
        handoff = asyncio.run(
            runner.run_node(
                "p1",
                "mission-001",
                task,
                spawn_ts,
                project_setup,
            )
        )
        assert handoff.done is True
        assert mcp_processes[0].returncode is not None
        assert acp_processes[0].returncode is not None
        assert registrations[0].endpoint is None
    finally:
        for process in [*acp_processes, *mcp_processes]:
            if process.returncode is None:
                process.kill()


@pytest.mark.parametrize("failure_point", ["prompt_render", "identity_registration"])
def test_run_node_setup_failure_after_mcp_start_closes_mcp(
    failure_point: str,
    config: HarnessConfig,
    project_setup,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = Task(
        id=f"w-setup-{failure_point}",
        type="work",
        body="b",
        targets=[],
        skill="s",
    )
    runner = ACPNodeRunner(config=config, loader=AssetLoader(config))
    mcp_processes: list[asyncio.subprocess.Process] = []

    async def _no_op_server(*args, **kwargs):
        process = await asyncio.create_subprocess_exec(
            "sleep",
            "30",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        mcp_processes.append(process)
        return process

    async def _ready(*args, **kwargs):
        return None

    def _raise_setup(*args, **kwargs):
        raise RuntimeError(f"{failure_point} failed")

    runner._start_worker_mcp_server = _no_op_server  # type: ignore[method-assign]
    runner._wait_for_server_ready = _ready  # type: ignore[method-assign]
    if failure_point == "prompt_render":
        runner._render_prompts = _raise_setup  # type: ignore[method-assign]
    else:
        runner._register_runtime_identity = _raise_setup  # type: ignore[method-assign]
    try:
        with pytest.raises(RuntimeError, match=f"{failure_point} failed"):
            asyncio.run(
                runner.run_node(
                    "p1",
                    "mission-001",
                    task,
                    f"attempt-{failure_point}",
                    project_setup,
                )
            )
        assert mcp_processes[0].returncode is not None
    finally:
        for process in mcp_processes:
            if process.returncode is None:
                process.kill()


def test_run_node_spawn_failure_cleanup_is_independent(
    config: HarnessConfig,
    project_setup,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = Task(id="w-spawn-cleanup", type="work", body="b", targets=[], skill="s")
    runner = ACPNodeRunner(config=config, loader=AssetLoader(config))
    mcp_processes: list[asyncio.subprocess.Process] = []
    close_attempted = False

    class _ExplodingRegistration:
        endpoint = "@endpoint"
        capability = "capability"

        def environment(self) -> dict[str, str]:
            return {}

        def close(self) -> None:
            nonlocal close_attempted
            close_attempted = True
            raise RuntimeError("identity close failed")

    async def _no_op_server(*args, **kwargs):
        process = await asyncio.create_subprocess_exec(
            "sleep",
            "30",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        mcp_processes.append(process)
        return process

    async def _ready(*args, **kwargs):
        return None

    async def _spawn_failure(*args, **kwargs):
        raise RuntimeError("spawn failed")

    runner._start_worker_mcp_server = _no_op_server  # type: ignore[method-assign]
    runner._wait_for_server_ready = _ready  # type: ignore[method-assign]
    runner._register_runtime_identity = lambda **kwargs: _ExplodingRegistration()  # type: ignore[method-assign]
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _spawn_failure)
    try:
        with pytest.raises(RuntimeError, match="spawn failed"):
            asyncio.run(
                runner.run_node(
                    "p1",
                    "mission-001",
                    task,
                    "attempt-spawn-cleanup",
                    project_setup,
                )
            )
        assert close_attempted is True
        assert mcp_processes[0].returncode is not None
    finally:
        for process in mcp_processes:
            if process.returncode is None:
                process.kill()


def test_terminal_flush_exception_does_not_skip_cleanup(
    config: HarnessConfig,
    project_setup,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal_config = replace(
        config,
        terminal_reviewer_provider_name="claude",
        terminal_reviewer_acp_command=config.worker_acp_command,
    )
    runner = ACPNodeRunner(
        config=terminal_config,
        loader=AssetLoader(terminal_config),
    )
    mcp_processes: list[asyncio.subprocess.Process] = []
    acp_processes: list[asyncio.subprocess.Process] = []
    original_spawn = asyncio.create_subprocess_shell

    async def _no_op_server(*args, **kwargs):
        process = await asyncio.create_subprocess_exec(
            "sleep",
            "30",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        mcp_processes.append(process)
        return process

    async def _ready(*args, **kwargs):
        return None

    async def _spawn(*args, **kwargs):
        process = await original_spawn(*args, **kwargs)
        acp_processes.append(process)
        return process

    async def _raise_flush(self) -> None:
        raise RuntimeError("flush failed")

    runner._start_terminal_reviewer_mcp = _no_op_server  # type: ignore[method-assign]
    runner._wait_for_server_ready = _ready  # type: ignore[method-assign]
    monkeypatch.setattr(asyncio, "create_subprocess_shell", _spawn)
    monkeypatch.setattr(acp_runner.ACPProgressTracker, "flush", _raise_flush)
    try:
        with pytest.raises(RuntimeError, match="without calling"):
            asyncio.run(
                runner.run_terminal_review(
                    "p1",
                    "mission-001",
                    "attempt-flush-failure",
                    project_setup,
                )
            )
        assert mcp_processes[0].returncode is not None
        assert acp_processes[0].returncode is not None
    finally:
        for process in [*acp_processes, *mcp_processes]:
            if process.returncode is None:
                process.kill()


def test_run_node_stderr_tail_is_bounded_under_multimegabyte_output(
    config: HarnessConfig,
    project_setup,
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = Task(id="w-stderr-ring", type="work", body="b", targets=[], skill="s")
    spawn_ts = "attempt-stderr-ring"
    _prepare_runtime_identity(project_setup, workspace, task, spawn_ts)
    handoff_path = project_setup.attempt_path("p1", "mission-001", spawn_ts, task.id)
    monkeypatch.setenv("ZENITH_HANDOFF_PATH", str(handoff_path))
    monkeypatch.setenv("ZENITH_NODE_ID", task.id)
    monkeypatch.setenv("ZENITH_NODE_TYPE", task.type)
    monkeypatch.setenv("MOCK_ACP_STDERR_BYTES", str(3 * 1024 * 1024))
    runner = ACPNodeRunner(config=config, loader=AssetLoader(config))
    captured_tails: list[str] = []
    original_drain = acp_runner._drain_stream_chunks

    async def _recording_drain(stream):
        result = await original_drain(stream)
        captured_tails.append(result)
        return result

    async def _no_op_server(*args, **kwargs):
        return await asyncio.create_subprocess_exec(
            "sleep",
            "30",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

    async def _ready(*args, **kwargs):
        return None

    runner._start_worker_mcp_server = _no_op_server  # type: ignore[method-assign]
    runner._wait_for_server_ready = _ready  # type: ignore[method-assign]
    monkeypatch.setattr(acp_runner, "_drain_stream_chunks", _recording_drain)
    handoff = asyncio.run(
        runner.run_node(
            "p1",
            "mission-001",
            task,
            spawn_ts,
            project_setup,
        )
    )

    assert handoff.done is True
    assert len(captured_tails) == 1
    assert len(captured_tails[0].encode()) <= acp_runner.ACP_STDERR_TAIL_BYTES


def test_terminal_stderr_tail_is_bounded_under_multimegabyte_output(
    config: HarnessConfig,
    project_setup,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal_config = replace(
        config,
        terminal_reviewer_provider_name="claude",
        terminal_reviewer_acp_command=config.worker_acp_command,
    )
    runner = ACPNodeRunner(
        config=terminal_config,
        loader=AssetLoader(terminal_config),
    )
    monkeypatch.setenv("MOCK_ACP_STDERR_BYTES", str(3 * 1024 * 1024))
    captured_tails: list[str] = []
    original_drain = acp_runner._drain_stream_chunks

    async def _recording_drain(stream):
        result = await original_drain(stream)
        captured_tails.append(result)
        return result

    async def _no_op_server(*args, **kwargs):
        return await asyncio.create_subprocess_exec(
            "sleep",
            "30",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

    async def _ready(*args, **kwargs):
        return None

    runner._start_terminal_reviewer_mcp = _no_op_server  # type: ignore[method-assign]
    runner._wait_for_server_ready = _ready  # type: ignore[method-assign]
    monkeypatch.setattr(acp_runner, "_drain_stream_chunks", _recording_drain)
    with pytest.raises(RuntimeError, match="without calling"):
        asyncio.run(
            runner.run_terminal_review(
                "p1",
                "mission-001",
                "attempt-stderr-ring",
                project_setup,
            )
        )

    assert len(captured_tails) == 1
    assert len(captured_tails[0].encode()) <= acp_runner.ACP_STDERR_TAIL_BYTES


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
