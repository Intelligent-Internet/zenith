from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import tomllib
from pathlib import Path

import click

from .assets import AssetLoader, iter_skill_directories
from .config import HarnessConfig
from .envelope import render_task_list
from .providers import (
    ProviderDefinition,
    ProviderSelection,
    default_worker_provider_name,
    get_provider,
    provider_names_for_role,
)
from .storage import ProjectStore

MCP_ENV_FORWARD_ALLOWLIST = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
    "CLAUDE_CODE_EFFORT_LEVEL",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS",
    "CLAUDE_CODE_SUBAGENT_MODEL",
    "GLM_API_KEY",
    "GLM_BASE_URL",
    "MAX_THINKING_TOKENS",
    "ZAI_API_KEY",
    "ZAI_BASE_URL",
)

USER_SCOPE_ORCHESTRATORS = ("claude", "codex")


@click.group()
def cli() -> None:
    """Zenith CLI — set up + inspect long-running coding projects."""


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "--agent",
    type=click.Choice(provider_names_for_role("orchestrator")),
    default=None,
    help="Convenience: sets orchestrator+worker provider in one shot.",
)
@click.option(
    "--orchestrator-provider",
    type=click.Choice(provider_names_for_role("orchestrator")),
    default=None,
)
@click.option(
    "--worker-provider",
    type=click.Choice(provider_names_for_role("worker")),
    default=None,
)
@click.option("--worker-acp-command", default=None)
@click.option("--validator-provider", type=click.Choice(provider_names_for_role("worker")), default=None)
@click.option("--validator-acp-command", default=None)
@click.option("--terminal-reviewer-provider", type=click.Choice(provider_names_for_role("worker")), default=None)
@click.option("--terminal-reviewer-acp-command", default=None)
@click.option("--zenith-home", type=click.Path(), default=None)
@click.option(
    "--scope",
    type=click.Choice(("project", "user")),
    default="project",
    show_default=True,
    help="Install into one project or the current user's host configuration.",
)
@click.option("--workspace-dir", "workspace_dir", type=click.Path(exists=True), default=None)
def init(
    agent: str | None,
    orchestrator_provider: str | None,
    worker_provider: str | None,
    worker_acp_command: str | None,
    validator_provider: str | None,
    validator_acp_command: str | None,
    terminal_reviewer_provider: str | None,
    terminal_reviewer_acp_command: str | None,
    zenith_home: str | None,
    scope: str,
    workspace_dir: str | None,
) -> None:
    """Initialize Zenith's host-agent surface.

    Project scope (the default) stages MCP config and assets in one workspace.
    User scope registers Zenith and installs its assets once for every workspace
    in Claude Code or Codex. In both scopes, the project bucket is created lazily
    by `start_project` at the first MCP call.
    """
    config = HarnessConfig.discover()
    loader = AssetLoader(config)
    selection = _resolve_selection(
        agent=agent,
        orchestrator=orchestrator_provider,
        worker=worker_provider,
        worker_acp_command=worker_acp_command,
        validator=validator_provider,
        validator_acp_command=validator_acp_command,
        terminal_reviewer=terminal_reviewer_provider,
        terminal_reviewer_acp_command=terminal_reviewer_acp_command,
    )

    if scope == "user":
        if workspace_dir is not None:
            raise click.UsageError("--workspace-dir cannot be used with --scope user")
        if selection.orchestrator.name not in USER_SCOPE_ORCHESTRATORS:
            supported = ", ".join(USER_SCOPE_ORCHESTRATORS)
            raise click.UsageError(
                f"--scope user supports these orchestrators: {supported}; "
                f"use --scope project for {selection.orchestrator.name}"
            )
        storage_env = _storage_env(
            zenith_home=zenith_home,
            workspace=Path.cwd(),
            selection=selection,
        )
        _write_user_bootstrap_config(selection, storage_env)
        _setup_user_provider_assets(loader, selection.orchestrator)
        _echo_user_next_steps(selection)
        return

    workspace = Path(workspace_dir or ".").resolve()

    # 1) MCP / Codex config
    storage_env = _storage_env(zenith_home=zenith_home, workspace=workspace, selection=selection)
    _write_bootstrap_config(workspace, selection, storage_env)

    # 2) Per-provider agents + orchestrator prompt
    for provider in selection.providers():
        _setup_provider_assets(workspace, loader, provider)

    click.echo(
        f"\nInitialized v5 project workspace at {workspace}: "
        f"orchestrator={selection.orchestrator.name}, "
        f"worker={selection.worker.name}, "
        f"validator={selection.resolved_validation_worker.name}."
    )
    click.echo(
        "Bucket lives at $ZENITH_HOME/projects/<pid>/ — created on the first "
        "`start_project(brief, workspace_dir)` call."
    )
    _echo_next_steps(selection.orchestrator)


