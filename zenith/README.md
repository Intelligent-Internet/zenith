# Zenith

Zenith is a small MCP/ACP harness for running a coding agent as a multi-agent
orchestrator.

## Quick Run

Requirements:

- Python 3.11+
- `uv`
- Node.js 22+ and `npm`
- Claude Code or Codex

Install Zenith from this repository:

```bash
uv sync
uv run zenith --help
```

Install the ACP adapters globally for the agents you want Zenith to run:

```bash
# Claude workers/validators
npm install -g @agentclientprotocol/claude-agent-acp
command -v claude-agent-acp

# Codex workers/validators
npm install -g @agentclientprotocol/codex-acp
command -v codex-acp
```

Install Zenith once for every workspace in your user account:

```bash
# Claude Code
uv run zenith init --scope user --agent claude

# Codex
uv run zenith init --scope user --agent codex

# Run both commands if you use both hosts.
```

This registers the user-scoped MCP server and installs a personal `/zenith`
skill, orchestrator prompt, agents, and playbooks. Existing model, reasoning,
sandbox, feature, and unrelated MCP settings are preserved. Ambient API/model
environment variables are not copied into the user configuration.

`CODEX_HOME` and `CLAUDE_CONFIG_DIR` are honored. The generated MCP command
contains the absolute path to this checkout, so rerun setup after moving it.
Hermes currently supports project scope only.

Restart Claude Code or Codex once, then use Zenith from any workspace:

```text
/zenith <your instruction or query>
```

For repository-specific setup, initialize the target app/repo instead:

```bash
uv run zenith init --scope project --workspace-dir /path/to/your-app --agent claude
uv run zenith init --scope project --workspace-dir /path/to/your-app --agent codex
uv run zenith init --scope project --workspace-dir /path/to/your-app --agent hermes
```

Project scope is the backward-compatible default, so `--scope project` may be
omitted. Start the host in that workspace and ask it to read the generated
orchestrator prompt:

```text
First read .claude/orchestrator_prompt.md and treat it as your primary role, then use Zenith to run this mission.

<your instruction or query>
```

For Codex, use:

```text
First read .codex/orchestrator_prompt.md and treat it as your primary role, then use Zenith to run this mission.

<your instruction or query>
```

## Development

```bash
uv run pytest
```

## License

Apache License 2.0 — see the repository [LICENSE](../LICENSE).
