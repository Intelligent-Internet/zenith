# Branch-Ready Zenith Improvement Backlog

This backlog maps the research recommendations to current source surfaces. It is intentionally implementation-ready without pre-committing to an API that tests may disprove.

## P0 — truthful closure

### Declared terminal-review deliverables

Current surfaces:

- `zenith/src/zenith_harness/bundled/prompts/terminal-reviewer/system_prompt.md`
- terminal-review launcher/provider code
- mission/project persistence schemas
- terminal-review tests

Proposal:

- persist an explicit list of canonical read-only `deliverable_roots` in the mission charter/runtime;
- pass only those roots plus the original workspace to terminal review;
- continue forbidding decisions, attempts, validator reports and closeout history;
- require each root to be inside an allowed workspace/project boundary and resolve symlinks before spawn;
- record the resolved root list in the terminal-review record.

Tests:

1. report only under mission evidence can pass;
2. missing report fails;
3. tampered report fails a real behavior/provenance probe;
4. a deliverable root that traverses to forbidden history is rejected;
5. earlier validator prose remains inaccessible.

### Terminal-gap fingerprint

Current surfaces:

- `zenith/src/zenith_harness/coordinator.py::_enter_terminal_review`
- terminal-review persistence and attention schemas

Proposal:

- hash normalized gap IDs/text, original request hash, workspace/deliverable roots and relevant content manifests;
- when the same fingerprint recurs without input change, raise `terminal_review_configuration_conflict`;
- disallow an unchanged retry until the orchestrator patches visibility, artifacts or scope.

The detector must not collapse genuinely new evidence or changed gaps.

## P0 — native execution telemetry

Persist per attempt:

- runtime/harness commit and dirty-state marker;
- provider and model;
- provider session/thread ID;
- queued, dispatched, started and completed timestamps;
- terminal reason and retry/patch parent;
- input, cached-input, output and reasoning tokens where available;
- artifact logical/allocated byte delta and file count;
- contract/task graph version.

Emit a native ledger equivalent to `generated/execution_ledger.csv`. Schema fields must be optional for providers that do not expose usage; unknown is better than inferred zero.

## P0 — research mission policy and budgets

Current surface: bundled orchestrator prompt and mission playbooks.

Proposal:

- select a research policy when the outcome is knowledge/artifacts rather than durable product behavior;
- begin with source feasibility and targetless discovery tasks;
- promote stable report claims into acceptance contracts after feasibility;
- record separate outcome, correctness oracle, and scoring reference;
- add soft budgets for wall time, attempts, task/contract growth, report-family versions and artifact bytes;
- budget crossing raises a value-of-information attention item containing critical path, sunk cost and alternatives.

Do not implement budgets as silent hard caps. That would trade visible slowness for invisible incompleteness.

## P1 — current evidence epochs

Current surfaces:

- `zenith/src/zenith_harness/coordinator.py::_evaluate_gate`
- `zenith/src/zenith_harness/coordinator.py::_upstream_validators`
- task supersession and contract-state persistence

Proposal:

- assign an immutable evidence epoch to each assertion ownership/method/input tuple;
- gates enumerate validators explicitly for the active epoch instead of walking arbitrary transitive history;
- supersession closes an epoch and preserves its verdicts as history;
- a new epoch cannot reuse a verdict unless contract text, validation method and relevant inputs hash-identically match.

Property-test DAGs containing chained supersession, shared prerequisites, partial target overlap, stale dissent, omitted verdicts and rollback. The principal failure risk is a false pass caused by losing a relevant historical prerequisite.

## P1 — incremental validation cache

Cache key:

`contract_hash + validator_method_hash + environment_identity + ordered_input_manifest_hash`

Cache entries contain per-assertion verdicts and raw evidence pointers. Any changed contract, method, environment requirement or relevant input invalidates the entry. Mutation tests must cover report text, cited table, raw source manifest, code, configuration and validation procedure.

Start in observe-only mode: compute “would reuse” decisions while still running validators, then compare verdicts before enabling reuse.

## P1 — sealed packet preflight

Before dispatch, statically verify:

- allowlisted files exist and hashes match;
- packet is self-contained under the declared startup rule;
- forbidden paths cannot be reached through symlinks or parent discovery;
- output root is writable and outside the sealed inputs;
- coder identity/assignment is not embedded in a blinded packet;
- independent assignments do not share generated labels or another coder's output.

Each July-run packet/startup failure should become a fixture. This is a compiler problem disguised as an agent retry.

## P1 — first-class non-estimability

Add a contract disposition distinct from pass/fail/accepted-risk:

- `not_estimable` requires an oracle explaining which identification prerequisite failed;
- it may retain descriptive artifacts;
- it forbids downstream numeric/causal claims that require the failed prerequisite;
- it satisfies closure only when the original request permits explicit limitations.

Validators must test the absence of prohibited estimates, not merely the presence of limitation prose.

## P1 — immutable evidence storage

Separate source corpora from mission/report packages:

- content-address raw and compact source objects;
- use immutable manifests for task inputs;
- materialize with reflinks/hardlinks only where safe;
- version derived outputs as deltas;
- garbage-collect only objects unreachable from sealed manifests, never during an active mission.

Replay the report v2–v9 lineage and require identical content hashes and validator results while measuring logical bytes, allocated bytes, file operations and session read tokens.

## P1/P2 — scoped attention and scheduling

Current surface: `coordinator.py::_apply_gate_event` and scheduler readiness logic.

Proposal:

- auto-continue a cleared gate unless it is marked as a semantic checkpoint;
- attach failed attention to its affected task subgraph;
- continue dispatching independent ready nodes when no shared resource or global scope decision is involved;
- after telemetry is available, prioritize nodes by estimated remaining critical-path length and failure probability.

Validate with deterministic simulations before live use. Compare makespan, maximum concurrency, number of orchestration turns, and—most importantly—whether any worker ran on invalidated global assumptions.

## Suggested pull-request slicing

1. Runtime version + attempt telemetry schema and ledger.
2. Terminal deliverable roots + security tests.
3. Terminal-gap fingerprint.
4. Research policy + shadow budgets.
5. Packet preflight linter.
6. Evidence epochs behind a feature flag.
7. Observe-only validation reuse.
8. Content-addressed evidence prototype.
9. Scoped attention and critical-path scheduler experiment.

Each slice should be independently reversible. Do not combine closure visibility and validator-cache semantics in one change: their risk profiles and oracles are different.
