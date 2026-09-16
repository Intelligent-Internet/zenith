# OpenCode Support PRD

Status: Proposed

Owner: ExpansionX

Target repository: `ExpansionX/zenith`, proposed upstream contribution to
`Intelligent-Internet/zenith`

Research baseline: OpenCode v1.18.30 (2026-09-09)

## Summary

Add OpenCode as a first-class Zenith host and execution provider. A user must be
able to initialize a workspace for OpenCode, run the Zenith orchestrator from
OpenCode, and select OpenCode independently for worker, validator, and terminal
reviewer roles. OpenCode workers will use its native `opencode acp` server; no
third-party ACP adapter is required.

The integration must preserve existing OpenCode configuration, avoid silently
selecting a paid model, support explicit per-role model and reasoning-variant
selection, and retain Zenith's independent terminal-review boundary.

## Problem

Zenith currently recognizes only Claude Code, Codex, and Hermes. OpenCode users
can neither run `zenith init --agent opencode` nor select OpenCode for an
individual execution role, even though OpenCode already implements the ACP and
MCP capabilities Zenith needs.

A provider-table-only change would be incomplete:

- OpenCode uses `opencode.json`/`opencode.jsonc`, not Claude's `.mcp.json` or
  Codex TOML.
- Model IDs are `provider/model`, and reasoning levels are model-specific
  variants.
- Its ACP server exposes model, effort, and mode as session configuration
  options.
- Its ambient configuration can inject project/global rules, skills, agents,
  and plugins. That is useful for workers, but conflicts with Zenith's
  independent terminal-review contract.
- Authentication may come from environment variables, project `.env` files, or
  OpenCode's persistent credential store, so model selection has billing and
  trust-boundary consequences.

## Users

1. An OpenCode user who wants OpenCode to host and orchestrate a Zenith mission.
2. A mixed-provider user who wants, for example, OpenCode workers and a Codex or
   Claude validator.
3. An operator who must pin different OpenCode models or effort variants for
   workers, validators, and terminal review.
4. A maintainer adding future ACP providers without introducing another set of
   provider-name conditionals.

## Goals

- Make `opencode` a valid orchestrator, worker, validator, and terminal-reviewer
  provider.
- Generate an idempotent project-scoped OpenCode MCP registration for Zenith.
- Install OpenCode-compatible orchestrator, subagent, and skill assets.
- Use native `opencode acp` for dispatched sessions.
- Allow explicit per-role OpenCode model pins in `provider/model` form.
- Apply an explicitly requested reasoning effort only when the selected model
  exposes that variant.
- Preserve OpenCode's configured/default model when no role pin is supplied.
- Select OpenCode's writable `build` mode for worker sessions regardless of the
  user's interactive default agent.
- Fail clearly before useful work begins when a requested model, effort, mode,
  executable, or resolved MCP configuration is invalid.
- Isolate an OpenCode terminal reviewer from project/global instructions,
  skills, agents, and external plugins while retaining the minimum authorized
  model authentication needed to review.
- Add hermetic tests plus opt-in real-agent serial, parallel, and terminal-review
  smoke coverage.

## Non-goals

- Managing OpenCode login or creating provider credentials.
- Shipping or maintaining an OpenCode model catalog inside Zenith.
- Choosing a default paid model on the user's behalf.
- Translating provider-specific model option objects such as Anthropic thinking
  budgets or OpenAI text verbosity.
- Supporting arbitrary custom OpenCode variant names in the first release;
  Zenith's existing reasoning-effort vocabulary remains the public interface.
- Enabling OpenCode's own background subagent orchestration inside dispatched
  Zenith workers.
- User-scoped OpenCode installation in the first PR. It should follow the
  project-scoped implementation and align with upstream PR #23.
- Solving Zenith's existing Windows execution issues. WSL is the documented
  initial Windows path; native Windows must not be knowingly regressed.

## User experience

### OpenCode for every role

```bash
uv run zenith init \
  --workspace-dir /path/to/app \
  --agent opencode \
  --worker-model openai/gpt-5.2-codex \
  --worker-reasoning-effort high \
  --validator-model anthropic/claude-sonnet-4-5 \
  --validator-reasoning-effort high

cd /path/to/app
opencode
```

