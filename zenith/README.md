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

Initialize the project workspace Zenith should operate on. This is your target
app/repo, not the Zenith source checkout:

```bash
# Claude Code, from this Zenith checkout
uv run zenith init --workspace-dir /path/to/your-app --agent claude

# Or Codex, from this Zenith checkout
uv run zenith init --workspace-dir /path/to/your-app --agent codex
```

Start your agent from the initialized project workspace:

```bash
cd /path/to/your-app

claude
# or
codex
```

Then ask the agent to read the generated orchestrator prompt:

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
