"""CLI integration tests — init / list-projects / show-project / install-skills."""
from __future__ import annotations

import json
import os
import subprocess
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

    @pytest.mark.parametrize("agent", ["claude", "codex", "hermes"])
    def test_explicit_project_scope_matches_default(
        self,
        runner: CliRunner,
        tmp_path: Path,
        env: dict[str, str],
        agent: str,
    ) -> None:
        default_workspace = tmp_path / "default"
        explicit_workspace = tmp_path / "explicit"
        default_workspace.mkdir()
        explicit_workspace.mkdir()

        default_result = runner.invoke(
            cli,
            ["init", "--workspace-dir", str(default_workspace), "--agent", agent],
        )
        explicit_result = runner.invoke(
            cli,
            [
                "init",
                "--scope",
                "project",
                "--workspace-dir",
                str(explicit_workspace),
                "--agent",
                agent,
            ],
        )
        assert default_result.exit_code == 0, default_result.output
        assert explicit_result.exit_code == 0, explicit_result.output

        def files(root: Path) -> dict[str, bytes]:
            return {
                str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }

        assert files(default_workspace) == files(explicit_workspace)
        assert default_result.output.replace(str(default_workspace), "<workspace>") == (
            explicit_result.output.replace(str(explicit_workspace), "<workspace>")
        )


@pytest.fixture
def user_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    return home


