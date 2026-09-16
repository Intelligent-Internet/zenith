---
audience: admin
component: opencode-support
sources:
  - README.md
  - zenith/README.md
  - zenith/src/zenith_harness/cli.py
  - zenith/src/zenith_harness/providers.py
  - zenith/tests/test_cli.py
generated: 2026-09-16
---

# OpenCode Admin Guide

This guide covers the operational and security boundaries of Zenith's
project-scoped OpenCode support. Use it when reviewing what `zenith init
--agent opencode` writes, what it refuses to write, and how to verify the
generated host configuration.

## Managed Surface

OpenCode support is project-local. The managed configuration lives in
`.opencode/opencode.json` under the single MCP server key `mcp.zenith`.

The managed entry uses OpenCode's local MCP server shape:

- `type: "local"`
- `command`: an array beginning with `uv run --project <zenith-checkout>`
- `enabled: true`
- `timeout: 1000000`
- `environment`: Zenith routing values only

The default OpenCode routing values are:

- `ZENITH_ORCHESTRATOR_PROVIDER=opencode`
- `ZENITH_WORKER_PROVIDER=opencode`
- `ZENITH_WORKER_ACP_COMMAND=opencode acp`

When a mixed-provider initialization is requested, the generated environment
may also include validator or terminal-reviewer provider and ACP command keys.

## Preservation And Conflict Policy

Zenith preserves:

- unrelated top-level strict JSON settings
- unrelated entries under `mcp`
- existing customized `.opencode/orchestrator_prompt.md`
- existing skills that are not replaced by bundled Zenith skills

Zenith fails closed instead of mutating or normalizing unsafe inputs:

- malformed `.opencode/opencode.json`
- non-object `.opencode/opencode.json`
- non-object `mcp`
- `.opencode/opencode.jsonc` defining `mcp.zenith`
- project-root `opencode.jsonc` defining `mcp.zenith`
- project-root strict `opencode.json` defining `mcp.zenith`

The root strict JSON guard exists because OpenCode can load project-root config
alongside `.opencode/opencode.json` and merge user-controlled `mcp.zenith` data
into the effective server registration. Zenith refuses that situation unless
the managed `.opencode/opencode.json` entry can remain the sole `mcp.zenith`
source.

## Security Boundary

Zenith does not persist OpenCode provider credentials or host policy choices.
The generated OpenCode config must not contain:

- API keys or provider tokens
- OpenCode default model or provider preferences
- permission policy
- plugin configuration
- global OpenCode config
- arbitrary provider secret environment variables

Normal OpenCode worker and validator sessions use whatever credentials and
billing access are available to the `opencode` process. Live provider checks can
spend tokens and should remain explicitly opt-in. The default validation floor is
hermetic tests plus disposable local OpenCode configuration checks.

## Operational Verification

Use a disposable workspace when verifying host configuration:

```bash
tmp="$(mktemp -d)"
git -C "$tmp" init
cd /path/to/zenith/zenith
uv run zenith init --workspace-dir "$tmp" --agent opencode
uv run zenith init --workspace-dir "$tmp" --agent opencode
cd "$tmp"
opencode debug config
opencode mcp list
```

Expected results:

- the second initialization leaves `.opencode/opencode.json` byte-identical
- `opencode debug config` resolves `mcp.zenith`
- `opencode mcp list` reports `zenith connected`
- no credentials or ambient model/plugin/permission sentinels appear in stdout
  or generated config

## Troubleshooting

If initialization reports that a root or JSONC file defines `mcp.zenith`, remove
or rename that user-controlled server entry, then re-run initialization. Keep
Zenith's managed `mcp.zenith` only in `.opencode/opencode.json`.

If `opencode mcp list` does not connect, first inspect `opencode debug config`
and confirm the generated command points to the expected Zenith checkout. Then
run `uv run zenith-server --mode orchestrator` from that checkout to confirm the
runtime can start.
