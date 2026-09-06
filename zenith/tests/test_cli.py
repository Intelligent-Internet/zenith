"""CLI integration tests — init / list-projects / show-project / install-skills."""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

from zenith_harness.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


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

    def test_codex_init_forwards_auth_registry_paths_without_api_key(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        subscription_home = workspace / "subscription-auth"
        grants_file = workspace / "api-grants.json"
        monkeypatch.setenv("ZENITH_CODEX_SUBSCRIPTION_HOME", str(subscription_home))
        monkeypatch.setenv("ZENITH_API_GRANTS_FILE", str(grants_file))
        monkeypatch.setenv("OPENAI_API_KEY", "must-not-enter-host-config")

        r = runner.invoke(cli, ["init", "--workspace-dir", str(workspace), "--agent", "codex"])
        assert r.exit_code == 0, r.output

        config = tomllib.loads(
            (workspace / ".codex" / "config.toml").read_text(encoding="utf-8")
        )
        server_env = config["mcp_servers"]["zenith"]["env"]
        assert server_env["ZENITH_CODEX_SUBSCRIPTION_HOME"] == str(subscription_home)
        assert server_env["ZENITH_API_GRANTS_FILE"] == str(grants_file)
        assert "OPENAI_API_KEY" not in server_env

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
        assert r.exit_code != 0
        assert isinstance(r.exception, ValueError)
        assert "ZENITH_WORKER_REASONING_EFFORT" in str(r.exception)

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

    def test_claude_init_forwards_only_allowed_model_env(
        self,
        runner: CliRunner,
        workspace: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.z.ai/api/anthropic")
        monkeypatch.setenv("ANTHROPIC_MODEL", "glm-5.2[1m]")
        monkeypatch.setenv("ZAI_API_KEY", "zai-test-key")
        monkeypatch.setenv("DATABASE_URL", "postgres://should-not-forward")

        r = runner.invoke(cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"])
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text())
        mcp_env = mcp["mcpServers"]["zenith"]["env"]
        assert mcp_env["ANTHROPIC_BASE_URL"] == "https://api.z.ai/api/anthropic"
        assert mcp_env["ANTHROPIC_MODEL"] == "glm-5.2[1m]"
        assert mcp_env["ZAI_API_KEY"] == "zai-test-key"
        assert "DATABASE_URL" not in mcp_env

    def test_claude_init_writes_terminal_reviewer_env_names(
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
                "--terminal-reviewer-provider",
                "codex",
                "--terminal-reviewer-acp-command",
                "custom-tr-acp",
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text())
        mcp_env = mcp["mcpServers"]["zenith"]["env"]
        assert mcp_env["ZENITH_TERMINAL_REVIEWER_PROVIDER"] == "codex"
        assert mcp_env["ZENITH_TERMINAL_REVIEWER_ACP_COMMAND"] == "custom-tr-acp"

    def test_claude_init_omits_terminal_reviewer_env_when_unset(
        self, runner: CliRunner, workspace: Path, env: dict[str, str]
    ) -> None:
        r = runner.invoke(
            cli, ["init", "--workspace-dir", str(workspace), "--agent", "claude"]
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text())
        mcp_env = mcp["mcpServers"]["zenith"]["env"]
        assert "ZENITH_TERMINAL_REVIEWER_PROVIDER" not in mcp_env
        assert "ZENITH_TERMINAL_REVIEWER_ACP_COMMAND" not in mcp_env

    def test_three_distinct_providers_all_env_written(
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
                "--terminal-reviewer-provider",
                "hermes",
            ],
        )
        assert r.exit_code == 0, r.output

        mcp = json.loads((workspace / ".mcp.json").read_text())
        mcp_env = mcp["mcpServers"]["zenith"]["env"]
        assert mcp_env["ZENITH_ORCHESTRATOR_PROVIDER"] == "claude"
        assert mcp_env["ZENITH_WORKER_PROVIDER"] == "claude"
        assert mcp_env["ZENITH_VALIDATOR_PROVIDER"] == "codex"
        assert mcp_env["ZENITH_TERMINAL_REVIEWER_PROVIDER"] == "hermes"


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