class TestUserScopeInit:
    def test_claude_installs_user_config_and_assets_without_freezing_model(
        self,
        runner: CliRunner,
        workspace: Path,
        user_home: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        config_path = user_home / ".claude.json"
        config_path.write_text(
            json.dumps(
                {
                    "theme": "dark",
                    "projects": {"/existing": {"allowedTools": ["Read"]}},
                    "mcpServers": {
                        "other": {"command": "other-server"},
                        "zenith": {"command": "old-zenith"},
                    },
                },
                indent=2,
            )
            + "\n"
        )
        monkeypatch.setenv("ANTHROPIC_MODEL", "must-not-be-persisted")
        monkeypatch.setenv("ZAI_API_KEY", "must-not-be-persisted")

        result = runner.invoke(cli, ["init", "--scope", "user", "--agent", "claude"])
        assert result.exit_code == 0, result.output

        config = json.loads(config_path.read_text())
        assert config["theme"] == "dark"
        assert config["projects"]["/existing"]["allowedTools"] == ["Read"]
        assert config["mcpServers"]["other"]["command"] == "other-server"
        server = config["mcpServers"]["zenith"]
        assert server["command"] == "uv"
        assert server["args"] == _expected_mcp_server_args()
        assert server["env"]["ZENITH_ORCHESTRATOR_PROVIDER"] == "claude"
        assert "ANTHROPIC_MODEL" not in server["env"]
        assert "ZAI_API_KEY" not in server["env"]

        claude_root = user_home / ".claude"
        assert (claude_root / "orchestrator_prompt.md").exists()
        assert (claude_root / "agents" / "investigator.md").exists()
        assert (claude_root / "skills" / "engineering-mission-playbook" / "SKILL.md").exists()
        skill = (claude_root / "skills" / "zenith" / "SKILL.md").read_text()
        assert "name: zenith" in skill
        assert str(claude_root / "orchestrator_prompt.md") in skill
        assert "Do not run workspace initialization" in skill
        assert not (workspace / ".mcp.json").exists()
        assert not (workspace / ".claude").exists()
        assert "Restart Claude Code or start a new session" in result.output

        first_config = config_path.read_bytes()
        first_skill = (claude_root / "skills" / "zenith" / "SKILL.md").read_bytes()
        rerun = runner.invoke(cli, ["init", "--scope", "user", "--agent", "claude"])
        assert rerun.exit_code == 0, rerun.output
        assert config_path.read_bytes() == first_config
        assert (claude_root / "skills" / "zenith" / "SKILL.md").read_bytes() == first_skill

    def test_claude_config_dir_override_and_invalid_config_are_safe(
        self,
        runner: CliRunner,
        user_home: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        config_root = user_home / "custom claude"
        config_root.mkdir()
        config_path = config_root / ".claude.json"
        original = '{"mcpServers": []}\n'
        config_path.write_text(original)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_root))

        result = runner.invoke(cli, ["init", "--scope", "user", "--agent", "claude"])
        assert result.exit_code != 0
        assert "mcpServers must be an object" in result.output
        assert config_path.read_text() == original
        assert not (config_root / "skills").exists()
        assert not (config_root / "agents").exists()

        config_path.write_text("not json\n")
        malformed = runner.invoke(
            cli, ["init", "--scope", "user", "--agent", "claude"]
        )
        assert malformed.exit_code != 0
        assert config_path.read_text() == "not json\n"
        assert not (config_root / "skills").exists()

        config_path.write_text('{"theme": "light"}\n')
        success = runner.invoke(cli, ["init", "--scope", "user", "--agent", "claude"])
        assert success.exit_code == 0, success.output
        config = json.loads(config_path.read_text())
        assert config["theme"] == "light"
        assert config["mcpServers"]["zenith"]["command"] == "uv"
        assert (config_root / "skills" / "zenith" / "SKILL.md").exists()
        assert (config_root / "agents" / "investigator.md").exists()

    def test_codex_preserves_preferences_and_adopts_existing_server(
        self,
        runner: CliRunner,
        workspace: Path,
        user_home: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        codex_root = user_home / "custom codex"
        codex_root.mkdir()
        monkeypatch.setenv("CODEX_HOME", str(codex_root))
        monkeypatch.setenv("ANTHROPIC_MODEL", "must-not-be-persisted")
        config_path = codex_root / "config.toml"
        config_path.write_text(
            'model = "user-model"\n'
            'model_reasoning_effort = "low"\n'
            'sandbox_mode = "workspace-write"\n'
            "\n"
            "[features]\n"
            "memories = false\n"
            "\n"
            "[mcp_servers.other]\n"
            'command = "other-server"\n'
            "\n"
            "[mcp_servers.zenith]\n"
            'command = "old-zenith"\n'
            "\n"
            "[mcp_servers.zenith.env]\n"
            'OLD = "value"\n'
        )
        sibling_skill = codex_root / "skills" / "personal" / "SKILL.md"
        sibling_skill.parent.mkdir(parents=True)
        sibling_skill.write_text("personal skill\n")
        sibling_agent = codex_root / "agents" / "personal.toml"
        sibling_agent.parent.mkdir(parents=True)
        sibling_agent.write_text('name = "personal"\n')

        custom_home = user_home / 'state with "quotes" and ünicode'
        result = runner.invoke(
            cli,
            [
                "init",
                "--scope",
                "user",
                "--agent",
                "codex",
                "--zenith-home",
                str(custom_home),
            ],
        )
        assert result.exit_code == 0, result.output

        text = config_path.read_text()
        config = tomllib.loads(text)
        assert config["model"] == "user-model"
        assert config["model_reasoning_effort"] == "low"
        assert config["sandbox_mode"] == "workspace-write"
        assert config["features"]["memories"] is False
        assert config["mcp_servers"]["other"]["command"] == "other-server"
        server = config["mcp_servers"]["zenith"]
        assert server["command"] == "uv"
        assert server["args"] == _expected_mcp_server_args()
        assert server["env"]["ZENITH_HOME"] == str(custom_home.resolve())
        assert "ANTHROPIC_MODEL" not in server["env"]
        assert text.count("[mcp_servers.zenith]") == 1
        assert text.count("[mcp_servers.zenith.env]") == 1
        assert 'model = "gpt-5.5"' not in text
        assert 'model_reasoning_effort = "xhigh"' not in text

        assert (codex_root / "orchestrator_prompt.md").exists()
        assert (codex_root / "agents" / "investigator.toml").exists()
        skill_path = codex_root / "skills" / "zenith" / "SKILL.md"
        assert str(codex_root / "orchestrator_prompt.md") in skill_path.read_text()
        assert not (workspace / ".codex").exists()
        assert sibling_skill.read_text() == "personal skill\n"
        assert sibling_agent.read_text() == 'name = "personal"\n'

        first = config_path.read_bytes()
        rerun = runner.invoke(
            cli,
            [
                "init",
                "--scope",
                "user",
                "--agent",
                "codex",
                "--zenith-home",
                str(custom_home),
            ],
        )
        assert rerun.exit_code == 0, rerun.output
        assert config_path.read_bytes() == first

    @pytest.mark.parametrize(
        "zenith_header, env_header",
        [
            ('[mcp_servers."zenith"]', '[mcp_servers."zenith".env]'),
            ("[mcp_servers.zenith] # old server", "[mcp_servers.zenith.env] # old env"),
        ],
    )
    def test_codex_adopts_equivalent_unmanaged_zenith_tables(
        self,
        runner: CliRunner,
        user_home: Path,
        env: dict[str, str],
        zenith_header: str,
        env_header: str,
    ) -> None:
        codex_root = user_home / ".codex"
        codex_root.mkdir()
        config_path = codex_root / "config.toml"
        config_path.write_text(
            '[mcp_servers.before]\ncommand = "before"\n\n'
            f'{zenith_header}\ncommand = "old"\n\n'
            f'{env_header}\nOLD = "value"\n\n'
            '[mcp_servers.after]\ncommand = "after"\n'
        )

        result = runner.invoke(cli, ["init", "--scope", "user", "--agent", "codex"])
        assert result.exit_code == 0, result.output
        text = config_path.read_text()
        config = tomllib.loads(text)
        assert config["mcp_servers"]["before"]["command"] == "before"
        assert config["mcp_servers"]["after"]["command"] == "after"
        assert config["mcp_servers"]["zenith"]["command"] == "uv"
        assert text.count("[mcp_servers.zenith]") == 1

    @pytest.mark.parametrize(
        "content, message",
        [
            ("not = [valid\n", "invalid Codex config"),
            ("# BEGIN zenith\n", "incomplete Zenith managed block"),
            ("# END zenith\n", "incomplete Zenith managed block"),
        ],
    )
    def test_codex_invalid_config_does_not_mutate_assets(
        self,
        runner: CliRunner,
        user_home: Path,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
        content: str,
        message: str,
    ) -> None:
        codex_root = user_home / ".codex"
        codex_root.mkdir()
        config_path = codex_root / "config.toml"
        config_path.write_text(content)
        monkeypatch.setenv("CODEX_HOME", str(codex_root))

        result = runner.invoke(cli, ["init", "--scope", "user", "--agent", "codex"])
        assert result.exit_code != 0
        assert message in result.output
        assert config_path.read_text() == content
        assert not (codex_root / "skills").exists()
        assert not (codex_root / "agents").exists()

    @pytest.mark.parametrize("order", [("claude", "codex"), ("codex", "claude")])
    def test_claude_and_codex_user_installs_coexist(
        self,
        runner: CliRunner,
        user_home: Path,
        env: dict[str, str],
        order: tuple[str, str],
    ) -> None:
        first = runner.invoke(cli, ["init", "--scope", "user", "--agent", order[0]])
        assert first.exit_code == 0, first.output
        shared_root = user_home / ".agents" / "skills"
        shared_before = {
            str(path.relative_to(shared_root)): path.read_bytes()
            for path in shared_root.rglob("*")
            if path.is_file()
        }

        for agent in order[1:]:
            result = runner.invoke(cli, ["init", "--scope", "user", "--agent", agent])
            assert result.exit_code == 0, result.output

        claude = json.loads((user_home / ".claude.json").read_text())
        codex = tomllib.loads((user_home / ".codex" / "config.toml").read_text())
        assert claude["mcpServers"]["zenith"]["env"]["ZENITH_WORKER_PROVIDER"] == "claude"
        assert codex["mcp_servers"]["zenith"]["env"]["ZENITH_WORKER_PROVIDER"] == "codex"
        assert (user_home / ".claude" / "skills" / "zenith" / "SKILL.md").exists()
        assert (user_home / ".codex" / "skills" / "zenith" / "SKILL.md").exists()
        assert (user_home / ".agents" / "skills" / "scrutiny-validator" / "SKILL.md").exists()
        shared_after = {
            str(path.relative_to(shared_root)): path.read_bytes()
            for path in shared_root.rglob("*")
            if path.is_file()
        }
        assert shared_after == shared_before

    def test_user_scope_argument_errors_happen_before_writes(
        self,
        runner: CliRunner,
        workspace: Path,
        user_home: Path,
        env: dict[str, str],
    ) -> None:
        conflicting = runner.invoke(
            cli,
            [
                "init",
                "--scope",
                "user",
                "--workspace-dir",
                str(workspace),
                "--agent",
                "codex",
            ],
        )
        assert conflicting.exit_code != 0
        assert "--workspace-dir cannot be used with --scope user" in conflicting.output

        unsupported = runner.invoke(
            cli, ["init", "--scope", "user", "--agent", "hermes"]
        )
        assert unsupported.exit_code != 0
        assert "use --scope project for hermes" in unsupported.output
        assert list(user_home.iterdir()) == []

    def test_registered_command_launches_from_another_workspace(
        self,
        runner: CliRunner,
        user_home: Path,
        env: dict[str, str],
        tmp_path: Path,
    ) -> None:
        result = runner.invoke(cli, ["init", "--scope", "user", "--agent", "codex"])
        assert result.exit_code == 0, result.output
        config = tomllib.loads((user_home / ".codex" / "config.toml").read_text())
        server = config["mcp_servers"]["zenith"]
        unrelated = tmp_path / "unrelated workspace"
        unrelated.mkdir()

        launched = subprocess.run(
            [server["command"], *server["args"], "--help"],
            cwd=unrelated,
            env={**os.environ, **server["env"]},
            text=True,
            capture_output=True,
            check=False,
        )
        assert launched.returncode == 0, launched.stderr
        assert "Zenith MCP Server" in launched.stdout
        assert not (unrelated / ".codex").exists()
        assert not (unrelated / ".zenith").exists()


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
