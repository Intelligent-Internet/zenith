# Zenith: A Continuous-Improvement Harness for Long-Running Tasks

<img width="1500" height="600" alt="From RALPH to Zenith — Intelligent Internet technical report" src="https://github.com/user-attachments/assets/8c3c76e7-4a54-4c6e-95b7-25db573a0881" />

<p>
  <a href="https://github.com/Intelligent-Internet/zenith/actions/workflows/ci.yml"><img src="https://github.com/Intelligent-Internet/zenith/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue.svg" alt="License: Apache-2.0"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+">
  <a href="technical_report/Technical_Report.pdf"><img src="https://img.shields.io/badge/technical%20report-PDF-b31b1b.svg" alt="Technical Report"></a>
</p>

Zenith is an agent harness for work that may run for days or weeks, where the dominant failure mode is *premature completion* rather than inability to make progress. It runs a coding agent (Claude Code, Codex, Hermes, or experimental OpenCode support) as a multi-agent orchestrator over MCP/ACP: one orchestrator session reads task state each turn and decides whether to spawn workers and testers, register reusable skills, replan, or stop.

This repository contains the Zenith harness ([`zenith/`](zenith/)) and the Intelligent Internet technical report (2026) behind it.

> **[Read the report (PDF)](technical_report/Technical_Report.pdf)**

## Abstract

Long-running agents often fail not because they cannot make progress, but because they stop before the task is truly complete. We tested five harness designs across eight long-horizon tasks to isolate the control mechanisms that matter: repeated gap-finding, revisable planning, independent verification, adaptive orchestration, and stopping discipline.

RALPH is the strongest simple baseline because it forces each new session to reopen the gap between the current project state and the original requirement. But RALPH is expensive and has no principled stopping rule.

Our Zenith method keeps the useful parts of repeated review while making the loop adaptive: the orchestrator dynamically allocates workers, testers, reusable skills, replanning, and stopping decisions. In this study, Zenith achieved the best mean rank while using less than half of RALPH's per-task cost.

<img width="1445" height="1088" alt="Benchmark results: Zenith vs. RALPH variants across eight long-horizon tasks" src="https://github.com/user-attachments/assets/200a7337-38a9-4fa2-91e6-60cc6ce07f5b" />

## Quick Start

### Option 1 — Let your agent install it

Copy this prompt into Claude Code, Codex, or OpenCode:

```text
/goal Read the readme at https://github.com/Intelligent-Internet/zenith, detect if using Claude Code, Codex, OpenCode, or multiple supported agents, install requirements, install and run Zenith (i.e. uv run zenith, as in the readme), and create a new skill called /zenith — when used (along with an additional prompt) it will call the skill: the minimum skill content should be: """First read .claude/orchestrator_prompt.md and treat it as your primary role, then use Zenith to run this mission.""" Afterwards, you can add information about the Zenith harness, based on the readme and the technical report (inside the repo), and info on how to start Zenith if it's not already running. Change the skill to use .codex when using it in Codex and .opencode when using it in OpenCode. If multiple harnesses are available, make sure to add the skill to both of them correctly. In fact, there might be more harness options (Hermes, for example). See what is supported in zenith/src/zenith_harness/providers.py, and for those that you detect are present, add their skills correctly. When finished, confirm to me that Zenith is installed, running, and ready, explain a bit about Zenith, and why and when to use it.
```

This will:

- install Zenith with its requirements
- start Zenith using `uv`
- create a `/zenith` skill for each agent harness it detects

Then, in Claude Code, Codex, or OpenCode, type:

```text
/zenith <your instruction or query>
```

### Option 2 — Install manually

**Requirements**

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)
- Node.js 22+ and `npm`
- Claude Code, Codex, Hermes, or OpenCode (see [`providers.py`](zenith/src/zenith_harness/providers.py) for the supported set)

**Install**