# ---------------------------------------------------------------------------
# install-skills
# ---------------------------------------------------------------------------


@cli.command("install-skills")
@click.option("--target", type=click.Path(), required=True)
def install_skills_cmd(target: str) -> None:
    """Install bundled skills to a target directory (e.g. <ws>/.zenith/skills/)."""
    config = HarnessConfig.discover()
    loader = AssetLoader(config)
    _copy_skills(loader, Path(target).resolve())
    click.echo(f"Installed bundled skills to {target}")


# ---------------------------------------------------------------------------
# list-projects
# ---------------------------------------------------------------------------


@cli.command("list-projects")
def list_projects_cmd() -> None:
    """List all projects in HARNESS bucket."""
    store = ProjectStore(HarnessConfig.discover())
    projects = store.list_projects()
    if not projects:
        click.echo("No projects.")
        return
    for p in projects:
        click.echo(f"  {p.id}   ws={p.workspace_dir}   created={p.created_at}")


# ---------------------------------------------------------------------------
# show-project
# ---------------------------------------------------------------------------


@cli.command("show-project")
@click.argument("project_id")
def show_project_cmd(project_id: str) -> None:
    """Show envelope + compact task list for a project."""
    store = ProjectStore(HarnessConfig.discover())
    try:
        record = store.load_project(project_id)
    except FileNotFoundError:
        raise click.ClickException(f"Project not found: {project_id}")
    state = store.load_state(project_id)
    click.echo(f"id:        {record.id}")
    click.echo(f"workspace: {record.workspace_dir}")
    click.echo(f"created:   {record.created_at}")
    click.echo(f"state:     {state.state if state else 'draft'}")
    mid = record.current_mission_id
    if mid:
        click.echo(f"mission:   {mid}")
        try:
            tl = store.load_task_list(record.id, mid)
            ts = store.load_task_state(record.id, mid)
            rendered = render_task_list(tl, ts)
            if rendered:
                click.echo("")
                click.echo(rendered)
        except FileNotFoundError:
            click.echo("  (task list not yet submitted)")


# ---------------------------------------------------------------------------
# inspect-tasks
# ---------------------------------------------------------------------------


@cli.command("inspect-tasks")
@click.option("--project", "project_id", required=True)
@click.option("--mission", "mission_id", default=None)
def inspect_tasks_cmd(project_id: str, mission_id: str | None) -> None:
    """Render the compact text task list for a mission."""
    store = ProjectStore(HarnessConfig.discover())
    if mission_id is None:
        mid_list = store.list_missions(project_id)
        if not mid_list:
            raise click.ClickException("no missions in this project")
        mission_id = mid_list[-1]
    try:
        tl = store.load_task_list(project_id, mission_id)
    except FileNotFoundError:
        raise click.ClickException(f"tasks.json not found for {project_id}/{mission_id}")
    ts = store.load_task_state(project_id, mission_id)
    rendered = render_task_list(tl, ts, mode="full")
    if rendered:
        click.echo(rendered)


# ---------------------------------------------------------------------------
# abort-project
# ---------------------------------------------------------------------------


@cli.command("abort-project")
@click.argument("project_id")
@click.option("--reason", required=True)
def abort_project_cmd(project_id: str, reason: str) -> None:
    """Mark a project Aborted (CLI-side: preserves tasks.json + attempts/)."""
    from .controller import ProjectController
    from .dispatcher import MockDispatcher, MockTerminalReviewer
    from .models import TerminalReviewHandoff, WorkHandoff

    config = HarnessConfig.discover()
    controller = ProjectController(
        config,
        MockDispatcher(lambda r: WorkHandoff(node_id=r.task.id, done=False, report="aborted")),
        MockTerminalReviewer(TerminalReviewHandoff(done=True, report="")),
    )
    env = controller.abort_project(project_id, reason)
    click.echo(f"Aborted {project_id}: state={env.state.state}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _copy_skills(loader: AssetLoader, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    bundled = loader.bundled_skills_dir()
    if not bundled.exists():
        click.echo(f"warning: bundled skills not found at {bundled}", err=True)
        return
    for skill_dir in iter_skill_directories(bundled):
        dest = target / skill_dir.name
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_dir / "SKILL.md", dest / "SKILL.md")


