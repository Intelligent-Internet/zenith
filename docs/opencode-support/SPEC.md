# OpenCode Support Technical Specification

Status: Proposed

Depends on: `PRD.md`

Compatibility baseline: Zenith `main` at `a8d9b57`; OpenCode v1.18.30

## 1. Design overview

OpenCode participates in two separate integrations:

```text
OpenCode host
  -> project .opencode/opencode.json
  -> Zenith orchestrator MCP server
  -> Zenith controller/coordinator
  -> role-selected ACP subprocess: opencode acp
  -> ACP session/new with ephemeral zenith-worker MCP
  -> model option -> effort option -> build mode -> task prompt
  -> end_node handoff
```

The host side is OpenCode JSON configuration and project assets. The execution
side uses the existing generic ACP client, with provider capabilities governing
session configuration and isolation.

## 2. Provider model

### 2.1 Names and configuration format

Update `zenith/src/zenith_harness/providers.py`:

```python
ProviderName = Literal["claude", "codex", "hermes", "opencode"]
ConfigFormat = Literal["mcp_json", "codex_config", "opencode_config"]
```

Add `opencode` to all role name tuples and define:

```python
"opencode": ProviderDefinition(
    name="opencode",
    skill_dirs=(".opencode/skills", ".agents/skills"),
    skill_alias_dirs=(".opencode/skills", ".agents/skills"),
    config_format="opencode_config",
    default_worker_acp_command="opencode acp",
    agent_output_dir=".opencode/agents",
    orchestrator_prompt_output_path=".opencode/orchestrator_prompt.md",
    acp_supports_system_prompt=False,
    acp_runtime_mode="build",
)
```

`acp_supports_system_prompt=False` documents that Zenith continues its existing
portable behavior: concatenate role instructions and task template into the
first user message.

### 2.2 Capabilities

Avoid adding scattered `provider.name == "opencode"` branches. Extend
`ProviderDefinition` with explicit capabilities:

```python
ACPConfigStrategy = Literal["none", "codex_env", "session_options"]

@dataclass(frozen=True)
class ProviderDefinition:
    # existing fields...
    acp_config_strategy: ACPConfigStrategy = "none"
    supports_model_pin: bool = False
    supports_reasoning_effort: bool = False
    terminal_review_isolation: Literal["none", "claude_meta", "opencode_env"] = "none"
```

Assignments:

| Provider | ACP config strategy | Model pin | Effort | Terminal isolation |
|---|---|---:|---:|---|
| Claude | none/environment after upstream #35 | planned | no generic ACP option | `claude_meta` after #33 |
| Codex | `codex_env` | yes after #35 | yes | current behavior |
| Hermes | none | not initially | no | none |
| OpenCode | `session_options` | yes | yes | `opencode_env` |

This refactor is deliberately small: it describes launch/session behavior while
leaving provider selection and role inheritance intact.

## 3. Role model configuration

### 3.1 Configuration fields

Add the per-role fields proposed by upstream PR #35 to `HarnessConfig`:

```python
worker_model: str | None
validator_model: str | None
terminal_reviewer_model: str | None
```

Add CLI options and durable environment names:

| CLI option | Environment variable |
|---|---|
| `--worker-model` | `ZENITH_WORKER_MODEL` |
| `--validator-model` | `ZENITH_VALIDATOR_MODEL` |
| `--terminal-reviewer-model` | `ZENITH_TERMINAL_REVIEWER_MODEL` |

Role inheritance follows the provider chain:

1. An explicit role model wins.
2. A role inherits the preceding role's model only when both roles use the same
   provider.
3. A provider switch clears inheritance unless that role has an explicit pin.
4. No pin means provider default.

The same inheritance rule applies to reasoning effort, but an unspecified
OpenCode effort must remain unspecified; unlike Codex, OpenCode must not receive
Zenith's historical implicit `xhigh` default.

### 3.2 Model validation

OpenCode model values are JSON data, not shell fragments. Validate only:

- non-empty;
- no NUL or ASCII control characters;
- contains a non-empty provider prefix and model suffix separated by `/`;
- reasonable maximum length (512 characters).

Do not split at the last slash or reject additional slashes: OpenCode model IDs
may be provider-defined and its ACP parser first attempts the complete suffix as
a model ID. Do not maintain an allowlist; availability is session-specific.

Reasoning-effort input retains Zenith's existing allowlist. Add `none` if the
corresponding Codex path supports it; otherwise validate per provider so an
OpenCode OpenAI model may request `none` without changing Codex behavior.

### 3.3 ACP selection sequence

After `session/new`, retain its `configOptions`. For providers using
`session_options`:

1. If a role model is pinned, send:

   ```json
   {
     "method": "session/set_config_option",
     "params": {
       "sessionId": "...",
       "configId": "model",
       "value": "provider/model"
     }
   }
   ```

2. Replace the local option snapshot with the response's `configOptions` when
   returned.
3. If reasoning effort is pinned, verify `effort` is advertised for the now
   selected model, then send the same method with `configId: "effort"`.