```bash
cd zenith
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

OpenCode has a native ACP server, so no third-party ACP adapter is required.
Install OpenCode using the current OpenCode installation instructions for your
platform, then confirm the `opencode` binary is on `PATH`:

```bash
# Common OpenCode 1.x install path; see https://opencode.ai/docs/ for alternatives.
curl -fsSL https://opencode.ai/install | bash
command -v opencode
opencode --version
```

This PR-A OpenCode support was implemented against OpenCode `1.18.30` and uses
the `opencode acp` command, project `.opencode` configuration, OpenCode agents,
and OpenCode skills.

**Initialize a workspace**

Initialize the project workspace Zenith should operate on. This is your target app/repo, not the Zenith source checkout:

```bash
# Claude Code, from this Zenith checkout
uv run zenith init --workspace-dir /path/to/your-app --agent claude

# Or Codex, from this Zenith checkout
uv run zenith init --workspace-dir /path/to/your-app --agent codex

# Or OpenCode, from this Zenith checkout
uv run zenith init --workspace-dir /path/to/your-app --agent opencode
```

**Run a mission**

Start your agent from the initialized project workspace:

```bash
cd /path/to/your-app

claude
# or
codex
# or
opencode
```

Then ask the agent to read the generated orchestrator prompt (use `.codex/orchestrator_prompt.md` for Codex and `.opencode/orchestrator_prompt.md` for OpenCode):

```text
First read .claude/orchestrator_prompt.md and treat it as your primary role, then use Zenith to run this mission.

