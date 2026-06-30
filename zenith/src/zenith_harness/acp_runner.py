from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, ClassVar, Coroutine, Literal

from .assets import AssetLoader
from .config import HarnessConfig
from .dispatcher import DispatchRequest, NodeHandoff
from .models import (
    Task,
    TerminalReviewHandoff,
    ValidateHandoff,
    WorkHandoff,
)
from .storage import (
    ProjectStore,
    atomic_write_json,
)

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[str], Awaitable[None] | None]
SUBPROCESS_STREAM_LIMIT = int(
    os.environ.get(
        "ZENITH_SUBPROCESS_STREAM_LIMIT_BYTES",
        str(8 * 1024 * 1024),
    )
)


# ---------------------------------------------------------------------------
# Helpers (carried over from stable_version)
# ---------------------------------------------------------------------------


def _run_cmd(command: list[str], cwd: str | None = None, *, timeout: int = 10) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return (result.stdout or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _normalize_progress_text(text: str) -> str:
    return " ".join(text.split())


def _extract_text_fragments(payload: Any) -> list[str]:
    if payload is None:
        return []
    if isinstance(payload, str):
        return [payload]
    if isinstance(payload, list):
        out: list[str] = []
        for item in payload:
            out.extend(_extract_text_fragments(item))
        return out
    if isinstance(payload, dict):
        if payload.get("type") == "text" and isinstance(payload.get("text"), str):
            return [payload["text"]]
        if "content" in payload:
            return _extract_text_fragments(payload["content"])
    return []


def _truncate_text(text: str, *, limit: int = 280) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


class ACPError(Exception):
    pass


def _augment_acp_command(command: str, provider) -> str:
    """Append provider-specific config flags to the ACP launch command.

    For codex-acp this is the no-ask, no-sandbox combo — equivalent to
    `codex --dangerously-bypass-approvals-and-sandbox`, which codex-acp
    does not expose as a flag but accepts via `-c` overrides.

    For hermes the command is passed through unchanged.
    """
    name = getattr(provider, "name", None)
    if name == "codex":
        return (
            command
            + ' -c sandbox_mode="danger-full-access"'
            + ' -c approval_policy="never"'
            + ' -c model_reasoning_effort="xhigh"'
        )
    # hermes: no-op
    return command


def _acp_subprocess_env(provider) -> dict[str, str]:
    """Build the env handed to an ACP-agent subprocess.

    For codex we preserve PATH so node-based ACP adapters can launch via
    `/usr/bin/env node`, and pass sandbox-disable hints through env. The
    command line also receives `sandbox_mode="danger-full-access"` in
    `_augment_acp_command`.

    For hermes the env is passed through unchanged.
    """
    env = os.environ.copy()
    name = getattr(provider, "name", None)
    if name == "codex":
        # Env-var hints — harmless if codex ignores them.
        env["CODEX_SANDBOX"] = "danger-full-access"
        env["CODEX_DISABLE_SANDBOX"] = "1"
    # hermes: no special env needed
    return env


_NOT_FOUND = object()


async def _close_subprocess(process: asyncio.subprocess.Process, *, timeout: float = 5) -> None:
    if process.stdin is not None:
        try:
            process.stdin.close()
        except Exception:  # noqa: BLE001
            pass
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            process.kill()
        except OSError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except asyncio.TimeoutError:
            pass
    transport: object = getattr(process, "_transport", None)
    if transport is not None:
        try:
            getattr(transport, "close", lambda: None)()
        except Exception:  # noqa: BLE001
            pass


async def _wait_for_process_exit(
    process: asyncio.subprocess.Process, *, timeout: float = 5
) -> None:
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            process.kill()
        except OSError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except asyncio.TimeoutError:
            pass


async def _drain_stream_chunks(stream: asyncio.StreamReader | None) -> str:
    if stream is None:
        return ""
    chunks: list[str] = []
    try:
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            if text:
                chunks.append(text)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        return "".join(chunks)
    return "".join(chunks)


@dataclass
class ManagedTerminal:
    terminal_id: str
    process: asyncio.subprocess.Process
    output: bytearray = field(default_factory=bytearray)
    output_limit: int = 1024 * 1024
    exit_waiters: list[asyncio.Future] = field(default_factory=list)
    truncated: bool = False


@dataclass
class ACPProgressTracker:
    callback: ProgressCallback | None = None
    agent_message_id: str | None = None
    agent_buffer: str = ""
    last_emitted: str = ""

    async def handle_session_update(self, params: dict[str, Any]) -> None:
        update = params.get("update")
        if not isinstance(update, dict):
            return
        if update.get("sessionUpdate") == "agent_message_chunk":
            text = "".join(_extract_text_fragments(update.get("content")))
            if not text.strip():
                return
            mid = update.get("messageId")
            if mid and mid != self.agent_message_id:
                await self._flush()
                self.agent_message_id = str(mid)
            self.agent_buffer += text
            normalized = _normalize_progress_text(self.agent_buffer)
            if (
                "\n" in text
                or self.agent_buffer.rstrip().endswith((".", "!", "?", ":", ";"))
                or len(normalized) >= 160
            ):
                await self._flush()

    async def flush(self) -> None:
        await self._flush()

    async def _flush(self) -> None:
        msg = _normalize_progress_text(self.agent_buffer)
        self.agent_buffer = ""
        if not msg or self.callback is None or msg == self.last_emitted:
            return
        self.last_emitted = msg
        out = self.callback(f"Agent: {msg}")
        if inspect.isawaitable(out):
            await out


# ---------------------------------------------------------------------------
# ACP JSON-RPC client (unchanged from stable)
# ---------------------------------------------------------------------------


class ACPClient:
    def __init__(
        self,
        process: asyncio.subprocess.Process,
        working_dir: str,
        session_update_handler: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    ):
        self._process = process
        self._working_dir = working_dir
        self._session_update_handler = session_update_handler
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        self._terminals: dict[str, ManagedTerminal] = {}
        self._terminal_count = 0
        self._request_tasks: set[asyncio.Task] = set()
        self._closing = False

    async def start(self) -> None:
        self._reader_task = asyncio.create_task(self._read_loop())

    async def send_request(self, method: str, params: dict[str, Any]) -> Any:
        if self._closing:
            raise ACPError("ACP client is shutting down")
        self._request_id += 1
        rid = self._request_id
        msg = {"jsonrpc": "2.0", "method": method, "params": params, "id": rid}
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[rid] = future
        try:
            await self._write(msg)
        except Exception:
            self._pending.pop(rid, None)
            raise
        return await future

    async def _write(self, msg: dict[str, Any]) -> None:
        assert self._process.stdin is not None
        data = json.dumps(msg).encode("utf-8") + b"\n"
        self._process.stdin.write(data)
        await self._process.stdin.drain()

    async def _read_loop(self) -> None:
        assert self._process.stdout is not None
        try:
            while line := await self._process.stdout.readline():
                txt = line.decode("utf-8", errors="replace").strip()
                if not txt:
                    continue
                try:
                    data = json.loads(txt)
                except json.JSONDecodeError:
                    continue
                entries = data if isinstance(data, list) else [data]
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    if "result" in entry or "error" in entry:
                        self._handle_response(entry)
                    elif "method" in entry:
                        task = asyncio.create_task(self._handle_request(entry))
                        self._request_tasks.add(task)
                        task.add_done_callback(self._request_tasks.discard)
        except (BrokenPipeError, ConnectionResetError, OSError, asyncio.CancelledError):
            pass
        finally:
            for t in list(self._request_tasks):
                t.cancel()
            err = "ACP client shutting down" if self._closing else "ACP process exited"
            for rid, fut in self._pending.items():
                if not fut.done():
                    fut.set_exception(ACPError(err))
            self._pending.clear()

    def _handle_response(self, data: dict[str, Any]) -> None:
        rid = data.get("id")
        if rid is not None and rid in self._pending:
            fut = self._pending.pop(rid)
            if "error" in data:
                fut.set_exception(ACPError(str(data["error"])))
            else:
                fut.set_result(data.get("result"))

    async def _handle_request(self, data: dict[str, Any]) -> None:
        method = data["method"]
        params = data.get("params", {})
        rid = data.get("id")
        try:
            result = await self._dispatch(method, params)
        except Exception as e:  # noqa: BLE001
            if rid is not None:
                await self._write(
                    {"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": str(e)}}
                )
            return
        if rid is not None:
            if result is _NOT_FOUND:
                await self._write(
                    {
                        "jsonrpc": "2.0",
                        "id": rid,
                        "error": {"code": -32601, "message": "Method not found"},
                    }
                )
            else:
                await self._write(
                    {
                        "jsonrpc": "2.0",
                        "id": rid,
                        "result": result if result is not None else {},
                    }
                )

    async def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        if method == "session/update":
            if self._session_update_handler is not None:
                try:
                    out = self._session_update_handler(params)
                    if inspect.isawaitable(out):
                        await out
                except Exception:  # noqa: BLE001
                    pass
            return None
        if method == "session/request_permission":
            options = params.get("options", [])
            allow = next(
                (o for o in options if o.get("kind") == "allow_once"),
                options[0] if options else {"optionId": "allow"},
            )
            return {
                "outcome": {
                    "optionId": allow.get("optionId", "allow"),
                    "outcome": "selected",
                }
            }
        if method == "fs/read_text_file":
            return self._handle_fs_read(params)
        if method == "fs/write_text_file":
            return self._handle_fs_write(params)
        if method == "terminal/create":
            return await self._handle_terminal_create(params)
        if method == "terminal/output":
            return self._handle_terminal_output(params)
        if method == "terminal/wait_for_exit":
            return await self._handle_terminal_wait(params)
        if method in ("terminal/release", "terminal/kill"):
            return self._handle_terminal_release(params)
        return _NOT_FOUND

    def _handle_fs_read(self, params: dict[str, Any]) -> dict[str, str]:
        path = Path(params.get("path", ""))
        if not path.is_absolute():
            path = Path(self._working_dir) / path
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            line = params.get("line")
            limit = params.get("limit")
            if line is not None:
                line = max(0, int(line) - 1)
                lines = text.splitlines()
                if limit is not None:
                    text = "\n".join(lines[line : line + int(limit)])
                else:
                    text = "\n".join(lines[line:])
        except OSError:
            text = ""
        return {"content": text}

    def _handle_fs_write(self, params: dict[str, Any]) -> dict[str, Any]:
        path = Path(params["path"])
        if not path.is_absolute():
            path = Path(self._working_dir) / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(params["content"], encoding="utf-8")
        return {}

    async def _handle_terminal_create(self, params: dict[str, Any]) -> dict[str, str]:
        self._terminal_count += 1
        terminal_id = f"terminal-{self._terminal_count}"
        cmd = params.get("command", "")
        args = params.get("args") or []
        cwd = params.get("cwd") or self._working_dir
        env_list = params.get("env") or []
        output_limit = params.get("outputByteLimit") or 1024 * 1024
        env = os.environ.copy()
        for var in env_list:
            env[var["name"]] = var["value"]
        full_cmd = " ".join([cmd, *args])
        process = await asyncio.create_subprocess_shell(
            full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
            env=env,
            limit=SUBPROCESS_STREAM_LIMIT,
        )
        terminal = ManagedTerminal(
            terminal_id=terminal_id, process=process, output_limit=output_limit
        )
        self._terminals[terminal_id] = terminal
        asyncio.create_task(self._read_terminal_output(terminal))
        return {"terminalId": terminal_id}

    async def _read_terminal_output(self, terminal: ManagedTerminal) -> None:
        assert terminal.process.stdout is not None
        try:
            while chunk := await terminal.process.stdout.read(4096):
                if terminal.truncated:
                    continue
                if len(terminal.output) + len(chunk) > terminal.output_limit:
                    terminal.truncated = True
                    remaining = terminal.output_limit - len(terminal.output)
                    terminal.output.extend(chunk[:remaining])
                    continue
                terminal.output.extend(chunk)
        except Exception:  # noqa: BLE001
            pass
        await terminal.process.wait()
        for w in terminal.exit_waiters:
            if not w.done():
                w.set_result((terminal.process.returncode, None))

    def _handle_terminal_output(self, params: dict[str, Any]) -> dict[str, Any]:
        tid = params.get("terminalId", "")
        t = self._terminals.get(tid)
        if t is None:
            return {"output": "", "truncated": False}
        out: dict[str, Any] = {
            "output": t.output.decode("utf-8", errors="replace"),
            "truncated": t.truncated,
        }
        if t.process.returncode is not None:
            out["exitStatus"] = {"exitCode": t.process.returncode}
        return out

    async def _handle_terminal_wait(self, params: dict[str, Any]) -> dict[str, Any]:
        tid = params.get("terminalId", "")
        t = self._terminals.get(tid)
        if t is None:
            return {"exitCode": -1, "signal": None}
        if t.process.returncode is not None:
            return {"exitCode": t.process.returncode, "signal": None}
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        t.exit_waiters.append(fut)
        code, sig = await fut
        return {"exitCode": code, "signal": sig}

    def _handle_terminal_release(self, params: dict[str, Any]) -> dict[str, Any]:
        tid = params.get("terminalId", "")
        t = self._terminals.pop(tid, None)
        if t and t.process.returncode is None:
            try:
                t.process.terminate()
            except OSError:
                pass
        return {}

    async def cleanup(self, *, close_main_process: bool = True) -> None:
        self._closing = True
        for t in self._terminals.values():
            if t.process.returncode is None:
                try:
                    t.process.terminate()
                except OSError:
                    pass
            await _close_subprocess(t.process, timeout=5)
        self._terminals.clear()
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if close_main_process:
            await _close_subprocess(self._process, timeout=5)