def _echo_user_next_steps(selection: ProviderSelection) -> None:
    provider = selection.orchestrator.name
    host = {"claude": "Claude Code", "codex": "Codex"}.get(provider, provider)
    click.echo(
        f"\nInitialized v5 user scope: orchestrator={provider}, "
        f"worker={selection.worker.name}, "
        f"validator={selection.resolved_validation_worker.name}."
    )
    click.echo("Zenith is available from every workspace for this user.")
    click.echo("")
    click.echo("Next:")
    click.echo(f"  1. Restart {host} or start a new session.")
    click.echo("  2. Run: /zenith <your instruction or query>")


def _echo_next_steps(orchestrator: ProviderDefinition) -> None:
    prompt_path = orchestrator.orchestrator_prompt_output_path
    click.echo("")
    click.echo("Next:")
    click.echo("  1. Start your agent from the initialized project workspace:")
    click.echo(f"     {orchestrator.name}")
    if prompt_path:
        click.echo("  2. Ask it:")
        click.echo(
            f"     First read {prompt_path} and treat it as your primary role, then use Zenith to run this mission."
        )
        click.echo("")
        click.echo("     <your instruction or query>")


def _resolve_selection(
    *,
    agent: str | None,
    orchestrator: str | None,
    worker: str | None,
    worker_acp_command: str | None,
    validator: str | None,
    validator_acp_command: str | None,
    terminal_reviewer: str | None,
    terminal_reviewer_acp_command: str | None,
) -> ProviderSelection:
    if agent and orchestrator and agent != orchestrator:
        raise click.UsageError("--agent conflicts with --orchestrator-provider")
    orch = orchestrator or agent or "claude"
    wrk = worker or (agent if agent in provider_names_for_role("worker") else None) or default_worker_provider_name(orch)
    return ProviderSelection(
        orchestrator=get_provider(orch),
        worker=get_provider(wrk),
        validation_worker=get_provider(validator) if validator else None,
        worker_acp_command=worker_acp_command,
        validation_worker_acp_command=validator_acp_command,
    )


def _storage_env(
    *,
    zenith_home: str | None,
    workspace: Path,
    selection: ProviderSelection,
) -> dict[str, str]:
    env: dict[str, str] = {}
    if zenith_home:
        env["ZENITH_HOME"] = str(Path(zenith_home).expanduser().resolve())
    return env


def _forwarded_mcp_env() -> dict[str, str]:
    return {
        key: value
        for key in MCP_ENV_FORWARD_ALLOWLIST
        if (value := os.environ.get(key))
    }


def _zenith_project_root() -> Path:
    """Return the source checkout that owns the Zenith runtime uv project."""
    start = Path(__file__).resolve()
    for candidate in (start.parent, *start.parents):
        pyproject = candidate / "pyproject.toml"
        if not pyproject.exists():
            continue
        try:
            text = pyproject.read_text(encoding="utf-8")
        except OSError:
            continue
        if 'name = "zenith-harness"' in text:
            return candidate
    raise click.ClickException(
        "Could not locate the Zenith uv project root. Run `zenith init` from a "
        "Zenith source checkout with pyproject.toml available."
    )


def _mcp_server_args() -> list[str]:
    return [
        "run",
        "--project",
        str(_zenith_project_root()),
        "zenith-server",
        "--mode",
        "orchestrator",
    ]


def _claude_user_paths() -> tuple[Path, Path]:
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    if configured:
        root = Path(configured).expanduser().resolve()
        return root, root / ".claude.json"
    home = Path.home().resolve()
    return home / ".claude", home / ".claude.json"


def _codex_user_paths() -> tuple[Path, Path]:
    root = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    root = root.expanduser().resolve()
    return root, root / "config.toml"


def _user_paths(provider: ProviderDefinition) -> tuple[Path, Path]:
    if provider.name == "claude":
        return _claude_user_paths()
    if provider.name == "codex":
        return _codex_user_paths()
    raise ValueError(f"user-scope paths are not defined for {provider.name}")


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    previous_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.zenith-",
            delete=False,
        ) as handle:
            handle.write(text)
            temp_path = Path(handle.name)
        if previous_mode is not None:
            temp_path.chmod(previous_mode)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _user_server_config(selection: ProviderSelection, storage_env: dict[str, str]) -> dict:
    return {
        "type": "stdio",
        "command": "uv",
        "args": _mcp_server_args(),
        "env": {**selection.env(), **storage_env},
    }