The user then invokes the generated Zenith skill or asks OpenCode to read
`.opencode/orchestrator_prompt.md` and run the mission.

### OpenCode for one role

```bash
uv run zenith init \
  --workspace-dir /path/to/app \
  --agent claude \
  --worker-provider opencode \
  --worker-model opencode/gpt-5.2
```

### Preserve OpenCode defaults

```bash
uv run zenith init --workspace-dir /path/to/app --agent opencode
```

With no model flags, Zenith does not write `model`, `small_model`, provider, or
variant settings. Each OpenCode ACP session uses the model selected by OpenCode's
normal precedence rules.

## Functional requirements

### Provider and initialization

- **OC-FR-001:** `opencode` is accepted by `--agent`,
  `--orchestrator-provider`, `--worker-provider`, `--validator-provider`, and
  `--terminal-reviewer-provider`.
- **OC-FR-002:** OpenCode defaults to `opencode acp` for execution roles.
- **OC-FR-003:** `zenith init --agent opencode` creates or updates only the
  managed `mcp.zenith` object in `.opencode/opencode.json`.
- **OC-FR-004:** The generated local MCP entry uses OpenCode's array-valued
  `command`, `environment`, `enabled`, and millisecond `timeout` fields.
- **OC-FR-005:** Re-running initialization is idempotent and preserves unrelated
  OpenCode settings and MCP servers.
- **OC-FR-006:** Initialization does not write a model, provider credentials,
  permissions policy, plugin list, or global configuration.
- **OC-FR-007:** If another higher-precedence OpenCode source overrides
  `mcp.zenith`, initialization reports the conflict and how to resolve it.

### Assets

- **OC-FR-010:** Zenith installs its orchestrator prompt at
  `.opencode/orchestrator_prompt.md` without replacing an existing customized
  copy.
- **OC-FR-011:** Zenith installs bundled skills to `.opencode/skills` and the
  shared `.agents/skills` surface without duplicate logical entries.
- **OC-FR-012:** OpenCode subagent files are installed under
  `.opencode/agents`, declare `mode: subagent`, inherit the invoking model unless
  explicitly pinned by the user, and encode read-only/no-delegation permissions
  for the reviewer/investigator roles.

### ACP execution

- **OC-FR-020:** Worker and validator sessions start through native
  `opencode acp` and receive the per-attempt `zenith-worker` MCP server in the
  ACP `session/new` request.
- **OC-FR-021:** Zenith selects ACP mode `build` before sending the task prompt.
- **OC-FR-022:** OpenCode-specific command/environment changes are capability
  driven and do not alter Claude, Codex, or Hermes behavior.
- **OC-FR-023:** OpenCode worker prompts continue to combine Zenith's role
  prompt and rendered task template into the first ACP user message.

### Models and reasoning

- **OC-FR-030:** Each execution role can receive an explicit model pin without
  leaking that pin across a provider boundary.
- **OC-FR-031:** An OpenCode model pin is passed after `session/new` through the
  ACP model configuration option, not interpolated into a shell command.
- **OC-FR-032:** Model selection occurs before effort selection because the
  available effort values depend on the selected model.
- **OC-FR-033:** If no model is pinned, Zenith leaves OpenCode's resolved model
  unchanged.
- **OC-FR-034:** If no reasoning effort is pinned, Zenith leaves OpenCode's
  resolved variant unchanged.
- **OC-FR-035:** A requested unavailable model or effort produces a concise
  role-specific failure containing the requested value and remediation command
  (`opencode models`, or selection of an advertised effort).
- **OC-FR-036:** Model IDs remain open-ended strings accepted as JSON data,
  including provider model IDs that themselves contain `/`; control characters
  are rejected and values are never treated as shell syntax.

### Security and isolation

- **OC-FR-040:** Zenith never serializes provider API keys or OpenCode's
  `auth.json` contents into workspace configuration, logs, handoffs, or receipts.
- **OC-FR-041:** Documentation states that normal OpenCode worker/validator
  sessions use the credentials available to the OpenCode process and therefore
  share the operator's billing trust boundary.
