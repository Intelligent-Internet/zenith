# From RALPH to Zenith

**Designing harnesses for long-running agents**

Technical report from Intelligent Internet (2026) on how an agent harness should control work that may run for days or weeks, where the dominant failure mode is *premature completion* rather than inability to make progress.

> **[Read the report (PDF)](technical_report/Technical_Report.pdf)**

## Abstract

Long-running agents often fail not because they cannot make progress, but because they stop before the task is truly complete. We tested five harness designs across eight long-horizon tasks to isolate the control mechanisms that matter: repeated gap-finding, revisable planning, independent verification, adaptive orchestration, and stopping discipline.

RALPH is the strongest simple baseline because it forces each new session to reopen the gap between the current project state and the original requirement. But RALPH is expensive and has no principled stopping rule.

Our Zenith method keeps the useful parts of repeated review while making the loop adaptive: the orchestrator dynamically allocates workers, testers, reusable skills, replanning, and stopping decisions. In this study, Zenith achieved the best mean rank while using less than half of RALPH's per-task cost.

## Zenith

<p align="center">
  <img src="technical_report/images/zenith.png" alt="Zenith harness architecture" width="780"/>
</p>

A single orchestrator session reads task state each turn and decides what to do next: spawn worker or tester subagents, register a reusable skill, replan, or stop. Workers and testers run in their own contexts and report back; the orchestrator integrates their results before the next decision.

## Results

<p align="center">
  <img src="technical_report/images/result.png" alt="Mean rank vs mean cost across harnesses" width="780"/>
</p>

| Method | Mean rank ↓ | Mean cost (USD/task) ↓ | Wins (of 8) ↑ |
| --- | ---: | ---: | ---: |
| One-session | 5.00 | $22.21 | 0 |
| Plan-RALPH | 4.00 | $161.53 | 0 |
| Milestone-RALPH | 2.88 | $209.47 | 0 |
| RALPH | 1.75 | $407.58 | 3 |
| **Zenith** | **1.38** | **$175.68** | **5** |

<sub>*A "win" is a task on which the method ranked first; the eight wins partition the eight benchmark tasks.*</sub>

## Example

[`example/angry-bird/`](example/angry-bird/) is an Angry Birds–style physics puzzle game **built end-to-end by Zenith** as one of the eight benchmarked tasks. See its [README](example/angry-bird/README.md) for setup and the strategy runner used to verify level clearability.

```bash
cd example/angry-bird
npm install && npm run dev
# → opens at http://localhost:4100
```

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