<your instruction or query>
```

### OpenCode project setup

`zenith init --agent opencode` performs project-scoped setup only. It writes or
updates `.opencode/opencode.json` with Zenith's managed `mcp.zenith` local MCP
entry, using OpenCode's `command`, `environment`, `enabled`, and millisecond
`timeout` fields. It also creates `.opencode/orchestrator_prompt.md`, installs
OpenCode subagents under `.opencode/agents/`, and installs bundled skills under
both `.opencode/skills/` and `.agents/skills/`.

Zenith preserves unrelated strict JSON OpenCode settings and unrelated MCP
servers. It does not rewrite JSONC; if `.opencode/opencode.jsonc` or a project
`opencode.jsonc` defines `mcp.zenith` in a way that would shadow Zenith's
managed entry, initialization fails with remediation instead of normalizing the
commented file.

OpenCode PR-A support is intentionally experimental. It registers OpenCode as a
host and execution provider, selects the native `opencode acp` command for
worker, validator, and terminal-reviewer roles, and selects OpenCode `build`
mode for normal ACP sessions. It does not yet claim verified live OpenCode
worker or validator execution, per-role OpenCode model/effort session options,
isolated OpenCode terminal review, user-scoped OpenCode setup, or
provider-neutral billing grants. Those are future PR B/C boundaries.

Zenith does not choose or persist an OpenCode default model, provider credential,
permission policy, plugin configuration, global OpenCode config, or provider API
key. Normal OpenCode worker and validator sessions run with the credentials
available to the `opencode` process, so provider access and billing remain under
the operator's OpenCode trust boundary. PR-A checks are hermetic by default and
use disposable local OpenCode configuration checks such as `opencode debug
config`; any live-provider smoke that can spend tokens must stay explicit and
opt-in.

For audience-specific OpenCode guidance, see the
[user](docs/opencode-support/user.md),
[admin](docs/opencode-support/admin.md), and
[developer](docs/opencode-support/developer.md) guides.

## How Zenith Works

<p align="center">
  <img src="technical_report/images/zenith.png" alt="Zenith harness architecture" width="780"/>
</p>

A single orchestrator session reads task state each turn and decides what to do next: spawn worker or tester subagents, register a reusable skill, replan, or stop. Workers and testers run in their own contexts and report back; the orchestrator integrates their results before the next decision.

## Results

### Frontier SWE Benchmark

On the [Frontier SWE benchmark](https://www.frontierswe.com), Zenith — running on GPT-5.5 — ranks first overall, leading on implementation, performance, and dominance against frontier models paired with their native harnesses.

| # | Model | Harness | Avg rank ↓ | Dominance ↑ | Implementation ↓ | Performance ↓ | Research ↓ |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | GPT-5.5 | **Zenith** | **2.06** | **92%** | **1.60** | **1.89** | 3.33 |
| 2 | Claude Fable | Claude Code | 2.71 | 88% | 1.80 | 2.11 | 6.00 |
| 3 | Claude Opus 4.8 | Claude Code | 5.06 | 71% | 4.20 | 5.56 | 5.00 |
| 4 | GLM-5.2 | Claude Code | 5.31 | 69% | 5.60 | 6.50 | 1.67 |
| 5 | GPT-5.5 | Codex | 5.53 | 68% | 7.40 | 4.44 | 5.67 |
| 6 | Claude Opus 4.7 | Claude Code | 6.35 | 59% | 5.00 | 7.00 | 6.67 |
| 7 | Claude Opus 4.6 | Claude Code | 7.53 | 52% | 7.60 | 7.56 | 7.33 |
| 8 | GPT-5.4 | Codex | 8.06 | 50% | 7.20 | 9.67 | 4.67 |
| 9 | Composer 2.5 | Cursor CLI | 9.35 | 38% | 7.80 | 11.11 | 6.67 |
| 10 | Gemini 3.1 Pro | Gemini CLI | 9.65 | 37% | 11.80 | 7.44 | 12.67 |
| 11 | GLM-5.1 | Claude Code | 10.88 | 29% | 10.80 | 11.00 | 10.67 |
| 12 | DeepSeek V4 Pro | Claude Code | 11.00 | 27% | 10.80 | 11.11 | 11.00 |
| 13 | Kimi K2.5 | Kimi CLI | 11.65 | 24% | 13.00 | 10.22 | 13.67 |
| 14 | Kimi K2.6 | Kimi CLI | 11.82 | 25% | 10.40 | 12.78 | 11.33 |
| 15 | Qwen3.6-Plus | Qwen Code | 12.47 | 21% | 15.00 | 10.67 | 13.67 |

<sub>*Metrics as reported by the [Frontier SWE leaderboard](https://www.frontierswe.com). Rank columns: lower is better. Dominance: higher is better.*</sub>

### Ablation Study

To isolate the control mechanisms that matter, we compared Zenith against RALPH and three reduced harness variants across eight long-horizon tasks. Zenith achieves the best mean rank at less than half of RALPH's per-task cost.

| Method | Mean rank ↓ | Mean cost (USD/task) ↓ | Wins (of 8) ↑ |
| --- | ---: | ---: | ---: |
| One-session | 5.00 | $22.21 | 0 |
| Plan-RALPH | 4.00 | $161.53 | 0 |
| Milestone-RALPH | 2.88 | $209.47 | 0 |
| RALPH | 1.75 | $407.58 | 3 |
| **Zenith** | **1.38** | **$175.68** | **5** |

<sub>*A "win" is a task on which the method ranked first; the eight wins partition the eight benchmark tasks.*</sub>

## Repository Layout

| Path | Contents |
| --- | --- |
| [`zenith/`](zenith/) | The Zenith harness — Python package (`zenith-harness`), CLI, MCP server, bundled prompts and skills, tests |
| [`technical_report/`](technical_report/) | *From RALPH to Zenith* technical report — PDF, LaTeX source, and figures |

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for the development setup and PR guidelines, and [SECURITY.md](SECURITY.md) for how to report vulnerabilities.

## Citation

```bibtex
@techreport{ii2026zenith,
  title       = {From RALPH to Zenith: Designing Harnesses for Long-Running Agents},
  author      = {{Intelligent Internet}},
  institution = {Intelligent Internet},
  year        = {2026},
  type        = {Technical Report},
  url         = {https://github.com/Intelligent-Internet/zenith}
}
```

## License

The Zenith code is licensed under the [Apache License 2.0](LICENSE). The technical report and its figures are licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
