# Contributing to Zenith

Thanks for your interest in improving Zenith! Contributions of all kinds are welcome — bug reports, documentation fixes, new provider integrations, and harness improvements.

## Development setup

The Python package lives in [`zenith/`](zenith/). You need Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

```bash
cd zenith
uv sync
```

## Running the checks

All three must pass before a PR can merge (they run in CI on Python 3.11–3.13):

```bash
uv run ruff check .   # lint
uv run mypy src       # type-check
uv run pytest -q      # tests
```

A handful of smoke tests exercise real ACP agents and are skipped automatically when the corresponding binaries (`claude-agent-acp`, `codex-acp`, or `opencode`) are not installed. Live provider checks can spend tokens and must stay explicitly opt-in; hermetic tests plus disposable host configuration checks are the default evidence floor.

## Pull requests

- Open an issue first for anything beyond a small fix, so we can align on the approach.
- Keep PRs focused: one logical change per PR.
- Add or update tests for behavior changes.
- Follow the existing code style — `ruff` (line length 100) and full type annotations checked by `mypy`.

## Adding a provider

Zenith's agent providers (Claude Code, Codex, Hermes, OpenCode, ...) are declared in [`zenith/src/zenith_harness/providers.py`](zenith/src/zenith_harness/providers.py), with per-provider assets under [`zenith/src/zenith_harness/bundled/providers/`](zenith/src/zenith_harness/bundled/providers/). New provider PRs should include an orchestrator prompt path, ACP adapter command, and tests in `tests/`.

### OpenCode PR-A boundaries

OpenCode support in this branch is project-scoped and experimental. Keep docs,
tests, and implementation aligned with `zenith init --agent opencode` generating
`.opencode/opencode.json`, `.opencode/orchestrator_prompt.md`, `.opencode/agents/`,
`.opencode/skills/`, and `.agents/skills/`. The managed OpenCode config should
contain only Zenith's `mcp.zenith` local MCP entry and safe Zenith routing
values; it must not persist provider API keys, OpenCode credentials, a default
model/provider, permission policy, plugin configuration, global OpenCode config,
or arbitrary provider secret environment variables.

Do not claim PR A proves live OpenCode worker or validator execution, OpenCode
model/effort ACP session options, isolated OpenCode terminal review, user-scoped
OpenCode setup, or provider-neutral billing grants. Those belong to later PR B/C
work. If you add future live OpenCode smoke tests, keep them opt-in and document
that normal worker and validator sessions use the credentials available to the
`opencode` process and therefore share the operator's billing trust boundary.

Keep the audience-specific OpenCode docs in sync with code changes:
[`docs/opencode-support/user.md`](docs/opencode-support/user.md),
[`docs/opencode-support/admin.md`](docs/opencode-support/admin.md), and
[`docs/opencode-support/developer.md`](docs/opencode-support/developer.md).

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).
