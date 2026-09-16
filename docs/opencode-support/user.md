---
audience: user
component: opencode-support
sources:
  - zenith/README.md
  - README.md
  - zenith/src/zenith_harness/providers.py
  - zenith/src/zenith_harness/cli.py
  - zenith/tests/test_cli.py
generated: 2026-09-16
---

# OpenCode User Guide

OpenCode support lets you initialize a target project so OpenCode can connect to
Zenith as the orchestrator host and run Zenith worker, validator, and terminal
review roles through OpenCode's native ACP command. The PR-A implementation is
project-scoped and experimental: it sets up the OpenCode host surface and local
configuration, but it does not claim live paid OpenCode worker execution or
OpenCode model/effort session controls.

## Requirements

Install the normal Zenith requirements first:

- Python 3.11+
- `uv`
- Node.js 22+ and `npm`
- OpenCode on `PATH`

OpenCode does not need a third-party ACP adapter for Zenith. It uses the native
`opencode acp` command registered in Zenith's provider table.

```bash
curl -fsSL https://opencode.ai/install | bash
command -v opencode
opencode --version
```

PR-A compatibility was validated against OpenCode `1.18.30`.

## Initialize A Project

Run initialization from the Zenith checkout, pointing `--workspace-dir` at the
target project that Zenith should operate on:

```bash
cd /path/to/zenith/zenith
uv run zenith init --workspace-dir /path/to/your-app --agent opencode
```

The command writes only project-local OpenCode files:

- `.opencode/opencode.json`
- `.opencode/orchestrator_prompt.md`
- `.opencode/agents/`
- `.opencode/skills/`
- `.agents/skills/`

It prints OpenCode diagnostics that include the generated host path, resolved
roles, ACP commands, and the fact that model pins are absent. Secret-looking
command fragments are redacted in diagnostics.

## Start A Mission From OpenCode

Start OpenCode from the initialized target project:

```bash
cd /path/to/your-app
opencode
```

Then ask OpenCode to use the generated Zenith prompt:

```text
First read .opencode/orchestrator_prompt.md and treat it as your primary role, then use Zenith to run this mission.

<your instruction or query>
```

## Generated Configuration

`zenith init --agent opencode` manages the `mcp.zenith` entry in
`.opencode/opencode.json`. The generated server is local and points back to the
Zenith checkout:

```json
{
  "mcp": {
    "zenith": {
      "type": "local",
      "command": ["uv", "run", "--project", "/path/to/zenith", "zenith-server", "--mode", "orchestrator"],
      "enabled": true,
      "timeout": 1000000,
      "environment": {
        "ZENITH_ORCHESTRATOR_PROVIDER": "opencode",
        "ZENITH_WORKER_PROVIDER": "opencode",
        "ZENITH_WORKER_ACP_COMMAND": "opencode acp"
      }
    }
  }
}
```

The exact `--project` path depends on the Zenith checkout used to run
initialization.

## What Zenith Preserves

Zenith preserves unrelated strict JSON settings and unrelated OpenCode MCP
servers in `.opencode/opencode.json`. Re-running the same initialization is
byte-idempotent once the managed entry already exists.

Zenith never rewrites or normalizes JSONC. If a JSONC source or project-root
strict `opencode.json` defines `mcp.zenith`, initialization fails with
remediation instead of silently allowing OpenCode to shadow or merge into the
managed server.

## Current Limits

PR-A does not select or persist an OpenCode model, provider credential,
permission policy, plugin configuration, global OpenCode config, or arbitrary
provider secret. Provider access and billing remain with the `opencode` process
you run locally.

The following are intentionally future work:

- per-role OpenCode model and effort session options
- verified live OpenCode worker and validator smoke tests
- isolated OpenCode terminal review
- user-scoped OpenCode setup
- provider-neutral billing grants
