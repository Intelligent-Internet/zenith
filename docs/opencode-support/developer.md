---
audience: developer
component: opencode-support
sources:
  - zenith/pyproject.toml
  - zenith/src/zenith_harness/providers.py
  - zenith/src/zenith_harness/cli.py
  - zenith/src/zenith_harness/acp_runner.py
  - zenith/src/zenith_harness/bundled/providers/opencode/agents/contract-review.md
  - zenith/src/zenith_harness/bundled/providers/opencode/agents/feature-reviewer.md
  - zenith/src/zenith_harness/bundled/providers/opencode/agents/flow-validator.md
  - zenith/src/zenith_harness/bundled/providers/opencode/agents/investigator.md
  - zenith/tests/test_config.py
  - zenith/tests/test_cli.py
  - zenith/tests/test_assets.py
  - zenith/tests/test_acp_runner.py
generated: 2026-09-16
---

# OpenCode Developer Guide

This guide describes the PR-A OpenCode implementation surface so future changes
can keep provider behavior, generated assets, and validation boundaries aligned.

## Component Summary

OpenCode support is implemented inside the `zenith-harness` Python package. The
package metadata declares `opencode` as a dependency, and the provider registry
accepts `opencode` for orchestrator, worker, validator, and terminal-reviewer
roles.

The OpenCode provider definition uses:

- `config_format="opencode_config"`
- `default_worker_acp_command="opencode acp"`
- `agent_output_dir=".opencode/agents"`
- `orchestrator_prompt_output_path=".opencode/orchestrator_prompt.md"`
- `skill_dirs=(".opencode/skills", ".agents/skills")`
- `acp_runtime_mode="build"`
- `acp_supports_system_prompt=False`

## Initialization Flow

`zenith init --agent opencode` resolves a `ProviderSelection`, writes OpenCode
assets, and writes `.opencode/opencode.json` through the OpenCode-specific
writer in `cli.py`.

The OpenCode config writer must keep these properties:

- strict JSON is parsed and preserved rather than regenerated from scratch
- unrelated strict JSON settings and unrelated MCP servers survive
- writes are atomic and avoid partial files on failure
- a second identical initialization is byte-idempotent
- JSONC files are never rewritten or normalized
- root strict `opencode.json` and JSONC `mcp.zenith` conflicts fail clearly
- OpenCode config does not receive forwarded runtime env secrets/defaults

OpenCode diagnostics are emitted only for OpenCode host configuration. They
print resolved host, roles, ACP commands, and absent model-pin status without
dumping raw credential values.

## ACP Runtime Behavior

The OpenCode provider's `acp_runtime_mode` is `build`. During ACP session setup,
the runner still uses the existing `session/set_mode` path for provider runtime
mode. The Claude settings workaround is scoped to the Claude provider only, so
OpenCode runtime mode must not create or modify `.claude/settings.json`.

PR-A deliberately does not implement OpenCode ACP model or effort session
options. Those remain PR-B work.

## Bundled Assets

OpenCode subagents are bundled as Markdown frontmatter files under
`zenith/src/zenith_harness/bundled/providers/opencode/agents/`:

- `investigator.md`
- `contract-review.md`
- `feature-reviewer.md`
- `flow-validator.md`

Their bodies preserve the role intent of the Claude agents while using
OpenCode-compatible asset shape. Initialization installs these assets under the
target workspace's `.opencode/agents/` directory and installs bundled skills
under both `.opencode/skills/` and `.agents/skills/`.

## Tests To Keep Current

The PR-A behavior is covered across four focused test modules:

- `tests/test_config.py`: provider registration, default ACP command, role
  resolution, and provider switching.
- `tests/test_cli.py`: strict JSON write/merge behavior, idempotency, JSONC and
  root strict conflict failures, no ambient secret/default persistence,
  diagnostics, mixed-provider routing, prompt/agent/skill installation, and
  asset preservation.
- `tests/test_assets.py`: OpenCode agent frontmatter and body parity.
- `tests/test_acp_runner.py`: build-mode selection and the guard that prevents
  OpenCode from writing Claude host settings.

Before opening or updating an OpenCode support PR, run:

```bash
cd zenith
uv run ruff check .
uv run mypy src
uv run pytest -q
uv build
```

For real host-surface validation, also run disposable OpenCode checks:

```bash
tmp="$(mktemp -d)"
git -C "$tmp" init
uv run zenith init --workspace-dir "$tmp" --agent opencode
uv run zenith init --workspace-dir "$tmp" --agent opencode
cd "$tmp"
opencode debug config
opencode mcp list
```

## Future Boundaries

Keep PR-A focused. Do not backfill these future surfaces into PR-A maintenance
work unless a later design explicitly changes the boundary:

- PR B: per-role OpenCode model fields, model/effort session options, live
  OpenCode worker/validator smokes, and model-selection docs.
- PR C: isolated OpenCode terminal review, hardening, `--pure`/isolated homes,
  and canary fixtures.
- Separate future work: user-scoped OpenCode setup and provider-neutral billing
  grants.

When adding future behavior, update the user, admin, and developer audience docs
in this directory in the same PR as the code change.