def _write_claude_user_config(
    path: Path,
    selection: ProviderSelection,
    storage_env: dict[str, str],
) -> None:
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise click.ClickException(f"Cannot update invalid Claude config {path}: {exc}") from exc
    else:
        existing = {}
    if not isinstance(existing, dict):
        raise click.ClickException(f"Cannot update Claude config {path}: root must be an object")
    mcp_servers = existing.setdefault("mcpServers", {})
    if not isinstance(mcp_servers, dict):
        raise click.ClickException(
            f"Cannot update Claude config {path}: mcpServers must be an object"
        )
    mcp_servers["zenith"] = _user_server_config(selection, storage_env)
    _write_text_atomic(path, json.dumps(existing, indent=2) + "\n")
    click.echo(f"Wrote {path}")


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_table_path(line: str) -> tuple[str, ...] | None:
    stripped = line.strip()
    if not stripped.startswith("[") or stripped.startswith("[["):
        return None
    try:
        parsed = tomllib.loads(f"{stripped}\n")
    except tomllib.TOMLDecodeError:
        return None
    path: list[str] = []
    current = parsed
    while len(current) == 1:
        key, value = next(iter(current.items()))
        if not isinstance(value, dict):
            return None
        path.append(key)
        current = value
    return tuple(path) if not current else None


def _strip_toml_tables(text: str, table: tuple[str, ...]) -> str:
    kept: list[str] = []
    removing = False
    for line in text.splitlines(keepends=True):
        path = _toml_table_path(line)
        if path is not None:
            removing = path[: len(table)] == table
        if not removing:
            kept.append(line)
    return "".join(kept).rstrip()


def _write_codex_user_config(
    path: Path,
    selection: ProviderSelection,
    storage_env: dict[str, str],
) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        tomllib.loads(existing)
    except tomllib.TOMLDecodeError as exc:
        raise click.ClickException(f"Cannot update invalid Codex config {path}: {exc}") from exc

    start = "# BEGIN zenith"
    end = "# END zenith"
    if (start in existing) != (end in existing):
        raise click.ClickException(
            f"Cannot update Codex config {path}: incomplete Zenith managed block"
        )
    if start not in existing:
        existing = _strip_toml_tables(existing, ("mcp_servers", "zenith"))

    server = _user_server_config(selection, storage_env)
    env_lines = "\n".join(
        f"{key} = {_toml_string(value)}" for key, value in server["env"].items()
    )
    block = (
        f"{start}\n"
        "[mcp_servers.zenith]\n"
        'command = "uv"\n'
        f"args = {json.dumps(server['args'], ensure_ascii=False)}\n"
        "startup_timeout_sec = 10\n"
        "tool_timeout_sec = 1000000\n"
        "\n"
        "[mcp_servers.zenith.env]\n"
        f"{env_lines}\n"
        f"{end}\n"
    )
    updated = _replace_managed_block_text(existing, start, end, block)
    try:
        tomllib.loads(updated)
    except tomllib.TOMLDecodeError as exc:
        raise click.ClickException(f"Generated invalid Codex config for {path}: {exc}") from exc
    _write_text_atomic(path, updated)
    click.echo(f"Wrote {path}")


def _write_user_bootstrap_config(
    selection: ProviderSelection,
    storage_env: dict[str, str],
) -> None:
    _, config_path = _user_paths(selection.orchestrator)
    if selection.orchestrator.name == "claude":
        _write_claude_user_config(config_path, selection, storage_env)
    elif selection.orchestrator.name == "codex":
        _write_codex_user_config(config_path, selection, storage_env)
    else:
        raise ValueError(f"unsupported user-scope provider: {selection.orchestrator.name}")


def _zenith_skill_body(prompt_path: Path) -> str:
    return f'''---
name: zenith
description: Run a long-horizon mission through the Zenith continuous-improvement harness.
---

# /zenith

First read `{prompt_path}` and treat it as your primary role, then use the globally
registered Zenith MCP tools to run the mission supplied with this skill.

If the Zenith tools are unavailable, ask the user to restart the host or start a new
session. Do not run workspace initialization merely because the current workspace has
no local Zenith configuration; project state begins with `start_project(brief,
workspace_dir)`.
'''