# ---------------------------------------------------------------------------
# ACPNodeRunner — the v5 equivalent of the stable ACPWorkerRunner
# ---------------------------------------------------------------------------


@dataclass
class ACPNodeRunner:
    """Runs ONE node end-to-end via ACP + worker MCP server subprocess."""

    supports_progress_updates: ClassVar[bool] = True
    config: HarnessConfig
    loader: AssetLoader

    @staticmethod
    def _find_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    async def run_node(
        self,
        project_id: str,
        mission_id: str,
        task: Task,
        spawn_ts: str,
        store: ProjectStore,
        *,
        cwd: str | Path | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> NodeHandoff:
        """Spawn the worker MCP server + ACP agent; poll the attempt file; return the handoff."""
        role: Literal["validator", "worker"] = (
            "validator" if task.type == "validate" else "worker"
        )
        role_config = self.config.for_role(role)
        acp_command = role_config.worker_acp_command or role_config.resolved_worker_acp_command
        if not acp_command:
            raise RuntimeError(
                f"No ACP command for role={role}. Set ZENITH_{role.upper()}_ACP_COMMAND."
            )
        acp_command = _augment_acp_command(acp_command, role_config.worker_provider)

        workspace_dir = str(Path(cwd).expanduser().resolve() if cwd else store.workspace_dir(project_id))
        project_bucket = str(store.zenith_dir(project_id))
        handoff_path = store.attempt_path(project_id, mission_id, spawn_ts, task.id)
        handoff_path.parent.mkdir(parents=True, exist_ok=True)

        # 0) For claude-agent-acp: drop a project-level settings.json that
        #    overrides the user's global ~/.claude/settings.json. Adapter
        #    rejects session/new with `Invalid permissions.defaultMode: auto`
        #    if the user's global setting carries the SDK-unsupported "auto"
        #    default.
        _ensure_claude_settings(Path(workspace_dir), role_config.worker_provider)

        # 1) Start the worker MCP server subprocess.
        mcp_port = self._find_free_port()
        mcp_process = await self._start_worker_mcp_server(
            task=task,
            project_id=project_id,
            mission_id=mission_id,
            handoff_path=str(handoff_path),
            workspace_dir=workspace_dir,
            mcp_port=mcp_port,
        )
        try:
            await self._wait_for_server_ready("127.0.0.1", mcp_port)
        except TimeoutError:
            if mcp_process.returncode is None:
                mcp_process.terminate()
            await _close_subprocess(mcp_process, timeout=5)
            return self._synthesize_missing_handoff(
                task, summary="Worker MCP server failed to start"
            )

        worker_mcp_cfg = {
            "type": "http",
            "name": "zenith-worker",
            "url": f"http://127.0.0.1:{mcp_port}/mcp",
            "headers": [],
            "env": [],
        }

        # 2) Render the prompt (system + template merged into one first message).
        first_message = self._render_prompts(
            task=task,
            mission_id=mission_id,
            project_bucket=project_bucket,
            workspace_dir=workspace_dir,
            store=store,
            project_id=project_id,
        )

        # 3) Spawn the ACP agent.
        process = await asyncio.create_subprocess_shell(
            acp_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workspace_dir,
            env=_acp_subprocess_env(role_config.worker_provider),
            limit=SUBPROCESS_STREAM_LIMIT,
        )
        progress_tracker = ACPProgressTracker(callback=progress_callback)
        client = ACPClient(
            process,
            workspace_dir,
            session_update_handler=progress_tracker.handle_session_update,
        )
        await client.start()
        prompt_stop_reason: str | None = None
        session_error: str | None = None
        worker_exit_code: int | None = None
        worker_stderr: str = ""
        stderr_task = asyncio.create_task(_drain_stream_chunks(process.stderr))

        try:
            await client.send_request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": True, "writeTextFile": True},
                        "terminal": True,
                    },
                    "clientInfo": {"name": "zenith", "version": "0.1.0"},
                },
            )
            session_params: dict[str, Any] = {
                "cwd": workspace_dir,
                "mcpServers": [worker_mcp_cfg],
            }
            provider = role_config.worker_provider
            session_resp = await client.send_request("session/new", session_params)
            session_id = session_resp["sessionId"]
            await self._maybe_set_mode(client, session_id, provider)

            prompt_result = await client.send_request(
                "session/prompt",
                {"prompt": [{"type": "text", "text": first_message}], "sessionId": session_id},
            )
            if isinstance(prompt_result, dict):
                sr = prompt_result.get("stopReason")
                if isinstance(sr, str):
                    prompt_stop_reason = sr

            # 4) Give the worker MCP server a short grace period to flush.
            await self._poll_attempt_file(handoff_path, timeout=2.0)
        except Exception as exc:  # noqa: BLE001
            session_error = str(exc)
            logger.error("ACP session failed for node %s: %s", task.id, exc)
        finally:
            await progress_tracker.flush()
            if process.returncode is None:
                try:
                    await asyncio.wait_for(process.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    try:
                        process.terminate()
                    except OSError:
                        pass
            await _wait_for_process_exit(process, timeout=5)
            worker_exit_code = process.returncode
            try:
                worker_stderr = _truncate_text(
                    await asyncio.wait_for(stderr_task, timeout=0.5), limit=2000
                )
            except (asyncio.TimeoutError, Exception):
                worker_stderr = ""
            await client.cleanup(close_main_process=False)
            await _close_subprocess(process, timeout=0)
            if mcp_process.returncode is None:
                try:
                    mcp_process.terminate()
                except OSError:
                    pass
            await _close_subprocess(mcp_process, timeout=5)

        # 5) Parse and return.
        if handoff_path.exists():
            return self._parse_handoff_file(handoff_path, task)
        return self._synthesize_and_persist_missing_handoff(
            handoff_path=handoff_path,
            task=task,
            stop_reason=prompt_stop_reason,
            exit_code=worker_exit_code,
            stderr=worker_stderr,
            session_error=session_error,
        )

    async def run_terminal_review(
        self,
        project_id: str,
        mission_id: str,
        spawn_ts: str,
        store: ProjectStore,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> TerminalReviewHandoff:
        """Adversarial fresh-context terminal review."""
        role_config = self.config.for_role("terminal_reviewer")
        acp_command = role_config.worker_acp_command
        if not acp_command:
            raise RuntimeError(
                "No ACP command for terminal reviewer. "
                "Set ZENITH_TERMINAL_REVIEWER_ACP_COMMAND."
            )
        acp_command = _augment_acp_command(acp_command, role_config.worker_provider)

        workspace_dir = str(store.workspace_dir(project_id))
        project_bucket = str(store.zenith_dir(project_id))
        report_path = store.terminal_review_path(project_id, mission_id, spawn_ts)
        report_path.parent.mkdir(parents=True, exist_ok=True)

        # Same claude-agent-acp settings workaround as run_node.
        _ensure_claude_settings(Path(workspace_dir), role_config.worker_provider)

        mcp_port = self._find_free_port()
        mcp_process = await self._start_terminal_reviewer_mcp(
            project_id=project_id,
            mission_id=mission_id,
            report_path=str(report_path),
            workspace_dir=workspace_dir,
            mcp_port=mcp_port,
        )
        try:
            await self._wait_for_server_ready("127.0.0.1", mcp_port)
        except TimeoutError:
            if mcp_process.returncode is None:
                mcp_process.terminate()
            await _close_subprocess(mcp_process, timeout=5)
            raise RuntimeError(
                "Terminal reviewer MCP server failed to start; cannot run terminal review"
            )

        worker_mcp_cfg = {
            "type": "http",
            "name": "zenith-terminal-reviewer",
            "url": f"http://127.0.0.1:{mcp_port}/mcp",
            "headers": [],
            "env": [],
        }

        first_message = self._render_terminal_reviewer_prompts(
            project_bucket=project_bucket,
            workspace_dir=workspace_dir,
        )

        process = await asyncio.create_subprocess_shell(
            acp_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workspace_dir,
            env=_acp_subprocess_env(role_config.worker_provider),
            limit=SUBPROCESS_STREAM_LIMIT,
        )
        tracker = ACPProgressTracker(callback=progress_callback)
        client = ACPClient(
            process, workspace_dir, session_update_handler=tracker.handle_session_update
        )
        await client.start()
        try:
            await client.send_request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": True, "writeTextFile": True},
                        "terminal": True,
                    },
                    "clientInfo": {"name": "zenith", "version": "0.1.0"},
                },
            )
            session_params: dict[str, Any] = {
                "cwd": workspace_dir,
                "mcpServers": [worker_mcp_cfg],
            }
            provider = role_config.worker_provider
            session_resp = await client.send_request("session/new", session_params)
            session_id = session_resp["sessionId"]
            await self._maybe_set_mode(client, session_id, provider)
            await client.send_request(
                "session/prompt",
                {
                    "prompt": [{"type": "text", "text": first_message}],
                    "sessionId": session_id,
                },
            )
            await self._poll_attempt_file(report_path, timeout=2.0)
        finally:
            await tracker.flush()
            if process.returncode is None:
                try:
                    process.terminate()
                except OSError:
                    pass
            await _wait_for_process_exit(process, timeout=5)
            await client.cleanup(close_main_process=False)
            await _close_subprocess(process, timeout=0)
            if mcp_process.returncode is None:
                try:
                    mcp_process.terminate()
                except OSError:
                    pass
            await _close_subprocess(mcp_process, timeout=5)

        if report_path.exists():
            return TerminalReviewHandoff.model_validate_json(report_path.read_text())
        raise RuntimeError(
            "Terminal reviewer exited without calling submit_terminal_review; "
            "no terminal review was written. The mission cannot be sealed as done "
            "without an explicit reviewer verdict."
        )

    # ------------------------------------------------------------------
    # Subprocess plumbing
    # ------------------------------------------------------------------

    async def _start_worker_mcp_server(
        self,
        *,
        task: Task,
        project_id: str,
        mission_id: str,
        handoff_path: str,
        workspace_dir: str,
        mcp_port: int,
    ) -> asyncio.subprocess.Process:
        cmd = [
            sys.executable,
            "-m",
            "zenith_harness",
            "--mode",
            "worker",
            "--transport",
            "streamable-http",
            "--host",
            "127.0.0.1",
            "--port",
            str(mcp_port),
        ]
        env = os.environ.copy()
        env["ZENITH_HOME"] = str(self.config.harness_home)
        env["ZENITH_PROJECT_ID"] = project_id
        env["ZENITH_MISSION_ID"] = mission_id
        env["ZENITH_NODE_ID"] = task.id
        env["ZENITH_NODE_TYPE"] = task.type
        env["ZENITH_HANDOFF_PATH"] = handoff_path
        return await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workspace_dir,
            env=env,
            limit=SUBPROCESS_STREAM_LIMIT,
        )

    async def _start_terminal_reviewer_mcp(
        self,
        *,
        project_id: str,
        mission_id: str,
        report_path: str,
        workspace_dir: str,
        mcp_port: int,
    ) -> asyncio.subprocess.Process:
        cmd = [
            sys.executable,
            "-m",
            "zenith_harness",
            "--mode",
            "terminal-reviewer",
            "--transport",
            "streamable-http",
            "--host",
            "127.0.0.1",
            "--port",
            str(mcp_port),
        ]
        env = os.environ.copy()
        env["ZENITH_PROJECT_ID"] = project_id
        env["ZENITH_MISSION_ID"] = mission_id
        env["ZENITH_TERMINAL_REVIEW_PATH"] = report_path
        return await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workspace_dir,
            env=env,
            limit=SUBPROCESS_STREAM_LIMIT,
        )

    async def _wait_for_server_ready(self, host: str, port: int, *, timeout: float = 15) -> None:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                _, writer = await asyncio.open_connection(host, port)
                writer.close()
                await writer.wait_closed()
                return
            except (ConnectionRefusedError, OSError):
                await asyncio.sleep(0.3)
        raise TimeoutError(f"MCP server on {host}:{port} not ready within {timeout}s")

    async def _poll_attempt_file(self, path: Path, *, timeout: float) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            if path.exists():
                return True
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(0.1)

    async def _maybe_set_mode(
        self, client: ACPClient, session_id: str, provider
    ) -> None:
        mode = getattr(provider, "acp_runtime_mode", None)
        if not mode:
            return
        try:
            await client.send_request(
                "session/set_mode", {"sessionId": session_id, "modeId": mode}
            )
        except ACPError as exc:
            raise ACPError(
                f"Failed to set ACP runtime mode {mode!r} for {provider.name}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Prompt rendering
    # ------------------------------------------------------------------

    def _render_prompts(
        self,
        *,
        task: Task,
        mission_id: str,
        project_bucket: str,
        workspace_dir: str,
        store: ProjectStore,
        project_id: str,
    ) -> str:
        session_type = "validator" if task.type == "validate" else "worker"
        system_prompt = self.loader.load_prompt_file(session_type, "system_prompt.md")
        template_vars = self._build_template_vars(
            task=task,
            mission_id=mission_id,
            project_bucket=project_bucket,
            workspace_dir=workspace_dir,
            store=store,
            project_id=project_id,
        )
        template = self.loader.render_prompt_template(session_type, "template.md", template_vars)
        if system_prompt:
            return system_prompt + "\n\n---\n\n" + template
        return template

    def _render_terminal_reviewer_prompts(
        self,
        *,
        project_bucket: str,
        workspace_dir: str,
    ) -> str:
        brief_path = Path(project_bucket) / "brief.md"
        brief_text = brief_path.read_text() if brief_path.exists() else ""
        return self.loader.render_prompt_template(
            "terminal-reviewer",
            "system_prompt.md",
            {
                "user_request": brief_text,
                "workspace": workspace_dir,
            },
        )

    def _build_template_vars(
        self,
        *,
        task: Task,
        mission_id: str,
        project_bucket: str,
        workspace_dir: str,
        store: ProjectStore,
        project_id: str,
    ) -> dict[str, str]:
        assertions: list[str] = []
        target_rows: list[str] = []
        for aid in task.targets:
            contract_p = store.contract_assertion_path(project_id, mission_id, aid)
            target_rows.append(f"- **{aid}**: `{contract_p}`")
            body = store.load_contract_assertion(project_id, mission_id, aid)
            if body is None:
                assertions.append(f"[Missing contract assertion {aid} at {contract_p}]\n")
                continue
            assertions.append(body.rstrip() + "\n")
        target_paths = "\n".join(target_rows) if target_rows else ""
        mission_dir = store.mission_dir(project_id, mission_id)
        project_bucket_path = Path(project_bucket)
        agents_path = Path(workspace_dir) / "AGENTS.md"
        return {
            "assignment_body": task.body,
            "contract_target_paths": target_paths,
            "memory_path": str(project_bucket_path / "MEMORY.md"),
            "mission_scope_path": str(mission_dir / "SCOPE.md"),
            "agents_path": str(agents_path),
            "attempts_dir": str(store.attempts_dir(project_id, mission_id)),
            # Legacy names are retained for validator templates and provider
            # prompts that have not yet been migrated from node vocabulary.
            "node_id": task.id,
            "node_type": task.type,
            "node_body": task.body,
            "node_targets": ", ".join(task.targets),
            "skill_name": task.skill or "",
            "workspace": workspace_dir,
            "project_bucket": project_bucket,
            "mission_id": mission_id,
            "contract_assertions": "\n\n---\n\n".join(assertions),
            "target_paths": target_paths,
            "regressions_dir": str(store.regressions_dir(project_id, mission_id)),
            "evidence_dir": str(mission_dir / "evidence"),
        }

    # ------------------------------------------------------------------
    # Handoff parsing + synthesis
    # ------------------------------------------------------------------

    def _parse_handoff_file(self, path: Path, task: Task) -> NodeHandoff:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if task.type == "validate":
            return ValidateHandoff.model_validate(data)
        return WorkHandoff.model_validate(data)

    def _synthesize_missing_handoff(
        self, task: Task, *, summary: str = ""
    ) -> NodeHandoff:
        report = summary or "Agent session ended without calling end_node."
        if task.type == "validate":
            return ValidateHandoff(
                node_id=task.id, done=False, report=report, items=[], passed=False
            )
        return WorkHandoff(
            node_id=task.id,
            done=False,
            report=report,
            request_attention=False,
        )

    def _synthesize_and_persist_missing_handoff(
        self,
        *,
        handoff_path: Path,
        task: Task,
        stop_reason: str | None,
        exit_code: int | None,
        stderr: str,
        session_error: str | None,
    ) -> NodeHandoff:
        parts: list[str] = ["Agent session ended without calling end_node."]
        if session_error:
            parts.append(f"acp_error={session_error}")
        if stop_reason:
            parts.append(f"stop_reason={stop_reason}")
        if exit_code is not None:
            parts.append(f"exit_code={exit_code}")
        if stderr:
            parts.append(f"stderr={stderr}")
        summary = " ".join(parts)
        handoff = self._synthesize_missing_handoff(task, summary=summary)
        atomic_write_json(handoff_path, handoff.model_dump(mode="json"))
        return handoff


# ---------------------------------------------------------------------------
# Production NodeDispatcher / TerminalReviewer wrappers
# ---------------------------------------------------------------------------


def _run_coro_blocking(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run an async coroutine to completion from sync code.

    Uses `asyncio.run` when no event loop is active. When the caller is
    already inside a running loop (e.g. an MCP tool handler that forgot
    to wrap with `asyncio.to_thread`), execute the coroutine in a fresh
    loop on a worker thread instead of crashing.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Inside a running loop: hop to a worker thread with its own loop.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class ACPNodeDispatcher:
    """Implements `NodeDispatcher` by calling `ACPNodeRunner.run_node`."""

    def __init__(self, config: HarnessConfig, store: ProjectStore | None = None):
        self.config = config
        self.store = store or ProjectStore(config)
        self.loader = AssetLoader(config)
        self.runner = ACPNodeRunner(config=config, loader=self.loader)

    def dispatch(self, request: DispatchRequest) -> NodeHandoff:
        return _run_coro_blocking(
            self.runner.run_node(
                project_id=request.project_id,
                mission_id=request.mission_id,
                task=request.task,
                spawn_ts=request.spawn_ts,
                store=self.store,
                cwd=request.cwd,
            )
        )

    def dispatch_batch(self, requests: list[DispatchRequest]) -> list[NodeHandoff]:
        async def _run_all() -> list[NodeHandoff]:
            results = await asyncio.gather(
                *(
                    self.runner.run_node(
                        project_id=request.project_id,
                        mission_id=request.mission_id,
                        task=request.task,
                        spawn_ts=request.spawn_ts,
                        store=self.store,
                        cwd=request.cwd,
                    )
                    for request in requests
                ),
                return_exceptions=True,
            )
            handoffs: list[NodeHandoff] = []
            for request, result in zip(requests, results, strict=True):
                if isinstance(result, BaseException):
                    handoffs.append(
                        self.runner._synthesize_missing_handoff(
                            request.task,
                            summary=f"Dispatcher crashed: {result}",
                        )
                    )
                else:
                    handoffs.append(result)
            return handoffs

        return _run_coro_blocking(_run_all())


class ACPTerminalReviewer:
    """Implements `TerminalReviewer` by calling `ACPNodeRunner.run_terminal_review`."""

    def __init__(self, config: HarnessConfig, store: ProjectStore | None = None):
        self.config = config
        self.store = store or ProjectStore(config)
        self.loader = AssetLoader(config)
        self.runner = ACPNodeRunner(config=config, loader=self.loader)

    def review(
        self, project_id: str, mission_id: str, spawn_ts: str
    ) -> TerminalReviewHandoff:
        return _run_coro_blocking(
            self.runner.run_terminal_review(
                project_id=project_id,
                mission_id=mission_id,
                spawn_ts=spawn_ts,
                store=self.store,
            )
        )


# ---------------------------------------------------------------------------
# claude-agent-acp settings workaround
# ---------------------------------------------------------------------------


def _ensure_claude_settings(workspace: Path, provider) -> None:
    """Write `<workspace>/.claude/settings.json` overriding `permissions.defaultMode`.

    The `@zed-industries/claude-agent-acp` adapter loads settings as
    user → project → local → enterprise (last write wins). Without this, a
    user with `"permissions": {"defaultMode": "auto"}` in their global
    `~/.claude/settings.json` will see session/new fail with
    `Invalid permissions.defaultMode: auto.` — the Claude Code SDK does not
    accept "auto".

    We touch this file only when:
    - The provider declares a non-empty `acp_runtime_mode` (i.e. claude).
    - The file does not already exist (respect any user-authored override).

    In v5 the workspace is the user's repo, so we conservatively no-op on
    pre-existing files.
    """
    mode = getattr(provider, "acp_runtime_mode", None)
    if not mode:
        return
    claude_dir = workspace / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    settings_path = claude_dir / "settings.json"
    if settings_path.exists():
        # Respect user-authored settings; the user can put whatever they want
        # in there. If their setting is "auto" we can't help — they need to
        # change it manually.
        return
    settings_path.write_text(
        json.dumps({"permissions": {"defaultMode": mode}}, indent=2) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "ACPClient",
    "ACPError",
    "ACPNodeRunner",
    "ACPNodeDispatcher",
    "ACPTerminalReviewer",
    "ACPProgressTracker",
    "SUBPROCESS_STREAM_LIMIT",
]
