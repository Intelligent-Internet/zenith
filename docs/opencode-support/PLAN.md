# OpenCode Support Implementation Plan

Status: Ready for review

Inputs: `PRD.md`, `SPEC.md`

Branch strategy: focused feature branches from current upstream `main`

## Delivery strategy

Deliver the integration as three reviewable PRs. Do not combine upstream's
unrelated runtime-locking or dispatch-wait changes with OpenCode support.

1. **PR A — provider, host setup, and assets**
2. **PR B — ACP model/effort execution and live workers**
3. **PR C — terminal-review isolation and hardening**

Open an upstream feature issue before PR A, per `CONTRIBUTING.md`. Link the PRD
and summarize the phased scope, particularly the terminal-review and billing
boundaries.

## Preflight

### Task 0.1 — Record baselines

- Confirm local `main` matches `upstream/main` before branching.
- Record `opencode --version`; minimum researched release is v1.18.30.
- Run:

  ```bash
  cd zenith
  uv run ruff check .
  uv run mypy src
  uv run pytest -q
  ```

- Record skipped real-agent tests separately.

Exit condition: clean checkout and green hermetic baseline.

### Task 0.2 — Resolve overlap with upstream work

- Review current state of upstream PRs #35, #39, #33, and #23 immediately before
  implementation.
- If #35 merged, build on its per-role model fields rather than recreating them.
- If it remains open, keep the model-field commit isolated so it can be rebased
  or replaced cleanly.
- Do not copy #39's Codex-only secret handling into OpenCode; note the future
  provider-neutral authorization dependency.

Exit condition: branch base and ownership of overlapping code are documented in
the upstream issue.

## PR A — Provider, host setup, and assets

### Task A1 — Add failing provider-selection tests

Files:

- `zenith/tests/test_config.py`
- `zenith/tests/test_cli.py`

Add tests proving `opencode` is accepted for orchestrator, worker, validator,
and terminal reviewer, defaults its ACP command to `opencode acp`, and follows
existing command/provider inheritance rules.

Run focused tests and confirm they fail for the expected unsupported-provider
reason.

### Task A2 — Add the provider definition

File: `zenith/src/zenith_harness/providers.py`

- Extend provider and config-format literals.
- Add `opencode` to role lists.
- Add the provider definition and `build` ACP mode.
- Add the smallest capability fields needed by this PR; defer session-option
  behavior to PR B if that keeps the diff clearer.

Run:

```bash
uv run pytest -q tests/test_config.py
uv run mypy src
```

Commit boundary: `feat(providers): register OpenCode roles`.

### Task A3 — Specify OpenCode host-config behavior with tests

File: `zenith/tests/test_cli.py`

Cover:

- new `.opencode/opencode.json`;
- exact `mcp.zenith` schema;
- preservation of unrelated settings and MCPs;
- malformed/non-object existing JSON;
- idempotency;
- quoted paths and environment values;
- coexistence with `.opencode/opencode.jsonc`;
- no ambient API/model settings persisted;
- mixed provider routing values.

Tests must assert no partial write on failure.

### Task A4 — Implement the host-config writer

File: `zenith/src/zenith_harness/cli.py`

- Add the `opencode_config` branch.
- Generate the local MCP command array and `environment` mapping.
- Merge only `mcp.zenith` in strict JSON.
- Use atomic replacement.
- Add conservative JSONC override diagnostics without rewriting JSONC.
- Keep model/provider/permission/plugin settings untouched.

Run CLI tests, Ruff, and mypy.

Commit boundary: `feat(cli): initialize OpenCode MCP host config`.

### Task A5 — Add OpenCode assets

Files:

- `zenith/src/zenith_harness/bundled/providers/opencode/agents/*.md`
- `zenith/tests/test_assets.py`
- `zenith/tests/test_cli.py`

Adapt all four provider subagents with OpenCode frontmatter. Add tests for mode,
permissions, model inheritance, installation paths, skill deduplication, and
orchestrator prompt preservation.

Commit boundary: `feat(assets): add OpenCode orchestrator assets`.

### Task A6 — Document project-scoped host setup

Files:

- `README.md`
- `zenith/README.md`
- `CONTRIBUTING.md`
- `zenith/pyproject.toml`

Add installation, initialization, generated paths, and current scope. Do not yet
claim verified worker execution.

### PR A verification

```bash
cd zenith
uv run ruff check .
uv run mypy src
uv run pytest -q
```

Disposable-host check:

1. initialize a temporary git workspace twice;
2. run `opencode debug config` there;
3. verify `mcp.zenith` resolves to the generated command and environment;
4. run `opencode mcp list` and verify Zenith connects;
5. confirm unrelated JSON/JSONC remains unchanged.

## PR B — ACP execution, models, and effort

### Task B1 — Land/generalize per-role model fields

Files:

- `zenith/src/zenith_harness/config.py`
- `zenith/src/zenith_harness/providers.py`
- `zenith/src/zenith_harness/cli.py`
- `zenith/tests/test_config.py`
- `zenith/tests/test_cli.py`

Implement `ZENITH_{WORKER,VALIDATOR,TERMINAL_REVIEWER}_MODEL` and matching CLI
flags using same-provider-only inheritance. Preserve unset OpenCode model and
effort values. Coordinate with upstream PR #35 rather than duplicating its
Codex/Claude work.

Commit boundary: `feat(config): support provider-scoped role model pins`.

### Task B2 — Extend the mock ACP agent first

File: `zenith/tests/mock_acp_agent.py`

Add deterministic fixtures for:

- `session/new` option advertisement;
- ordered `session/set_config_option` requests;
- model-dependent effort lists;
- invalid model/effort errors;
- mode selection;
- session MCP registration capture.

