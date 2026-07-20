# Evidence and Source Map

This research uses local, read-only trace sources. Public paths below use stable placeholders: `$ZENITH_HOME` is the local Zenith data root, `$CODEX_HOME` is the local Codex data root, `<historical-workspace>` is the preserved product workspace, and `<clean-research-checkout>` is the source checkout used for the audit.

## Historical run

- Project bucket: `$ZENITH_HOME/projects/20260717T130345Z-read-only-all-around-production-log-research-for-agent-builder-p`
- Runtime mission metadata: `<project>/.zenith-runtime/missions/mission-001`
- Durable mission charter, decisions and evidence inventory: `<project>/.zenith`
- Mission charter: `<project>/.zenith/missions/mission-001/mission.md`
- Root Codex conversation: `$CODEX_HOME/sessions/2026/07/<root-session>.jsonl`
- Worker and reviewer conversations: `$CODEX_HOME/sessions/2026/07/**/*.jsonl`, narrowed by project ID/task ID and dispatch timestamp by `analyze_trace.py`

The analyzer performs mission-evidence-payload-blind analysis over project/runtime JSON, attempt handoffs, terminal-review records, decision metadata, and Codex session/event data. It traverses the evidence tree only for filesystem sizes/inodes. It does not open production-log or mission-evidence payload content; it retains bounded Codex session text only for event-to-session correlation.

## Harness source

Clean research checkout:

- `<clean-research-checkout>`
- branch `research/zenith-run-efficiency-20260719`
- upstream source snapshot `feb1d62`

Primary inspected surfaces:

- `zenith/src/zenith_harness/bundled/prompts/orchestrator/system_prompt.md`
- `zenith/src/zenith_harness/bundled/prompts/terminal-reviewer/system_prompt.md`
- `zenith/src/zenith_harness/coordinator.py`
- `zenith/src/zenith_harness/task_validation.py`
- `zenith/src/zenith_harness/config.py`
- ACP/provider runner and persistence modules under `zenith/src/zenith_harness/`

The historical project does not record the executing harness commit. `feb1d62` is therefore a current-source audit target whose behavior matches the trace, not a proven identity for the July 17 process.

## Preserved checkout

`<historical-workspace>` was treated as read-only historical evidence and was not modified.

## Generated evidence

- `generated/execution_ledger.csv`: timestamped attempts, decisions, terminal reviews, deterministic session aliases, match diagnostics, active duration and reported token fields
- `generated/metrics.json`: summarized wall/active time, topology, outcomes, artifact sizes and method limitations
- `generated/idle_gaps.csv`: gaps between the union of matched active session intervals

The three generated files are deterministic for the frozen sources. Two fresh analyzer runs produced identical SHA-256 hashes:

```text
7882a386d40967bdd4275a0c1c2679eef7baa66c6d752c18864e40d996e36ecf  execution_ledger.csv
168e43a55d2d20042162491731e0b6e06607119bd8cf9b55f803ae78a21a7f1e  idle_gaps.csv
1a967622babb9ce59e2b98f5373bf8ebc061ece5351ddb62ceec5fd9fbbfc315  metrics.json
```
