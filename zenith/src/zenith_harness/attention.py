from __future__ import annotations

import secrets

from .models import (
    AttentionItemInternal,
    Task,
    TerminalReviewHandoff,
    ValidateHandoff,
    WorkHandoff,
)


def _new_id(prefix: str) -> str:
    return f"att-{prefix}-{secrets.token_hex(3)}"


def _handoff_report(task: Task, handoff: WorkHandoff | ValidateHandoff) -> str:
    lines = [
        f"Task report from {task.id}",
        f"type: {task.type}",
        f"done: {handoff.done}",
        f"request_attention: {handoff.request_attention}",
        "",
        "report:",
        handoff.report or "(empty)",
    ]
    if isinstance(handoff, ValidateHandoff):
        lines.extend(
            [
                "",
                f"passed: {handoff.passed}",
                "items:",
            ]
        )
        if handoff.items:
            lines.extend(
                f"- {item.item_id}: {'passed' if item.passed else 'failed'}"
                for item in handoff.items
            )
        else:
            lines.append("- (none)")
    return "\n".join(lines)


def node_failed(
    mission_id: str,
    task: Task,
    handoff: WorkHandoff,
) -> AttentionItemInternal:
    return AttentionItemInternal(
        id=_new_id(task.id),
        kind="node_failed",
        mission_id=mission_id,
        node_id=task.id,
        report=_handoff_report(task, handoff),
    )


def node_attention(
    mission_id: str,
    task: Task,
    handoff: WorkHandoff | ValidateHandoff,
) -> AttentionItemInternal:
    return AttentionItemInternal(
        id=_new_id(task.id),
        kind="node_attention",
        mission_id=mission_id,
        node_id=task.id,
        report=_handoff_report(task, handoff),
    )


def _validator_summary_lines(
    targets: list[str],
    validator_verdicts: dict[str, dict[str, bool]],
    missing_items: dict[str, list[str]] | None = None,
) -> list[str]:
    """Human-readable per-validator summary for the gate report."""
    summary: list[str] = []
    target_set = set(targets)
    missing_items = missing_items or {}
    for vid in sorted(validator_verdicts):
        verdicts = validator_verdicts[vid]
        covered = [t for t in targets if t in verdicts]
        if not covered:
            summary.append(f"- {vid}: 0/{len(target_set)} covered")
            continue
        passed = sum(1 for t in covered if verdicts[t])
        miss_set = set(missing_items.get(vid, []))
        flags: list[str] = []
        dissenting = [t for t in covered if not verdicts[t] and t not in miss_set]
        missing = [t for t in covered if t in miss_set]
        if dissenting:
            flags.append(f"dissenting: {', '.join(dissenting)}")
        if missing:
            flags.append(f"missing: {', '.join(missing)}")
        flag_text = f" ({'; '.join(flags)})" if flags else ""
        summary.append(
            f"- {vid}: {passed}/{len(covered)} passed over {len(target_set)} target(s){flag_text}"
        )
    return summary


def _gate_report(
    gate: Task,
    *,
    cleared: bool,
    reason: str = "",
    failed_items: list[str] | None = None,
    validator_verdicts: dict[str, dict[str, bool]] | None = None,
    missing_items: dict[str, list[str]] | None = None,
) -> str:
    failed_items = failed_items or []
    validator_verdicts = validator_verdicts or {}
    missing_items = missing_items or {}
    lines = [
        f"Gate report from {gate.id}",
        f"cleared: {cleared}",
        f"targets: {', '.join(gate.targets) if gate.targets else '(none)'}",
    ]
    if reason:
        lines.append(f"reason: {reason}")
    if failed_items:
        lines.append(f"failed_items: {', '.join(failed_items)}")
    lines.extend(["", "validator summary:"])
    summary = _validator_summary_lines(gate.targets, validator_verdicts, missing_items)
    lines.extend(summary or ["- (no validator verdicts)"])
    return "\n".join(lines)


def gate_failed(
    mission_id: str,
    gate: Task,
    reason: str,
    *,
    failed_items: list[str] | None = None,
    validator_verdicts: dict[str, dict[str, bool]] | None = None,
    missing_items: dict[str, list[str]] | None = None,
) -> AttentionItemInternal:
    failed_items = failed_items or []
    validator_verdicts = validator_verdicts or {}
    missing_items = missing_items or {}
    return AttentionItemInternal(
        id=_new_id(gate.id),
        kind="gate_failed",
        mission_id=mission_id,
        node_id=gate.id,
        report=_gate_report(
            gate,
            cleared=False,
            reason=reason,
            failed_items=failed_items,
            validator_verdicts=validator_verdicts,
            missing_items=missing_items,
        ),
    )


def gate_checkpoint(
    mission_id: str,
    gate: Task,
    *,
    validator_verdicts: dict[str, dict[str, bool]] | None = None,
) -> AttentionItemInternal:
    validator_verdicts = validator_verdicts or {}
    return AttentionItemInternal(
        id=_new_id(gate.id),
        kind="gate_checkpoint",
        mission_id=mission_id,
        node_id=gate.id,
        report=_gate_report(
            gate,
            cleared=True,
            validator_verdicts=validator_verdicts,
        ),
    )


def terminal_review(
    mission_id: str,
    review: TerminalReviewHandoff,
) -> AttentionItemInternal:
    return AttentionItemInternal(
        id=_new_id("terminal-review"),
        kind="terminal_review",
        mission_id=mission_id,
        report=review.report or "(empty)",
    )


__all__ = [
    "node_failed",
    "node_attention",
    "gate_failed",
    "gate_checkpoint",
    "terminal_review",
]