4. Select mode `build` using the existing `session/set_mode` request. If a
   future ACP implementation removes that compatibility method, add a fallback
   to the `mode` configuration option only when advertised.
5. Send the task prompt.

Model must precede effort because OpenCode rebuilds the effort option from the
selected model's variants. A rejected request becomes `ACPError` with provider,
role, requested value, and a non-secret list or count of advertised choices.

When no model/effort pin exists, send neither option. This preserves OpenCode's
selection order: CLI pin, config model, last-used model, then internal default.

## 4. Host configuration

### 4.1 Managed file

Use `.opencode/opencode.json` for Zenith-owned project configuration. This keeps
the repository-root `opencode.json[c]` under user control while using an
officially loaded `.opencode` config directory.

The managed object is:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "zenith": {
      "type": "local",
      "command": [
        "uv",
        "run",
        "--project",
        "/absolute/path/to/zenith",
        "zenith-server",
        "--mode",
        "orchestrator"
      ],
      "enabled": true,
      "timeout": 1000000,
      "environment": {
        "ZENITH_ORCHESTRATOR_PROVIDER": "opencode",
        "ZENITH_WORKER_PROVIDER": "opencode"
      }
    }
  }
}
```

OpenCode's field is `environment`, not Claude's `env`. `timeout` is
milliseconds. The command is one array rather than command plus args.

### 4.2 Merge behavior

Implement `_write_opencode_config(path, entry)` with these rules:

1. Missing file: create formatted strict JSON with schema and managed entry.
2. Existing strict JSON object: replace only `mcp.zenith`; retain all other
   parsed values and preserve deterministic indentation/key order as far as the
   current serializer permits.
3. Non-object or invalid JSON: fail before writing.
4. Existing `.opencode/opencode.jsonc` remains untouched. Because OpenCode loads
   it after `.json`, detect and report when its resolved `mcp.zenith` overrides
   the managed entry. Do not strip comments or rewrite it as JSON.
5. Write atomically through a sibling temporary file and `os.replace`.
6. A second identical initialization makes no content change.

The initial implementation may use a conservative text/provenance check for
JSONC conflicts, backed by a resolved-config integration test. It must prefer a
clear refusal over modifying a user-commented file.

### 4.3 Environment persistence

Persist Zenith routing/storage values and explicit CLI role pins. Do not add
OpenCode provider credentials to `RUNTIME_ENV_FORWARD_ALLOWLIST`. In
particular, initialization must not copy arbitrary provider keys merely because
OpenCode supports that provider.

Normal runtime subprocesses inherit the environment already available to the
Zenith MCP server. That is an operator trust boundary and must be documented.

## 5. Assets

Add `bundled/providers/opencode/agents/*.md` for:

- `investigator`
- `contract-review`
- `feature-reviewer`
- `flow-validator`

Reuse the corresponding instruction bodies, but use OpenCode frontmatter:

```yaml
---
description: "..."
mode: subagent
permission:
  edit: deny
  task: deny
---
```

Omit `model` so the subagent inherits the invoking primary model. Preserve bash,
read, search, and skill access needed by each role; prompts remain the primary
scope boundary, while `edit: deny` and `task: deny` enforce their leaf/read-only
properties.

Install bundled skills into both `.opencode/skills` and `.agents/skills` through
the existing deduplication path. Keep the generated orchestrator prompt
separate from `AGENTS.md`; Zenith must not overwrite the project's general
OpenCode instructions.

## 6. ACP subprocess behavior

### 6.1 Workers and validators

Default command: `opencode acp`.

- Do not append Codex `-c` flags.
- Preserve `PATH` and normal OpenCode authentication paths.
- Pass the ephemeral `zenith-worker` HTTP MCP server in `session/new`; OpenCode
  v1.18.30 registers these session-scoped servers natively.
- Explicitly select `build` before prompting.
- Do not enable OpenCode background subagents or change `subagent_depth`.
- Do not use `--pure` for normal workers because project plugins may be part of
  the user's declared implementation environment.

### 6.2 Terminal reviewer

The OpenCode reviewer must use a role-specific environment and command:

```text
opencode acp --pure
OPENCODE_DISABLE_PROJECT_CONFIG=1
OPENCODE_DISABLE_EXTERNAL_SKILLS=1
OPENCODE_DISABLE_CLAUDE_CODE_PROMPT=1
OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1
HOME=<fresh reviewer home>
XDG_CONFIG_HOME=<fresh reviewer config root>
XDG_DATA_HOME=<operator-authorized OpenCode data root>
OPENCODE_CONFIG_CONTENT=<minimal inline role config>
```

Properties:

- `--pure` removes external plugins.
- project config disabled removes project `opencode.json[c]`, `.opencode`
  directories, and project instruction discovery.
- external skill flags remove `.agents`/`.claude` skill discovery.
- the fresh home and XDG config root remove `~/.opencode`, `~/.claude`, and
  user-global OpenCode instructions, agents, skills, and plugins.
- point `XDG_DATA_HOME` at the existing OpenCode data root only when the
  operator explicitly accepts reuse of its persistent authentication store;
  never copy or print credential contents.
- inline config contains only the selected model and terminal-review permission
  policy needed to read declared artifacts and call the ephemeral MCP tool.

Managed machine policy may still apply and must be described as an operator
boundary. Reusing the data root exposes the credential store to the OpenCode
process even though the pinned model determines which credential is exercised;
provider-neutral grant enforcement remains a follow-up to upstream PR #39. If a
model depends on provider configuration removed by isolation, fail closed with
guidance to choose a built-in/config-independent provider or a different
terminal-review provider.

Temporary reviewer configuration directories are created with owner-only
permissions and removed after the subprocess exits.

## 7. Errors and observability

Define or reuse `ACPError` messages for:

- executable missing;
- invalid OpenCode configuration;
- model option not advertised/rejected;
- effort unavailable for selected model;
- build mode unavailable;
- session MCP registration failure;
- terminal-review isolation incompatible with selected provider;
- OpenCode process exit, timeout, or malformed JSON-RPC.

Handoffs should record provider, role, model, and effort as non-secret runtime
identity when that infrastructure is accepted upstream. Until then, include
them only in safe diagnostic summaries—not arbitrary environment or config
dumps.

## 8. Test specification

### 8.1 Unit tests

`tests/test_config.py`

- provider discovery for all four roles;
- same-provider model/effort inheritance;
- cross-provider pin isolation;
- unspecified OpenCode effort remains unspecified;
- invalid OpenCode model control characters rejected.

`tests/test_cli.py`

- every OpenCode CLI selector;
- exact local MCP JSON shape;
- unrelated JSON settings and MCP servers preserved;
- invalid/non-object JSON fails without mutation;
- idempotent second run;
- JSONC override conflict is diagnosed;
- no model/provider/key written without explicit flags;
- assets and next-step text use `.opencode` and `opencode`.

`tests/test_acp_runner.py`

- command remains `opencode acp` for normal work;
- selection order is model, effort, mode, prompt;
- absent pins emit no model/effort requests;
- session option errors are role-specific;
- model IDs are transported as JSON, never shell-expanded;
- terminal command/environment is isolated and cleaned up.

`tests/test_assets.py`

- four OpenCode subagents exist and parse;
- `mode: subagent`, `edit: deny`, and `task: deny` are present;
- bundled skills are discoverable from OpenCode paths.

### 8.2 Mock ACP changes

Enhance `tests/mock_acp_agent.py` to:

- advertise configurable `model`, `effort`, and `mode` options;
- record ordered requests;
- update effort choices after model selection;
- reject configured unsupported values;
- record `session/new` MCP servers.

### 8.3 Real smoke tests

Extend `test_smoke_real_acp.py` and `test_smoke_parallel_acp.py` with
`ZENITH_SMOKE_REAL_ACP=opencode`. Add command override
`ZENITH_SMOKE_OPENCODE_ACP_CMD`.

Required live cases:

1. one work/validate mission using OpenCode defaults;
2. explicit model plus supported effort;
3. different worker/validator model pins;
4. two parallel workers;
5. terminal reviewer isolation canary.

Tests remain opt-in because prompts incur provider usage. Capture OpenCode
version and selected provider/model in safe test output.

## 9. Documentation changes

Update root and package READMEs, CONTRIBUTING, package keywords, and real-smoke
test instructions. Document:

- OpenCode installation and `command -v opencode`;
- `zenith init --agent opencode`;
- host prompt/skill invocation;
- mixed-provider examples;
- `opencode models [provider]` for discovering IDs;
- model and effort precedence;
- credential/billing trust boundary;
- terminal-review limitations for custom providers;
- WSL recommendation.

## 10. Compatibility and rollout

- Keep all existing defaults unchanged (`claude` remains default).
- Project scope ships first.
- Mark OpenCode support experimental until serial, parallel, model-pin, and
  isolation smoke tests pass against the documented minimum version.
- After one release cycle, consider user-scoped setup and generalizing billing
  grants across credential-backed providers.

## 11. Research evidence

- Native ACP command and feature support:
  [docs](https://opencode.ai/docs/acp/),
  [v1.18.30 source](https://github.com/anomalyco/opencode/blob/v1.18.30/packages/opencode/src/acp/service.ts)
- Model IDs, precedence, and variants:
  [docs](https://opencode.ai/docs/models/)
- Config merge/precedence:
  [docs](https://opencode.ai/docs/config/),
  [paths source](https://github.com/anomalyco/opencode/blob/v1.18.30/packages/opencode/src/config/paths.ts)
- ACP model/effort/mode option encoding:
  [config-option source](https://github.com/anomalyco/opencode/blob/v1.18.30/packages/opencode/src/acp/config-option.ts)
- Agent inheritance/frontmatter:
  [docs](https://opencode.ai/docs/agents/)
- Permission defaults:
  [docs](https://opencode.ai/docs/permissions/)
- Credential storage and model enumeration:
  [CLI docs](https://opencode.ai/docs/cli/)