def _setup_user_provider_assets(loader: AssetLoader, provider: ProviderDefinition) -> None:
    root, _ = _user_paths(provider)
    agents_dir = root / "agents"
    _copy_provider_agents(loader, agents_dir, provider.name)
    click.echo(f"Installed {provider.name} subagents to {agents_dir}")

    skills_dir = root / "skills"
    _copy_skills(loader, skills_dir)
    click.echo(f"Installed bundled skills to {skills_dir}")

    shared_skills_dir = Path.home().resolve() / ".agents" / "skills"
    _copy_skills(loader, shared_skills_dir)
    click.echo(f"Installed bundled skills to {shared_skills_dir}")

    prompt_path = root / "orchestrator_prompt.md"
    prompt = loader.load_prompt_file("orchestrator", "system_prompt.md")
    _write_text_atomic(prompt_path, prompt)
    click.echo(f"Wrote {prompt_path}")

    skill_path = skills_dir / "zenith" / "SKILL.md"
    _write_text_atomic(skill_path, _zenith_skill_body(prompt_path))
    click.echo(f"Wrote {skill_path}")


def _write_bootstrap_config(
    workspace: Path,
    selection: ProviderSelection,
    storage_env: dict[str, str],
) -> None:
    fmt = selection.orchestrator.config_format
    env = {**selection.env(), **storage_env}
    server_args = _mcp_server_args()
    if fmt == "mcp_json":
        env = {**env, **_forwarded_mcp_env()}
        path = workspace / ".mcp.json"
        existing = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        )
        existing.setdefault("mcpServers", {})["zenith"] = {
            "type": "stdio",
            "command": "uv",
            "args": server_args,
            "env": env,
        }
        path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
        click.echo(f"Wrote {path}")
    elif fmt == "codex_config":
        config_path = workspace / ".codex" / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        env_lines = "\n".join(f'{k} = "{v}"' for k, v in env.items())
        block = (
            'model = "gpt-5.5"\n'
            'sandbox_mode = "danger-full-access"\n'
            'model_reasoning_effort = "xhigh"\n'
            '[features]\n'
            'memories = true\n'
            "# BEGIN zenith\n"
            "[mcp_servers.zenith]\n"
            'command = "uv"\n'
            f"args = {json.dumps(server_args)}\n"
            "startup_timeout_sec = 10\n"
            "tool_timeout_sec = 1000000\n"
            "\n"
            "[mcp_servers.zenith.env]\n"
            f"{env_lines}\n"
            "# END zenith\n"
        )
        _replace_managed_block(config_path, "# BEGIN zenith", "# END zenith", block)
        click.echo(f"Wrote {config_path}")
    else:
        raise ValueError(f"unsupported config_format: {fmt}")


def _replace_managed_block_text(existing: str, start: str, end: str, block: str) -> str:
    if start in existing and end in existing:
        before, _, tail = existing.partition(start)
        _, _, after = tail.partition(end)
        updated = before.rstrip()
        if updated:
            updated += "\n\n"
        updated += block.rstrip() + "\n"
        if after.strip():
            updated += "\n" + after.lstrip("\n")
    else:
        updated = existing.rstrip()
        if updated:
            updated += "\n\n"
        updated += block.rstrip() + "\n"
    return updated


def _replace_managed_block(path: Path, start: str, end: str, block: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    updated = _replace_managed_block_text(existing, start, end, block)
    path.write_text(updated, encoding="utf-8")


def _setup_provider_assets(
    workspace: Path,
    loader: AssetLoader,
    provider: ProviderDefinition,
) -> None:
    if provider.agent_output_dir:
        agents_dir = workspace / provider.agent_output_dir
        _copy_provider_agents(
            loader, agents_dir, provider.name
        )
        click.echo(f"Installed {provider.name} subagents to {agents_dir}")
    # Install bundled skills into the host-agent skill surface so the
    # orchestrator can discover playbooks/skills at startup — `start_project`
    # runs only after the host agent is already up, so the surface must exist
    # before the first MCP call. `start_project` later merges bucket skills
    # (including project-authored ones) into these dirs.
    for rel in provider.skill_dirs:
        dest = workspace / rel
        _copy_skills(loader, dest)
        click.echo(f"Installed bundled skills to {dest}")
    if provider.orchestrator_prompt_output_path:
        path = workspace / provider.orchestrator_prompt_output_path
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            body = loader.load_prompt_file("orchestrator", "system_prompt.md")
            path.write_text(body, encoding="utf-8")
            click.echo(f"Created {path}")


def _copy_provider_agents(loader: AssetLoader, target: Path, provider_name: str) -> None:
    bundled = loader.bundled_agents_dir(provider_name)
    if not bundled.exists():
        return
    target.mkdir(parents=True, exist_ok=True)
    for agent_file in sorted(bundled.glob("*")):
        if agent_file.is_file():
            shutil.copy2(agent_file, target / agent_file.name)