- **OC-FR-042:** OpenCode terminal review launches without external plugins,
  project config/rules, project/global external skills, or user-global OpenCode
  instructions.
- **OC-FR-043:** Terminal-review isolation must not silently fall back to an
  unisolated session. If the selected model cannot be made available inside the
  isolated context, terminal review reports a blocked/failed result with an
  actionable explanation.
- **OC-FR-044:** Process errors and diagnostic output are truncated and scrubbed
  using the same secret-free standards as other ACP providers.

### Compatibility and diagnostics

- **OC-FR-050:** The supported baseline is OpenCode v1.18.30 or newer within
  the tested ACP v1 behavior. Unsupported/missing binaries fail with a direct
  installation/version message.
- **OC-FR-051:** Project scope works on Linux and macOS. WSL is the supported
  initial Windows route.
- **OC-FR-052:** `zenith init` prints the resolved OpenCode host, execution
  roles, ACP commands, and model pins without printing credentials.

## Acceptance criteria

1. A clean disposable workspace initialized with `--agent opencode` exposes all
   Zenith orchestrator MCP tools in OpenCode.
2. A real OpenCode work task writes the expected fixture and calls `end_node`.
3. A real OpenCode validator independently reports assertion items and passes a
   known-good fixture.
4. Two OpenCode ACP workers can execute concurrently without session or MCP
   registration collisions.
5. Worker and validator can use two distinct `provider/model` pins in one
   mission, and their attempt evidence identifies the selected model without
   containing credentials.
6. An unavailable effort fails before the task is treated as completed.
7. Existing OpenCode configuration and unrelated MCP entries remain
   semantically unchanged; after the first managed update, a second identical
   `zenith init` run is byte-for-byte idempotent.
8. A terminal-review fixture containing forbidden project/global instructions,
   skills, and a plugin proves none are injected or callable.
9. Existing Claude, Codex, and Hermes unit tests remain green.
10. Ruff, mypy, and the full hermetic pytest suite pass on Python 3.11-3.13.

## Success measures

- OpenCode completes the existing real-ACP hello mission at the same functional
  evidence floor as Claude and Codex.
- No OpenCode-specific regression in the existing provider matrix.
- Initialization is repeatable and does not change model/provider preferences.
- Failures identify the role, command, model/effort request, and next action.
- No credential material appears in generated workspace files or test logs.

## Risks and open decisions

1. **Persistent authentication boundary:** OpenCode credentials live outside the
   project. A fully grant-scoped billing design may require generalizing upstream
   PR #39 rather than treating OpenCode authentication as ambient authority.
2. **Custom providers in terminal review:** isolating global/project config can
   also remove a custom provider definition. Initial support may need to reject
   those combinations until a safe minimal-provider projection is designed.
3. **JSONC precedence:** `.opencode/opencode.jsonc` loads after the managed JSON
   file and can override `mcp.zenith`. The initializer must diagnose this rather
   than destructively rewriting comments.
4. **OpenCode release cadence:** ACP configuration names are confirmed in
   v1.18.30 source, but should be exercised by live smoke tests and guarded with
   clear capability errors.
5. **Nested agents:** OpenCode supports subagents and experimental background
   subagents. Dispatched Zenith workers should not become unbounded nested
   orchestrators by default.

## Source references

- [OpenCode ACP documentation](https://opencode.ai/docs/acp/)
- [OpenCode configuration and precedence](https://opencode.ai/docs/config/)
- [OpenCode models and variants](https://opencode.ai/docs/models/)
- [OpenCode agents](https://opencode.ai/docs/agents/)
- [OpenCode permissions](https://opencode.ai/docs/permissions/)
- [OpenCode skills](https://opencode.ai/docs/skills/)
- [OpenCode MCP servers](https://opencode.ai/docs/mcp-servers/)
- [Pinned v1.18.30 ACP implementation](https://github.com/anomalyco/opencode/blob/v1.18.30/packages/opencode/src/acp/service.ts)
- [Pinned v1.18.30 ACP configuration options](https://github.com/anomalyco/opencode/blob/v1.18.30/packages/opencode/src/acp/config-option.ts)
