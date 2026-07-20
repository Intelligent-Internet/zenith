#!/usr/bin/env python3
"""Build a reproducible, mission-evidence-payload-blind Zenith trace profile.

The script reads Zenith runtime records and Codex JSONL session/event data. It
does not open production-log or mission-evidence payload content; it retains
bounded Codex session text only for event-to-session correlation.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


UTC = timezone.utc
ATTEMPT_RE = re.compile(
    r"^(?P<stamp>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z)-\d{4}__(?P<task>.+)\.json$"
)
DECISION_TS_RE = re.compile(r"^- Timestamp: (?P<stamp>[^\s]+)$", re.MULTILINE)
JSON_BLOCK_RE = re.compile(r"```json\n(?P<body>.*?)\n```", re.DOTALL)
HISTORICAL_WORKSPACE = "<historical-workspace>"


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def parse_filesafe(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H-%M-%SZ").replace(tzinfo=UTC)


def iso(value: datetime | None) -> str:
    return value.isoformat().replace("+00:00", "Z") if value else ""


def seconds(start: datetime | None, end: datetime | None) -> float:
    if not start or not end:
        return 0.0
    return max(0.0, (end - start).total_seconds())


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def tree_stats(path: Path) -> dict[str, int]:
    count = 0
    logical_size = 0
    allocated_size = 0
    inodes: set[tuple[int, int]] = set()
    for item in path.rglob("*"):
        if item.is_file():
            stat = item.stat()
            count += 1
            logical_size += stat.st_size
            allocated_size += getattr(stat, "st_blocks", 0) * 512
            inodes.add((stat.st_dev, stat.st_ino))
    return {
        "files": count,
        "logical_bytes": logical_size,
        "allocated_bytes": allocated_size,
        "unique_inodes": len(inodes),
        "hardlink_aliases": count - len(inodes),
    }


def classify_task(task_id: str, task_type: str) -> str:
    if task_type == "validate":
        return "validation"
    if task_type == "gate":
        return "gate"
    lowered = task_id.lower()
    if any(token in lowered for token in ("semantic", "coder", "manual", "adjudicat", "recode", "holdout", "blind")):
        return "manual_semantic_reliability"
    if "analysis-failclosed" in lowered or "analysis-fail-closed" in lowered:
        return "fail_closed_analysis_repair"
    if any(token in lowered for token in ("report", "history", "lineage", "bind-", "link", "provenance-r")):
        return "report_provenance_repair"
    if any(token in lowered for token in ("source", "strata", "sampling", "retrieve", "corpus", "supplement-timing")):
        return "population_and_retrieval"
    if any(token in lowered for token in ("tools", "token", "reqresp", "jq", "rare", "compare", "ops")):
        return "analysis"
    return "other_work"


def terminal_review_start(path: Path) -> datetime:
    return parse_filesafe(path.stem)


@dataclass
class Session:
    path: Path
    session_id: str
    start: datetime
    end: datetime
    active_intervals: list[tuple[datetime, datetime]]
    thread_source: str
    source: str
    final_usage: dict[str, int]
    text: str

    @property
    def active_seconds(self) -> float:
        return sum(seconds(start, end) for start, end in self.active_intervals)


@dataclass(frozen=True)
class MatchResult:
    session: Session | None
    method: str
    delta_seconds: float | None
    eligible_candidate_count: int
    ambiguity_status: str

    @property
    def ambiguous(self) -> bool:
        return self.method == "ambiguous"


def load_session(path: Path) -> Session | None:
    meta: dict[str, Any] | None = None
    first: datetime | None = None
    last: datetime | None = None
    turn_start: datetime | None = None
    intervals: list[tuple[datetime, datetime]] = []
    final_usage: dict[str, int] = {}
    text_parts: list[str] = []

    with path.open(errors="replace") as handle:
        for raw in handle:
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            stamp_raw = row.get("timestamp")
            stamp = parse_iso(stamp_raw) if isinstance(stamp_raw, str) else None
            if stamp:
                first = first or stamp
                last = stamp
            if row.get("type") == "session_meta":
                meta = row.get("payload", {})
            payload = row.get("payload", {})
            if row.get("type") == "event_msg" and payload.get("type") == "task_started" and stamp:
                if turn_start is not None:
                    intervals.append((turn_start, stamp))
                turn_start = stamp
            elif row.get("type") == "event_msg" and payload.get("type") == "task_complete" and stamp:
                if turn_start is not None:
                    intervals.append((turn_start, stamp))
                    turn_start = None
            if row.get("type") == "event_msg" and payload.get("type") == "token_count":
                info = payload.get("info") or {}
                usage = info.get("total_token_usage", {})
                if isinstance(usage, dict):
                    final_usage = {key: int(value) for key, value in usage.items() if isinstance(value, int)}
            if len(text_parts) < 2000:
                text_parts.append(raw[:20_000])

    if meta is None or first is None or last is None:
        return None
    if turn_start is not None:
        intervals.append((turn_start, last))
    if not intervals:
        intervals = [(first, last)]
    source_value = meta.get("source")
    source_text = json.dumps(source_value, sort_keys=True) if isinstance(source_value, dict) else str(source_value or "")
    return Session(
        path=path,
        session_id=str(meta.get("id") or meta.get("session_id") or ""),
        start=parse_iso(str(meta.get("timestamp"))) if meta.get("timestamp") else first,
        end=last,
        active_intervals=intervals,
        thread_source=str(meta.get("thread_source") or ""),
        source=source_text,
        final_usage=final_usage,
        text="".join(text_parts),
    )


def relevant_sessions(
    sessions_root: Path,
    project_id: str,
    start: datetime,
    end: datetime,
) -> list[Session]:
    sessions: list[Session] = []
    for path in sessions_root.rglob("*.jsonl"):
        loaded = load_session(path)
        if loaded is None or loaded.start < start or loaded.start > end:
            continue
        if project_id not in loaded.text and "Zenith Terminal Reviewer" not in loaded.text:
            continue
        sessions.append(loaded)
    return sorted(sessions, key=lambda item: (item.start, item.session_id))


def build_session_aliases(sessions: Iterable[Session]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for session in sorted(sessions, key=lambda item: (item.start, item.end, item.session_id)):
        if session.session_id and session.session_id not in aliases:
            aliases[session.session_id] = f"session-{len(aliases) + 1:03d}"
    return aliases


def match_session(
    event_start: datetime,
    event_id: str,
    sessions: list[Session],
    used: set[str],
    *,
    tolerance_seconds: int = 90,
) -> MatchResult:
    task_candidates = [
        session
        for session in sessions
        if session.session_id not in used
        and event_id in session.text
        and abs((session.start - event_start).total_seconds()) <= tolerance_seconds
    ]
    if task_candidates:
        deltas = {
            session.session_id: abs((session.start - event_start).total_seconds())
            for session in task_candidates
        }
        minimum_delta = min(deltas.values())
        best = [session for session in task_candidates if deltas[session.session_id] == minimum_delta]
        if len(best) != 1:
            return MatchResult(
                session=None,
                method="ambiguous",
                delta_seconds=minimum_delta,
                eligible_candidate_count=len(task_candidates),
                ambiguity_status="task_id_and_time_tie",
            )
        selected = best[0]
        used.add(selected.session_id)
        return MatchResult(
            session=selected,
            method="task_id_and_time",
            delta_seconds=minimum_delta,
            eligible_candidate_count=len(task_candidates),
            ambiguity_status="not_ambiguous",
        )

    time_candidates = [
        session
        for session in sessions
        if session.session_id not in used
        and abs((session.start - event_start).total_seconds()) <= 15
    ]
    if len(time_candidates) == 1:
        selected = time_candidates[0]
        delta = abs((selected.start - event_start).total_seconds())
        used.add(selected.session_id)
        return MatchResult(
            session=selected,
            method="time_only_unique",
            delta_seconds=delta,
            eligible_candidate_count=1,
            ambiguity_status="not_ambiguous",
        )
    if time_candidates:
        minimum_delta = min(
            abs((session.start - event_start).total_seconds()) for session in time_candidates
        )
        return MatchResult(
            session=None,
            method="ambiguous",
            delta_seconds=minimum_delta,
            eligible_candidate_count=len(time_candidates),
            ambiguity_status="multiple_time_only_candidates",
        )
    return MatchResult(
        session=None,
        method="unmatched",
        delta_seconds=None,
        eligible_candidate_count=0,
        ambiguity_status="not_ambiguous",
    )


def interval_union_seconds(intervals: Iterable[tuple[datetime, datetime]]) -> float:
    ordered = sorted((start, end) for start, end in intervals if end >= start)
    if not ordered:
        return 0.0
    total = 0.0
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
        else:
            total += seconds(current_start, current_end)
            current_start, current_end = start, end
    return total + seconds(current_start, current_end)


def merged_intervals(intervals: Iterable[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    ordered = sorted((start, end) for start, end in intervals if end >= start)
    if not ordered:
        return []
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        prior_start, prior_end = merged[-1]
        if start <= prior_end:
            merged[-1] = (prior_start, max(prior_end, end))
        else:
            merged.append((start, end))
    return merged


def parse_decisions(decision_dir: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    growth = Counter()
    for path in sorted(decision_dir.glob("*.md")):
        text = path.read_text()
        match = DECISION_TS_RE.search(text)
        if not match:
            continue
        action = path.stem.split("-", 1)[1]
        patch_tasks = patch_items = superseded = cancelled = 0
        for block in JSON_BLOCK_RE.finditer(text):
            try:
                payload = json.loads(block.group("body"))
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict) or not any(key in payload for key in ("add", "add_items", "supersede", "cancel")):
                continue
            patch_tasks += len(payload.get("add", []))
            patch_items += len(payload.get("add_items", []))
            superseded += len(payload.get("supersede", {}))
            cancelled += len(payload.get("cancel", []))
        growth.update({"added_tasks": patch_tasks, "added_contracts": patch_items, "superseded_tasks": superseded, "cancelled_tasks": cancelled})
        rows.append(
            {
                "event_kind": "decision",
                "event_id": path.stem,
                "event_type": action,
                "stage": "orchestration",
                "start_utc": match.group("stamp"),
                "end_utc": match.group("stamp"),
                "duration_seconds": 0,
                "session_id": "",
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_output_tokens": 0,
                "total_tokens": 0,
                "match_method": "",
                "match_delta_seconds": "",
                "match_candidate_count": "",
                "match_ambiguity": "",
                "done": "",
                "passed": "",
                "request_attention": "",
                "final_status": "",
                "note": f"add_tasks={patch_tasks}; add_contracts={patch_items}; supersede={superseded}; cancel={cancelled}",
            }
        )
    return rows, dict(growth)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "event_kind", "event_id", "event_type", "stage", "start_utc", "end_utc",
        "duration_seconds", "session_id", "input_tokens", "cached_input_tokens",
        "output_tokens", "reasoning_output_tokens", "total_tokens", "match_method",
        "match_delta_seconds", "match_candidate_count", "match_ambiguity", "done",
        "passed", "request_attention", "final_status", "note",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: (row["start_utc"], row["event_kind"], row["event_id"])))


def write_idle_gaps(
    path: Path,
    intervals: list[tuple[datetime, datetime]],
    project_start: datetime,
    project_end: datetime,
) -> list[dict[str, Any]]:
    busy = merged_intervals(intervals)
    gaps: list[dict[str, Any]] = []
    cursor = project_start
    for start, end in busy:
        if start > cursor:
            gaps.append({"start_utc": iso(cursor), "end_utc": iso(start), "duration_seconds": round(seconds(cursor, start), 3)})
        cursor = max(cursor, end)
    if project_end > cursor:
        gaps.append({"start_utc": iso(cursor), "end_utc": iso(project_end), "duration_seconds": round(seconds(cursor, project_end), 3)})
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["start_utc", "end_utc", "duration_seconds"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(sorted(gaps, key=lambda row: row["duration_seconds"], reverse=True))
    return gaps


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--sessions-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    project_root = args.project_root.resolve()
    runtime = project_root / ".zenith-runtime" / "missions" / "mission-001"
    durable = project_root / ".zenith" / "missions" / "mission-001"
    project = read_json(project_root / ".zenith-runtime" / "project.json")
    state = read_json(project_root / ".zenith-runtime" / "state.json")
    tasks_doc = read_json(runtime / "tasks.json")
    task_state = read_json(runtime / "task-state.json").get("tasks", {})
    contract_state = read_json(runtime / "contract-state.json").get("items", {})
    tasks = {task["id"]: task for task in tasks_doc["tasks"]}

    attempt_paths = sorted((runtime / "attempts").glob("*.json"))
    review_paths = sorted((runtime / "terminal-reviews").glob("*.json"))
    project_start = parse_iso(project["created_at"])
    last_review_start = max((terminal_review_start(path) for path in review_paths), default=project_start)
    session_end_bound = datetime.fromtimestamp(last_review_start.timestamp() + 3600, tz=UTC)
    sessions = relevant_sessions(args.sessions_root.resolve(), project["id"], project_start, session_end_bound)
    session_aliases = build_session_aliases(sessions)
    used_sessions: set[str] = set()
    matched_raw_session_ids: set[str] = set()
    match_results: list[MatchResult] = []
    rows: list[dict[str, Any]] = []
    active_intervals: list[tuple[datetime, datetime]] = []
    stage_seconds = Counter()
    stage_tokens = Counter()
    outcome_counts = Counter()
    unmatched_attempts: list[str] = []

    first_attempt_start: datetime | None = None
    for path in attempt_paths:
        match = ATTEMPT_RE.match(path.name)
        if not match:
            continue
        start = parse_filesafe(match.group("stamp"))
        first_attempt_start = min(first_attempt_start, start) if first_attempt_start else start
        task_id = match.group("task")
        task = tasks.get(task_id, {"type": "unknown"})
        payload = read_json(path)
        match_result = match_session(start, task_id, sessions, used_sessions)
        match_results.append(match_result)
        session = match_result.session
        if match_result.method == "unmatched":
            unmatched_attempts.append(path.name)
        if session:
            matched_raw_session_ids.add(session.session_id)
        event_end = session.end if session else start
        active = session.active_seconds if session else 0.0
        if session:
            active_intervals.extend(session.active_intervals)
        stage = classify_task(task_id, task.get("type", "unknown"))
        stage_seconds[stage] += active
        usage = session.final_usage if session else {}
        stage_tokens[stage] += usage.get("total_tokens", 0)
        done = payload.get("done")
        passed = payload.get("passed")
        attention = payload.get("request_attention")
        outcome_counts[f"done_{str(done).lower()}"] += 1
        if task.get("type") == "validate":
            outcome_counts[f"validator_passed_{str(passed).lower()}"] += 1
        if attention:
            outcome_counts["requested_attention"] += 1
        rows.append(
            {
                "event_kind": "attempt", "event_id": task_id, "event_type": task.get("type", "unknown"),
                "stage": stage, "start_utc": iso(start), "end_utc": iso(event_end),
                "duration_seconds": round(active, 3), "session_id": session.session_id if session else "",
                "input_tokens": usage.get("input_tokens", 0), "cached_input_tokens": usage.get("cached_input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0), "reasoning_output_tokens": usage.get("reasoning_output_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0), "match_method": match_result.method,
                "match_delta_seconds": round(match_result.delta_seconds, 3)
                if match_result.delta_seconds is not None else "",
                "match_candidate_count": match_result.eligible_candidate_count,
                "match_ambiguity": match_result.ambiguity_status, "done": done,
                "passed": passed if passed is not None else "", "request_attention": attention,
                "final_status": task_state.get(task_id, {}).get("status", ""), "note": path.name,
            }
        )

    if first_attempt_start and first_attempt_start > project_start:
        stage_seconds["planning"] += seconds(project_start, first_attempt_start)
        rows.append(
            {
                "event_kind": "phase", "event_id": "initial-planning", "event_type": "planning", "stage": "planning",
                "start_utc": iso(project_start), "end_utc": iso(first_attempt_start),
                "duration_seconds": round(seconds(project_start, first_attempt_start), 3), "session_id": "",
                "input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "reasoning_output_tokens": 0,
                "total_tokens": 0, "match_method": "", "match_delta_seconds": "",
                "match_candidate_count": "", "match_ambiguity": "", "done": "", "passed": "",
                "request_attention": "", "final_status": "",
                "note": "Project creation to first worker dispatch; includes clarification and contract planning.",
            }
        )

    review_results = Counter()
    review_end: datetime | None = None
    for path in review_paths:
        start = terminal_review_start(path)
        match_result = match_session(
            start, "terminal review", sessions, used_sessions, tolerance_seconds=120
        )
        match_results.append(match_result)
        session = match_result.session
        if session:
            matched_raw_session_ids.add(session.session_id)
        payload = read_json(path)
        event_end = session.end if session else start
        review_end = max(review_end, event_end) if review_end else event_end
        active = session.active_seconds if session else 0.0
        if session:
            active_intervals.extend(session.active_intervals)
        usage = session.final_usage if session else {}
        stage_seconds["terminal_review"] += active
        stage_tokens["terminal_review"] += usage.get("total_tokens", 0)
        review_results[f"done_{str(payload.get('done')).lower()}"] += 1
        rows.append(
            {
                "event_kind": "terminal_review", "event_id": path.stem, "event_type": "terminal_review",
                "stage": "terminal_review", "start_utc": iso(start), "end_utc": iso(event_end),
                "duration_seconds": round(active, 3), "session_id": session.session_id if session else "",
                "input_tokens": usage.get("input_tokens", 0), "cached_input_tokens": usage.get("cached_input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0), "reasoning_output_tokens": usage.get("reasoning_output_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0), "match_method": match_result.method,
                "match_delta_seconds": round(match_result.delta_seconds, 3)
                if match_result.delta_seconds is not None else "",
                "match_candidate_count": match_result.eligible_candidate_count,
                "match_ambiguity": match_result.ambiguity_status,
                "done": payload.get("done"), "passed": "",
                "request_attention": not payload.get("done", False), "final_status": state.get("state", ""),
                "note": "Fresh-context reviewer; mission artifacts forbidden by reviewer prompt.",
            }
        )

    decision_rows, growth = parse_decisions(project_root / ".zenith" / "decisions")
    rows.extend(decision_rows)

    for row in rows:
        stage_seconds.setdefault(row["stage"], 0)
        stage_tokens.setdefault(row["stage"], 0)

    all_usage = Counter()
    for row in rows:
        raw_session_id = row["session_id"]
        if raw_session_id:
            row["session_id"] = session_aliases[raw_session_id]

    for session in sessions:
        if session.session_id in matched_raw_session_ids:
            all_usage.update(session.final_usage)

    match_method_counts = Counter(result.method for result in match_results)
    ambiguity_status_counts = Counter(
        result.ambiguity_status for result in match_results if result.ambiguous
    )

    task_type_counts = Counter(task["type"] for task in tasks.values())
    task_status_counts = Counter(value.get("status", "unknown") for value in task_state.values())
    contract_status_counts = Counter(value.get("status", "unknown") for value in contract_state.values())
    action_counts = Counter(row["event_type"] for row in decision_rows)
    initial_task_count = len(tasks) - growth.get("added_tasks", 0)
    initial_contract_count = len(contract_state) - growth.get("added_contracts", 0)
    latest_decision = max((parse_iso(row["start_utc"]) for row in decision_rows), default=project_start)
    end = max(review_end or last_review_start, latest_decision)
    wall_seconds = seconds(project_start, end)
    worker_active_seconds = sum(row["duration_seconds"] for row in rows if row["event_kind"] in {"attempt", "terminal_review"})
    busy_union = interval_union_seconds(active_intervals)

    evidence_stats = tree_stats(durable / "evidence")
    durable_stats = tree_stats(project_root / ".zenith")
    runtime_stats = tree_stats(project_root / ".zenith-runtime")
    report_validator_attempts = sum(
        1 for row in rows
        if row["event_kind"] == "attempt" and row["event_type"] == "validate" and "report-failclosed" in row["event_id"]
    )
    idle_gaps = write_idle_gaps(args.output_dir / "idle_gaps.csv", active_intervals, project_start, end)
    long_idle_gaps = sorted(
        (gap for gap in idle_gaps if gap["duration_seconds"] >= 300),
        key=lambda gap: gap["duration_seconds"],
        reverse=True,
    )

    metrics = {
        "source": {
            "project_id": project["id"], "mission_id": project.get("current_mission_id"),
            "workspace_dir": HISTORICAL_WORKSPACE, "project_created_at": iso(project_start),
            "analysis_end_at": iso(end), "runtime_state_after_reviews": state.get("state"),
        },
        "elapsed": {
            "wall_seconds": round(wall_seconds, 3), "wall_hours": round(wall_seconds / 3600, 3),
            "planning_to_first_dispatch_seconds": round(seconds(project_start, first_attempt_start), 3),
            "matched_worker_and_reviewer_active_seconds": round(worker_active_seconds, 3),
            "matched_worker_and_reviewer_active_hours": round(worker_active_seconds / 3600, 3),
            "union_busy_seconds": round(busy_union, 3),
            "effective_parallelism_when_busy": round(worker_active_seconds / busy_union, 3) if busy_union else None,
            "nonbusy_seconds": round(max(0.0, wall_seconds - busy_union), 3),
            "nonbusy_hours": round(max(0.0, wall_seconds - busy_union) / 3600, 3),
            "idle_gap_count_at_least_5m": len(long_idle_gaps),
            "largest_idle_gaps_seconds": [gap["duration_seconds"] for gap in long_idle_gaps[:10]],
        },
        "topology": {
            "initial_task_count_inferred": initial_task_count, "final_task_count": len(tasks),
            "task_growth_factor": round(len(tasks) / initial_task_count, 3) if initial_task_count else None,
            "task_types": dict(task_type_counts), "task_statuses": dict(task_status_counts),
            "initial_contract_count_inferred": initial_contract_count, "final_contract_count": len(contract_state),
            "contract_growth_factor": round(len(contract_state) / initial_contract_count, 3) if initial_contract_count else None,
            "contract_statuses": dict(contract_status_counts), "patch_growth": growth,
        },
        "execution": {
            "attempt_count": sum(row["event_kind"] == "attempt" for row in rows),
            "terminal_review_count": sum(row["event_kind"] == "terminal_review" for row in rows),
            "terminal_review_results": dict(review_results), "decision_count": sum(action_counts.values()),
            "decision_actions": dict(action_counts), "attempt_outcomes": dict(outcome_counts),
            "report_failclosed_validator_attempts": report_validator_attempts,
            "matched_sessions": len(matched_raw_session_ids),
            "match_method_counts": dict(match_method_counts),
            "ambiguity_status_counts": dict(ambiguity_status_counts),
            "ambiguous_match_count": match_method_counts.get("ambiguous", 0),
            "unmatched_match_count": match_method_counts.get("unmatched", 0),
            "unmatched_attempt_count": len(unmatched_attempts), "unmatched_attempts": unmatched_attempts,
        },
        "usage": dict(all_usage),
        "stage_active_seconds": {key: round(value, 3) for key, value in stage_seconds.items()},
        "stage_total_tokens": dict(stage_tokens),
        "artifacts": {"mission_evidence": evidence_stats, "durable_project_tree": durable_stats, "runtime_tree": runtime_stats},
        "method_limits": [
            "Session token counters are Codex-reported totals; input totals include cached input and should not be added to cached input again.",
            "Active time uses task_started/task_complete intervals from matched Codex sessions. It excludes uninstrumented shell/service latency outside those sessions.",
            "The task and contract baselines are inferred by subtracting patch additions from final state; in-place textual growth is not represented.",
            "This mission-evidence-payload-blind analysis did not open production-log or mission-evidence payload content; it read bounded Codex session/event text only for event-to-session correlation.",
            "Ambiguous and unmatched events remain in the execution ledger but contribute no matched duration or token usage; zero unmatched events would not prove attribution correctness.",
        ],
    }

    write_csv(args.output_dir / "execution_ledger.csv", rows)
    (args.output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
