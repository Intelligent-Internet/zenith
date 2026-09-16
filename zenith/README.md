# Zenith

Zenith is a small MCP/ACP harness for running a coding agent as a multi-agent
orchestrator.

## Quick Run

Requirements:

- Python 3.11+
- `uv`
- Node.js 22+ and `npm`
- Claude Code, Codex, Hermes, or OpenCode

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

OpenCode uses its native ACP server instead of a third-party adapter. Install
OpenCode with the current OpenCode instructions for your platform, then confirm
that `opencode` is available:

```bash
curl -fsSL https://opencode.ai/install | bash
command -v opencode
opencode --version
```

Initialize the project workspace Zenith should operate on. This is your target
app/repo, not the Zenith source checkout:

```bash
# Claude Code, from this Zenith checkout
uv run zenith init --workspace-dir /path/to/your-app --agent claude

# Or Codex, from this Zenith checkout
uv run zenith init --workspace-dir /path/to/your-app --agent codex

# Or OpenCode, from this Zenith checkout
uv run zenith init --workspace-dir /path/to/your-app --agent opencode
```

Start your agent from the initialized project workspace:

```bash
cd /path/to/your-app

claude
# or
codex
# or
opencode
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

For OpenCode, use:

```text
First read .opencode/orchestrator_prompt.md and treat it as your primary role, then use Zenith to run this mission.

<your instruction or query>
```

### OpenCode PR-A scope

`zenith init --agent opencode` is project-scoped. It manages only Zenith's
`mcp.zenith` entry in `.opencode/opencode.json`, creates
`.opencode/orchestrator_prompt.md`, installs subagents in `.opencode/agents/`,
and installs bundled skills in `.opencode/skills/` and `.agents/skills/`.
Unrelated strict JSON settings and MCP servers are preserved, and JSONC files
are not rewritten.

OpenCode support is experimental in PR A. It registers OpenCode as a Zenith host
and execution provider using `opencode acp` and normal `build` mode sessions,
but it does not claim verified live OpenCode worker execution, OpenCode
model/effort session options, isolated OpenCode terminal review, user-scoped
setup, or billing grants. Provider credentials and billing authority stay with
the `opencode` process; Zenith does not write OpenCode credentials, default
models, permission policy, plugin configuration, or global config.

Default checks are hermetic. Live OpenCode provider checks may spend tokens and
must remain explicit opt-in tests.

Detailed OpenCode guidance is split by audience in the repository docs:
[user guide](../docs/opencode-support/user.md),
[admin guide](../docs/opencode-support/admin.md), and
[developer guide](../docs/opencode-support/developer.md).

## Development

```bash
uv run pytest
```

## License

Apache License 2.0 — see the repository [LICENSE](../LICENSE).
