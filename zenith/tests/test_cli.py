"""CLI integration tests — init / list-projects / show-project / install-skills."""
from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

from zenith_harness.cli import cli
from zenith_harness.config import HarnessConfig


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def _scrub_ambient_role_env(monkeypatch) -> None:
    """Init reads ambient ZENITH_* role settings when resolving a lane, so a
    developer's exported provider or command would otherwise leak into these
    assertions. Tests that want one set it themselves.
    """
    for role in ("WORKER", "VALIDATOR", "TERMINAL_REVIEWER"):
        for suffix in ("MODEL", "PROVIDER", "ACP_COMMAND", "REASONING_EFFORT"):
            monkeypatch.delenv(f"ZENITH_{role}_{suffix}", raising=False)


@pytest.fixture
def env(harness_home: Path, workspace: Path, monkeypatch) -> dict[str, str]:
    monkeypatch.setenv("ZENITH_HOME", str(harness_home))
    monkeypatch.chdir(workspace)
    return {"ZENITH_HOME": str(harness_home)}


def _expected_mcp_server_args() -> list[str]:
    zenith_root = Path(__file__).resolve().parents[1]
    return [
        "run",
        "--project",
        str(zenith_root),
        "zenith-server",
        "--mode",
        "orchestrator",
    ]


class TestInit:
    def test_stages_host_agent_surface_only(
        self, runner: CliRunner, workspace: Path, env: dict[str, str]
    ) -> None:
        """`zenith init` writes MCP config + provider agents + orchestrator prompt
        but does NOT create the project bucket or workspace shims — those are
        created by `start_project` at the first MCP call."""
        result = runner.invoke(
            cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"]
        )
        assert result.exit_code == 0, result.output
        # Workspace stays clean of .zenith/ — bucket lives under ZENITH_HOME.
        assert not (workspace / ".zenith").exists()
        # No symlink shims either — start_project handles them.
        assert not (workspace / "AGENTS.md").exists()
        # MCP config + .claude/agents/ are written.
        assert (workspace / ".mcp.json").exists()
        mcp = json.loads((workspace / ".mcp.json").read_text())
        assert "zenith" in mcp["mcpServers"]
        server = mcp["mcpServers"]["zenith"]
        assert server["command"] == "uv"
        assert server["args"] == _expected_mcp_server_args()

    def test_init_does_not_touch_gitignore(
        self, runner: CliRunner, workspace: Path, env: dict[str, str]
    ) -> None:
        gitignore = workspace / ".gitignore"
        gitignore.write_text("node_modules/\n")
        original = gitignore.read_text()
        r = runner.invoke(
            cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"]
        )
        assert r.exit_code == 0, r.output
        assert gitignore.read_text() == original

    def test_idempotent(
        self, runner: CliRunner, workspace: Path, env: dict[str, str]
    ) -> None:
        for _ in range(2):
            r = runner.invoke(
                cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"]
            )
            assert r.exit_code == 0, r.output
        # .mcp.json preserved across reruns.
        assert (workspace / ".mcp.json").exists()

    def test_codex_writes_codex_config(
        self, runner: CliRunner, workspace: Path, env: dict[str, str]
    ) -> None:
        r = runner.invoke(cli, ["init", "--workspace-dir", str(workspace), "--agent", "codex"])
        assert r.exit_code == 0, r.output
        config_path = workspace / ".codex" / "config.toml"
        assert config_path.exists()
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        server = config["mcp_servers"]["zenith"]
        assert server["command"] == "uv"
        assert server["args"] == _expected_mcp_server_args()
        assert f"Initialized v5 project workspace at {workspace}" in r.output
        assert "Start your agent from the initialized project workspace" in r.output
        assert (
            "First read .codex/orchestrator_prompt.md and treat it as your primary role, "
            "then use Zenith to run this mission." in r.output
        )

    def test_claude_init_writes_reasoning_effort_env(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ZENITH_WORKER_REASONING_EFFORT", "high")
        monkeypatch.setenv("ZENITH_VALIDATOR_REASONING_EFFORT", "medium")
        monkeypatch.setenv("ZENITH_TERMINAL_REVIEWER_REASONING_EFFORT", "low")

        r = runner.invoke(cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"])
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        assert server_env["ZENITH_WORKER_REASONING_EFFORT"] == "high"
        assert server_env["ZENITH_VALIDATOR_REASONING_EFFORT"] == "medium"
        assert server_env["ZENITH_TERMINAL_REVIEWER_REASONING_EFFORT"] == "low"

    def test_codex_init_writes_reasoning_effort_env(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ZENITH_WORKER_REASONING_EFFORT", "high")
        monkeypatch.setenv("ZENITH_VALIDATOR_REASONING_EFFORT", "medium")
        monkeypatch.setenv("ZENITH_TERMINAL_REVIEWER_REASONING_EFFORT", "low")

        r = runner.invoke(cli, ["init", "--workspace-dir", str(workspace), "--agent", "codex"])
        assert r.exit_code == 0, r.output

        config = tomllib.loads(
            (workspace / ".codex" / "config.toml").read_text(encoding="utf-8")
        )
        server_env = config["mcp_servers"]["zenith"]["env"]
        assert server_env["ZENITH_WORKER_REASONING_EFFORT"] == "high"
        assert server_env["ZENITH_VALIDATOR_REASONING_EFFORT"] == "medium"
        assert server_env["ZENITH_TERMINAL_REVIEWER_REASONING_EFFORT"] == "low"

    def test_codex_init_escapes_quoted_acp_commands(
        self, runner: CliRunner, workspace: Path, env: dict[str, str]
    ) -> None:
        """Quoted ACP commands must survive into config.toml as valid TOML.

        `-c key="value"` is the supported splice shape for codex config, so
        a role's command can carry double quotes. Interpolating them raw
        terminates the TOML string early and corrupts the managed block.
        The two commands differ so `ProviderSelection.env()` emits both —
        it suppresses a role whose resolved command matches the previous
        role's.
        """
        worker_cmd = 'codex-acp -c model="gpt-5.6-luna"'
        validator_cmd = 'codex-acp -c model="gpt-5.6-terra"'

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "codex",
                "--worker-acp-command",
                worker_cmd,
                "--validator-acp-command",
                validator_cmd,
            ],
        )
        assert r.exit_code == 0, r.output

        # Parsing at all is the regression guard — this raises before the fix.
        config = tomllib.loads(
            (workspace / ".codex" / "config.toml").read_text(encoding="utf-8")
        )
        server_env = config["mcp_servers"]["zenith"]["env"]
        assert server_env["ZENITH_WORKER_ACP_COMMAND"] == worker_cmd
        assert server_env["ZENITH_VALIDATOR_ACP_COMMAND"] == validator_cmd

    def test_init_reasoning_effort_flags_override_env(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ZENITH_WORKER_REASONING_EFFORT", "xhigh")

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--worker-reasoning-effort",
                "max",
                "--validator-reasoning-effort",
                "medium",
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        # Flag beats the inherited shell env.
        assert server_env["ZENITH_WORKER_REASONING_EFFORT"] == "max"
        assert server_env["ZENITH_VALIDATOR_REASONING_EFFORT"] == "medium"
        assert "ZENITH_TERMINAL_REVIEWER_REASONING_EFFORT" not in server_env

    def test_init_invalid_inherited_effort_env_fails_despite_flag(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Flags override valid inherited settings; a broken env var is still a
        # hard error — the same validation would raise at server launch, so
        # masking it at init would only defer the failure.
        monkeypatch.setenv("ZENITH_WORKER_REASONING_EFFORT", "turbo")

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--worker-reasoning-effort",
                "max",
            ],
        )
        # A complaint about the caller's environment, reported the way a bad
        # flag is rather than as a traceback.
        assert r.exit_code == 2, r.output
        assert "ZENITH_WORKER_REASONING_EFFORT" in r.output

    def test_init_persists_terminal_reviewer_provider(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ZENITH_TERMINAL_REVIEWER_PROVIDER", raising=False)
        monkeypatch.delenv("ZENITH_TERMINAL_REVIEWER_ACP_COMMAND", raising=False)

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--terminal-reviewer-provider",
                "codex",
                "--terminal-reviewer-acp-command",
                "codex-acp",
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        # Accepted-and-discarded is worse than rejected: the flag reads as
        # configured while every terminal review runs on the validator's
        # provider instead.
        assert server_env["ZENITH_TERMINAL_REVIEWER_PROVIDER"] == "codex"
        assert server_env["ZENITH_TERMINAL_REVIEWER_ACP_COMMAND"] == "codex-acp"

    def test_init_installs_assets_for_a_validator_resolved_from_the_environment(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The reviewer is pinned elsewhere, so it cannot mask the gap by
        # inheriting the validator's provider: a config naming a codex
        # validator must come with codex agents and skills on disk.
        monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "codex")

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--terminal-reviewer-provider",
                "claude",
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        assert server_env["ZENITH_VALIDATOR_PROVIDER"] == "codex"
        assert (workspace / ".codex" / "agents").is_dir()

    def test_init_terminal_reviewer_inherits_the_validator_not_the_worker(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Matches for_role("terminal_reviewer"), which falls back to the
        # validator. Init now WRITES this provider unconditionally, so a wrong
        # inheritance here cannot be corrected by the runtime chain — the
        # written value wins.
        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--validator-provider",
                "codex",
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        assert server_env["ZENITH_TERMINAL_REVIEWER_PROVIDER"] == "codex"

    def test_init_command_flag_beats_ambient_command_env(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Same precedence claim the provider flags carry, for commands.
        monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "claude")
        monkeypatch.setenv("ZENITH_VALIDATOR_ACP_COMMAND", "stale-agent-acp")

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--validator-acp-command",
                "claude-agent-acp --lane validate",
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        assert server_env["ZENITH_VALIDATOR_ACP_COMMAND"] == "claude-agent-acp --lane validate"

    def test_init_drops_an_ambient_command_whose_provider_it_discarded(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Init sets the worker provider itself, so a shell that was talking
        # about a different provider must not get to set the worker's command.
        # Keeping half of a stale pair manufactures a claude lane that launches
        # codex-acp: no sandbox flags, no codex env, and a claude-only ACP mode
        # id sent to codex — durably, in the config init just wrote.
        monkeypatch.setenv("ZENITH_WORKER_PROVIDER", "codex")
        monkeypatch.setenv("ZENITH_WORKER_ACP_COMMAND", "codex-acp")

        r = runner.invoke(cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"])
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        assert server_env["ZENITH_WORKER_PROVIDER"] == "claude"
        assert server_env.get("ZENITH_WORKER_ACP_COMMAND") != "codex-acp"

    def test_init_keeps_an_ambient_command_paired_with_its_provider(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The other half of the pairing rule: exported together, they describe
        # one coherent lane, and dropping the command would send it back to the
        # worker's binary at runtime — the original defect.
        monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "codex")
        monkeypatch.setenv("ZENITH_VALIDATOR_ACP_COMMAND", "codex-acp --lane validate")

        r = runner.invoke(cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"])
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        assert server_env["ZENITH_VALIDATOR_PROVIDER"] == "codex"
        assert server_env["ZENITH_VALIDATOR_ACP_COMMAND"] == "codex-acp --lane validate"

    def test_init_warns_about_a_foreign_command(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Sandbox flags, the codex config flags and the ACP session mode all
        # key on provider.name, so a lane that launches somebody else's
        # binary gets all of them wrong.
        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--worker-acp-command",
                "codex-acp",
            ],
        )
        assert r.exit_code == 0, r.output

        assert "warning" in r.output.lower()
        assert "codex-acp" in r.output

    @pytest.mark.parametrize(
        "command",
        ["claude-agent-acp --verbose", "/usr/local/bin/claude-agent-acp"],
    )
    def test_init_does_not_warn_for_the_providers_own_binary(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
        command: str,
    ) -> None:
        # An absolute path or extra arguments still run claude-agent-acp. The
        # question is which binary runs, not whether the string matches.
        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--worker-acp-command",
                command,
            ],
        )
        assert r.exit_code == 0, r.output

        assert "warning" not in r.output.lower()

    def test_init_summary_reports_the_resolved_roles(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The summary is the only thing most users read; it must not contradict
        # the config written one line earlier.
        monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "codex")

        r = runner.invoke(cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"])
        assert r.exit_code == 0, r.output

        assert "validator=codex" in r.output

    def test_init_provider_flag_beats_ambient_provider_env(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # A stale export must not overrule what the user typed, and a typo in
        # it must not fail an init that never consults it.
        monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "clyde")

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--validator-provider",
                "claude",
            ],
        )
        assert r.exit_code == 0, r.output
        assert "warning" not in r.output.lower()

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]
        assert server_env["ZENITH_VALIDATOR_PROVIDER"] == "claude"

    def test_written_config_reproduces_init_resolution_in_a_clean_environment(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The seam every other test in this file stops short of.

        Init resolves lanes; the server resolves them again from the written
        config, in a later process launched from a different shell. Every
        divergence between those two resolvers is a bug that per-lane
        assertions on init's output cannot see, so this drives the real
        `discover() + for_role()` over exactly what init wrote.
        """
        # Both role settings that init can only learn from the environment
        # are exercised — a provider and a command — across a lane that
        # lands on a different provider than the worker.
        monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "codex")
        monkeypatch.setenv("ZENITH_VALIDATOR_ACP_COMMAND", "codex-acp --lane validate")

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--worker-reasoning-effort",
                "max",
                "--terminal-reviewer-provider",
                "claude",
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        server_env = mcp["mcpServers"]["zenith"]["env"]

        # Stand in for the later launch: nothing survives but the file.
        for var in list(os.environ):
            if var.startswith("ZENITH_") or var == "ANTHROPIC_MODEL":
                monkeypatch.delenv(var, raising=False)
        for key, value in server_env.items():
            monkeypatch.setenv(key, value)

        config = HarnessConfig.discover()

        worker = config.for_role("worker")
        assert worker.worker_provider_name == "claude"
        assert worker.worker_reasoning_effort == "max"
        assert worker.resolved_worker_acp_command == "claude-agent-acp"

        validator = config.for_role("validator")
        assert validator.worker_provider_name == "codex"
        assert validator.resolved_worker_acp_command == "codex-acp --lane validate"
        # Provider-neutral vocabulary, so this one does inherit across the gap.
        assert validator.worker_reasoning_effort == "max"

        reviewer = config.for_role("terminal_reviewer")
        assert reviewer.worker_provider_name == "claude"

    def test_init_installs_assets_for_terminal_reviewer_provider(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ZENITH_TERMINAL_REVIEWER_PROVIDER", raising=False)

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--terminal-reviewer-provider",
                "codex",
            ],
        )
        assert r.exit_code == 0, r.output

        # The reviewer really runs codex-acp now, so it needs the same asset
        # surface --validator-provider codex would have installed.
        assert (workspace / ".codex" / "agents").is_dir()

    def test_init_rejects_unknown_ambient_terminal_reviewer_provider_before_writing(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The flags carry a click.Choice, but an exported var does not — and it
        # is read late, so a typo used to raise ValueError only after the config
        # had been written, leaving a half-initialized workspace behind.
        monkeypatch.setenv("ZENITH_TERMINAL_REVIEWER_PROVIDER", "clyde")

        r = runner.invoke(
            cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"]
        )

        assert r.exit_code != 0
        assert "clyde" in r.output
        assert "ZENITH_TERMINAL_REVIEWER_PROVIDER" in r.output
        assert not (workspace / ".mcp.json").exists()

    def test_init_error_names_the_variable_that_supplied_the_bad_provider(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ZENITH_TERMINAL_REVIEWER_PROVIDER", raising=False)
        # The terminal lane inherits this name, but blaming
        # ZENITH_TERMINAL_REVIEWER_PROVIDER sends the user hunting for a
        # variable they never set.
        monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "clyde")

        r = runner.invoke(
            cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"]
        )

        assert r.exit_code != 0
        assert "ZENITH_VALIDATOR_PROVIDER" in r.output
        assert "ZENITH_TERMINAL_REVIEWER_PROVIDER" not in r.output
        assert not (workspace / ".mcp.json").exists()

    def test_init_validates_validator_provider_even_when_terminal_is_explicit(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ZENITH_VALIDATOR_PROVIDER", "clyde")

        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--terminal-reviewer-provider",
                "codex",
            ],
        )

        # An explicit terminal provider must not mask a broken validator lane:
        # without this the typo detonates mid-mission at the first validate
        # dispatch instead of at init.
        assert r.exit_code != 0
        assert "ZENITH_VALIDATOR_PROVIDER" in r.output
        assert not (workspace / ".mcp.json").exists()

    def test_claude_init_writes_runtime_validator_env_names(
        self, runner: CliRunner, workspace: Path, env: dict[str, str]
    ) -> None:
        r = runner.invoke(
            cli,
            [
                "init",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "claude",
                "--validator-provider",
                "codex",
                "--validator-acp-command",
                "custom-validator-acp",
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text())
        mcp_env = mcp["mcpServers"]["zenith"]["env"]
        assert mcp_env["ZENITH_VALIDATOR_PROVIDER"] == "codex"
        assert mcp_env["ZENITH_VALIDATOR_ACP_COMMAND"] == "custom-validator-acp"
        assert "ZENITH_VALIDATION_WORKER_PROVIDER" not in mcp_env
        assert "ZENITH_VALIDATION_WORKER_ACP_COMMAND" not in mcp_env

class TestListProjects:
    def test_empty(self, runner: CliRunner, env: dict[str, str]) -> None:
        r = runner.invoke(cli, ["list-projects"])
        assert r.exit_code == 0
        assert "No projects" in r.output

    def test_after_creation(
        self, runner: CliRunner, workspace: Path, harness_home: Path, env: dict[str, str]
    ) -> None:
        from zenith_harness.config import HarnessConfig
        from zenith_harness.storage import ProjectStore

        ProjectStore(HarnessConfig.discover()).create_project(
            "brief", workspace, project_id="proj-x"
        )
        r = runner.invoke(cli, ["list-projects"])
        assert "proj-x" in r.output


class TestShowProject:
    def test_unknown_id(self, runner: CliRunner, env: dict[str, str]) -> None:
        r = runner.invoke(cli, ["show-project", "ghost"])
        assert r.exit_code != 0
        assert "not found" in r.output.lower()
