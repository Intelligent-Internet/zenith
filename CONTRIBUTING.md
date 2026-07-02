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

A handful of smoke tests exercise real ACP agents and are skipped automatically when the corresponding binaries (`claude-agent-acp`, `codex-acp`) are not installed.

## Pull requests

- Open an issue first for anything beyond a small fix, so we can align on the approach.
- Keep PRs focused: one logical change per PR.
- Add or update tests for behavior changes.
- Follow the existing code style — `ruff` (line length 100) and full type annotations checked by `mypy`.

## Adding a provider

Zenith's agent providers (Claude Code, Codex, Hermes, …) are declared in [`zenith/src/zenith_harness/providers.py`](zenith/src/zenith_harness/providers.py), with per-provider assets under [`zenith/src/zenith_harness/bundled/providers/`](zenith/src/zenith_harness/bundled/providers/). New provider PRs should include an orchestrator prompt path, ACP adapter command, and tests in `tests/`.

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).
