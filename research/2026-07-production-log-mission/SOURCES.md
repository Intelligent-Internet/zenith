# Evidence and Source Map

This research uses local, read-only trace sources. It does not copy production-log payloads into the Zenith repository.

## Historical run

- Project bucket: `/Users/aleksandrpodgaiko/.zenith/projects/20260717T130345Z-read-only-all-around-production-log-research-for-agent-builder-p`
- Runtime mission metadata: `<project>/.zenith-runtime/missions/mission-001`
- Durable mission charter, decisions and evidence inventory: `<project>/.zenith`
- Mission charter: `<project>/.zenith/missions/mission-001/mission.md`
- Root Codex conversation: `/Users/aleksandrpodgaiko/.codex/sessions/2026/07/17/rollout-2026-07-17T17-00-57-019f702a-72c3-77d3-810e-a08d8f323219.jsonl`
- Worker and reviewer conversations: `/Users/aleksandrpodgaiko/.codex/sessions/2026/07/**/*.jsonl`, narrowed by project ID/task ID and dispatch timestamp by `analyze_trace.py`

The analyzer reads project/runtime JSON, attempt handoffs, terminal-review records, decision metadata and Codex session event metadata. It traverses the evidence tree only for filesystem sizes/inodes. It does not open production-log or mission-evidence payload content.

## Harness source

Clean research checkout:

- `/Users/aleksandrpodgaiko/zenith`
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

`/Users/aleksandrpodgaiko/Desktop/agents/cx/zenith` was treated as read-only historical evidence and was not modified.

## Generated evidence

- `generated/execution_ledger.csv`: timestamped attempts, decisions, terminal reviews, session IDs, active duration and reported token fields
- `generated/metrics.json`: summarized wall/active time, topology, outcomes, artifact sizes and method limitations
- `generated/idle_gaps.csv`: gaps between the union of matched active session intervals

The three generated files are deterministic for the frozen sources. A repeated analyzer run produced identical SHA-1 hashes:

```text
b4776ca30df554c5cce94f005d869e84192ea95e  execution_ledger.csv
17477151a702ec96edb34efe23a103465b03a93f  idle_gaps.csv
49a610ee199658675e62fd7f4f9a6767cd9fae10  metrics.json
```
