from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import click

from .assets import AssetLoader, iter_skill_directories
from .config import VALID_REASONING_EFFORTS, HarnessConfig
from .envelope import render_task_list
from .providers import (
    ProviderDefinition,
    ProviderSelection,
    default_worker_provider_name,
    get_provider,
    provider_names_for_role,
)
from .storage import ProjectStore

RUNTIME_ENV_FORWARD_ALLOWLIST = (
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
    "ZENITH_WORKER_REASONING_EFFORT",
    "ZENITH_VALIDATOR_REASONING_EFFORT",
    "ZENITH_TERMINAL_REVIEWER_REASONING_EFFORT",
    "ZAI_API_KEY",
    "ZAI_BASE_URL",
)


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
@click.option("--worker-reasoning-effort", type=click.Choice(VALID_REASONING_EFFORTS), default=None)
@click.option("--validator-reasoning-effort", type=click.Choice(VALID_REASONING_EFFORTS), default=None)
@click.option("--terminal-reviewer-reasoning-effort", type=click.Choice(VALID_REASONING_EFFORTS), default=None)
@click.option("--zenith-home", type=click.Path(), default=None)
@click.option("--workspace-dir", "workspace_dir", type=click.Path(exists=True), default=".")
def init(
    agent: str | None,
    orchestrator_provider: str | None,
    worker_provider: str | None,
    worker_acp_command: str | None,
    validator_provider: str | None,
    validator_acp_command: str | None,
    terminal_reviewer_provider: str | None,
    terminal_reviewer_acp_command: str | None,
    worker_reasoning_effort: str | None,
    validator_reasoning_effort: str | None,
    terminal_reviewer_reasoning_effort: str | None,
    zenith_home: str | None,
    workspace_dir: str,
) -> None:
    """Initialize host-agent surface: MCP/codex config + provider agents + orchestrator prompt.

    The project bucket is created by `start_project` at the first MCP call from
    the host agent — `zenith init` stages the host-agent-facing files the agent
    loads at startup (provider configs, subagent definitions, orchestrator
    prompt, and the bundled skill surface under the provider's skill dirs). The
    workspace stays clean of `.zenith/` until `start_project` runs.
    """
    workspace = Path(workspace_dir).resolve()
    # discover() validates the ambient ZENITH_* settings. Its ValueError is a
    # user-facing complaint about the caller's environment, not a harness
    # fault, so it gets the same treatment as a bad flag rather than a
    # traceback.
    try:
        config = HarnessConfig.discover()
    except ValueError as exc:
        raise click.UsageError(str(exc)) from None
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

    # 1) MCP / Codex config
    storage_env = _storage_env(zenith_home=zenith_home, workspace=workspace, selection=selection)
    # Flags are sugar for the ZENITH_*_REASONING_EFFORT env vars and win over
    # valid inherited shell settings. An invalid value already in the
    # environment still fails fast at discover() above — flags override
    # settings, they don't mask broken ones (the same validation would raise
    # at server launch anyway).
    effort_env = {
        var: value
        for var, value in (
            ("ZENITH_WORKER_REASONING_EFFORT", worker_reasoning_effort),
            ("ZENITH_VALIDATOR_REASONING_EFFORT", validator_reasoning_effort),
            ("ZENITH_TERMINAL_REVIEWER_REASONING_EFFORT", terminal_reviewer_reasoning_effort),
        )
        if value
    }
    # Resolve every role the way the server will, then stage what was
    # resolved. These vars are not in RUNTIME_ENV_FORWARD_ALLOWLIST and
    # ProviderSelection.env() emits a role provider only when it differs from
    # the worker, so an ambient ZENITH_VALIDATOR_PROVIDER used to inform init's
    # diagnostics while never reaching the config init wrote. The two answers
    # could then disagree in both directions: a warning about a hermes
    # validator whose written config said claude, and silence in the mirror
    # case. Writing the resolved value closes that gap — the host agent is
    # usually launched later, from a different shell, and reads only what is
    # written here.
    #
    # Precedence per role: explicit flag, then the ambient var, then inherit
    # down the chain (worker -> validator -> terminal reviewer). The flag wins
    # so an explicit `--validator-provider claude` is never overruled by a
    # stale export.
    def _ambient(var: str) -> str | None:
        return os.environ.get(var) or None

    def _pick(*candidates: tuple[str | None, str]) -> tuple[str, str]:
        """First candidate with a value, paired with where it came from."""
        for value, source in candidates:
            if value:
                return value, source
        raise AssertionError("the final candidate must always carry a value")

    # The worker is the exception: it is the only role with a default of its
    # own (`--agent`, then default_worker_provider_name), and ProviderSelection
    # has always written ZENITH_WORKER_PROVIDER unconditionally. Init therefore
    # sets the worker rather than inheriting it, and an ambient
    # ZENITH_WORKER_PROVIDER does not survive `zenith init`. The other two
    # roles have no default but the lane above them, which is why they consult
    # the environment.
    worker_provider_name, worker_source = selection.worker.name, "--worker-provider"
    validator_provider_name, validator_source = _pick(
        (validator_provider, "--validator-provider"),
        (_ambient("ZENITH_VALIDATOR_PROVIDER"), "ZENITH_VALIDATOR_PROVIDER"),
        (worker_provider_name, worker_source),
    )
    terminal_reviewer_provider_name, terminal_source = _pick(
        (terminal_reviewer_provider, "--terminal-reviewer-provider"),
        (_ambient("ZENITH_TERMINAL_REVIEWER_PROVIDER"), "ZENITH_TERMINAL_REVIEWER_PROVIDER"),
        (validator_provider_name, validator_source),
    )

    # An ACP command names a binary, so it is the most provider-specific value
    # in the config. It is therefore taken from the
    # environment only for a lane whose *provider* also came from the
    # environment, so the pair stays together. Take one without the other and
    # init manufactures the mismatch it warns about below: with
    # `ZENITH_WORKER_PROVIDER=codex ZENITH_WORKER_ACP_COMMAND=codex-acp` in the
    # shell, `zenith init --agent claude` sets the worker provider itself (see
    # above) and would otherwise pair claude with codex-acp — permanently, and
    # in the config it just wrote. A lane whose provider init chose gets its
    # command from the flag or from that provider's default, never from a
    # shell that was talking about some other provider.
    #
    # Honoring the paired case still fixes the original defect: an exported
    # ZENITH_VALIDATOR_ACP_COMMAND used to inform nothing and never be written,
    # so the lane silently fell back to the worker's command at runtime.
    def _role_command(
        flag_value: str | None, var: str, provider_source: str
    ) -> str | None:
        if flag_value:
            return flag_value
        return _ambient(var) if provider_source == var.replace("_ACP_COMMAND", "_PROVIDER") else None

    role_command = {
        var: value
        for var, value in (
            (
                "ZENITH_WORKER_ACP_COMMAND",
                _role_command(worker_acp_command, "ZENITH_WORKER_ACP_COMMAND", worker_source),
            ),
            (
                "ZENITH_VALIDATOR_ACP_COMMAND",
                _role_command(
                    validator_acp_command, "ZENITH_VALIDATOR_ACP_COMMAND", validator_source
                ),
            ),
            (
                "ZENITH_TERMINAL_REVIEWER_ACP_COMMAND",
                _role_command(
                    terminal_reviewer_acp_command,
                    "ZENITH_TERMINAL_REVIEWER_ACP_COMMAND",
                    terminal_source,
                ),
            ),
        )
        if value
    }
    role_env = {
        "ZENITH_VALIDATOR_PROVIDER": validator_provider_name,
        "ZENITH_TERMINAL_REVIEWER_PROVIDER": terminal_reviewer_provider_name,
        **role_command,
    }
    cli_env = {**effort_env, **role_env}

    # Resolved before anything is written: the flags carry a click.Choice, but
    # an ambient ZENITH_*_PROVIDER does not, and these names are dereferenced
    # late — the terminal one at asset install, the validator one not until the
    # first validate dispatch mid-mission. A typo should stop init, blamed on
    # whatever actually supplied it. A flag that beat the ambient var means the
    # ambient typo never reaches this check, which is the point.
    def _resolve_provider(name: str, source: str):
        try:
            return get_provider(name)
        except ValueError as exc:
            raise click.UsageError(f"{exc} (from {source})") from None

    validator_provider_def = _resolve_provider(validator_provider_name, validator_source)
    terminal_reviewer_provider_def = _resolve_provider(
        terminal_reviewer_provider_name, terminal_source
    )

    def _runs_provider_binary(command: str, provider_def: ProviderDefinition) -> bool:
        """Whether `command` looks like it launches `provider_def`'s own agent.

        Compares the executable — first token, basename only — so an absolute
        path or added arguments (`/usr/local/bin/codex-acp`, `codex-acp
        --verbose`) still reads as codex. Wrong only when a command genuinely
        runs a different binary, which is the case worth a warning.
        """
        default = provider_def.default_worker_acp_command
        if not default:
            return False
        return Path(command.split()[0]).name == Path(default.split()[0]).name

    # A lane whose command runs somebody else's binary will not get the
    # provider-specific treatment the harness applies for the provider it
    # thinks it has: sandbox flags, the codex config flags and the ACP session
    # mode all key on provider.name.
    for role, provider_def, command_var in (
        ("worker", selection.worker, "ZENITH_WORKER_ACP_COMMAND"),
        ("validator", validator_provider_def, "ZENITH_VALIDATOR_ACP_COMMAND"),
        (
            "terminal reviewer",
            terminal_reviewer_provider_def,
            "ZENITH_TERMINAL_REVIEWER_ACP_COMMAND",
        ),
    ):
        command = role_command.get(command_var)
        if command and not _runs_provider_binary(command, provider_def):
            click.echo(
                f"Warning: the {role} lane dispatches as provider "
                f"{provider_def.name} but launches {command} — sandbox flags "
                "and the ACP session mode are applied the way "
                f"{provider_def.name} expects, and will be wrong if that "
                "command runs a different agent."
            )

    _write_bootstrap_config(workspace, selection, storage_env, cli_env)

    # 2) Per-provider agents + orchestrator prompt. ProviderSelection knows
    #    only the flags, so both roles that can be resolved from the
    #    environment are added here. Skipping either installs a workspace whose
    #    config names a provider that has no agents or skills on disk — a
    #    validator resolved from an ambient ZENITH_VALIDATOR_PROVIDER used to
    #    get assets only by accident, when the reviewer happened to inherit it.
    asset_providers = list(selection.providers())
    for provider_def in (validator_provider_def, terminal_reviewer_provider_def):
        if provider_def.name not in {p.name for p in asset_providers}:
            asset_providers.append(provider_def)
    for provider in asset_providers:
        _setup_provider_assets(workspace, loader, provider)

    click.echo(
        f"\nInitialized v5 project workspace at {workspace}: "
        f"orchestrator={selection.orchestrator.name}, "
        f"worker={worker_provider_name}, "
        # The resolved names, not selection's flag-only view — otherwise the
        # summary contradicts the config written one line earlier whenever a
        # role came from the environment.
        f"validator={validator_provider_name}, "
        f"terminal-reviewer={terminal_reviewer_provider_name}."
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


def _forwarded_runtime_env() -> dict[str, str]:
    return {
        key: value
        for key in RUNTIME_ENV_FORWARD_ALLOWLIST
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


def _write_bootstrap_config(
    workspace: Path,
    selection: ProviderSelection,
    storage_env: dict[str, str],
    cli_env: dict[str, str],
) -> None:
    fmt = selection.orchestrator.config_format
    env = {**selection.env(), **storage_env, **_forwarded_runtime_env(), **cli_env}
    server_args = _mcp_server_args()
    if fmt == "mcp_json":
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
        # TOML basic strings share JSON's escape syntax, so json.dumps closes
        # and escapes embedded quotes. ACP commands splice config via
        # `-c key="value"`, and forwarded env values may hold quotes or
        # backslashes; interpolating either raw emits invalid TOML.
        env_lines = "\n".join(f"{k} = {json.dumps(v)}" for k, v in env.items())
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


def _replace_managed_block(path: Path, start: str, end: str, block: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
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