Keep all behavior opt-in through mock environment variables so existing tests
remain unchanged.

### Task B3 — Add session-option unit tests

File: `zenith/tests/test_acp_runner.py`

Write failing tests for:

- OpenCode launch command/environment;
- model then effort then mode then prompt ordering;
- no selection calls when pins are absent;
- provider/model IDs with nested slashes;
- model rejection and effort mismatch;
- worker/validator pin separation;
- missing build mode;
- no Codex config flags or `CODEX_CONFIG` mutation for OpenCode.

### Task B4 — Implement ACP session configuration

File: `zenith/src/zenith_harness/acp_runner.py`

- Capture `configOptions` from `session/new`.
- Add a typed helper for `session/set_config_option`.
- Select model first, effort second, mode third.
- Update advertised options after each successful request.
- Leave absent values untouched.
- Convert failures into concise `ACPError` diagnostics.
- Use provider capabilities rather than broad name checks.

Apply identical behavior to normal nodes and terminal-review sessions through a
shared session setup helper.

Commit boundary: `feat(acp): configure OpenCode model and effort per role`.

### Task B5 — Add opt-in real OpenCode smoke tests

Files:

- `zenith/tests/test_smoke_real_acp.py`
- `zenith/tests/test_smoke_parallel_acp.py`

Add `opencode` gating and command override. Exercise:

1. default-model work plus validation;
2. explicit valid model/effort;
3. mixed worker and validator pins;
4. two parallel workers.

Use disposable workspaces and a dedicated low-cost test account/model where
available. Never print auth data or the full subprocess environment.

### Task B6 — Document model selection

Document:

- discover IDs with `opencode models [provider]`;
- IDs use `provider/model`;
- effort values are selected-model variants;
- explicit role pins override OpenCode defaults only for that session;
- no pin preserves OpenCode precedence;
- custom model option objects remain OpenCode config responsibility;
- OpenCode credentials are an operator billing boundary.

### PR B verification

Run all static/hermetic checks, then opt-in serial and parallel OpenCode smokes.
Record exact OpenCode version and safe model IDs in the PR description.

## PR C — Terminal-review isolation and hardening

### Task C1 — Build an adversarial isolation fixture

Add test-only project and fake-home fixtures containing:

- `AGENTS.md` with a recognizable canary;
- `.opencode/skills/.../SKILL.md` canary;
- `.agents/skills/.../SKILL.md` canary;
- global OpenCode `AGENTS.md` and skill canaries;
- external plugin canary;
- unrelated provider configuration.

The reviewer must neither report seeing the canaries nor have their tools
available. A prompt-level prohibition alone is not evidence.

### Task C2 — Implement role-specific launch context

Files:

- `zenith/src/zenith_harness/acp_runner.py`
- optionally a focused isolation/config helper module

- Pass role into command/environment construction.
- Add `--pure` only for the OpenCode terminal reviewer.
- Set project/external-skill/Claude-compatibility disable flags.
- Create an owner-only temporary `HOME` and `XDG_CONFIG_HOME` so `~/.opencode`
  and user-global instructions cannot be discovered.
- Supply minimal inline config for the selected reviewer model and permissions.
- Reuse the existing `XDG_DATA_HOME` only after explicit operator acceptance of
  that credential-store boundary; do not copy or log its contents.
- Clean up after success, failure, cancellation, and timeout.
- Fail closed for unsupported custom-provider isolation.

Commit boundary: `security(opencode): isolate terminal reviewer context`.

### Task C3 — Test failure and cleanup paths

Cover:

- missing isolated model/provider;
- malformed managed config;
- process crash and timeout;
- cancellation cleanup;
- no temporary paths or secrets in handoffs;
- managed system policy remains an explicitly documented boundary.

### Task C4 — Run real terminal-review smoke

Run one known-clean and one deliberate-defect review. Confirm:

- declared artifacts are readable;
- ephemeral Zenith MCP handoff works;
- project/global canaries are not injected;
- selected model/effort is honored;
- no credentials appear in output.

### Task C5 — Security documentation

Add a support matrix for built-in versus custom providers under isolated review,
billing authority, managed policy, and recommended use of a dedicated OpenCode
profile/account for long-running missions.

## Deferred follow-ups

- User-scoped OpenCode setup aligned with upstream PR #23.
- Provider-neutral API billing grants aligned with upstream PR #39.
- Runtime identity receipts containing safe provider/model/variant fields.
- Native Windows ACP smoke coverage after upstream issue #8 is resolved.
- Arbitrary custom OpenCode variant names.
- Capability negotiation for future ACP versions instead of a version floor.

## Review checklist for every PR

- Scope matches the PR description; no unrelated upstream fixes included.
- Existing user configuration is preserved.
- No new default model, provider, cost, permission, or plugin behavior.
- No API keys, credential files, inline config secrets, or environments logged.
- New errors name the affected role and remediation.
- Unit tests cover cross-provider inheritance and negative paths.
- Documentation distinguishes hermetic tests from paid live smoke tests.
- `uv run ruff check .`, `uv run mypy src`, and `uv run pytest -q` pass.

## Estimated effort

| Work | Estimate |
|---|---:|
| PR A: provider, host config, assets | 2–3 engineering days |
| PR B: role models, ACP options, live workers | 2–3 engineering days |
| PR C: terminal isolation and hardening | 2–4 engineering days |
| Upstream review/rebase contingency | 1–2 engineering days |

Expected merge-quality total: 7–12 engineering days, depending primarily on
terminal-review authentication isolation and overlap with upstream PR #35.
