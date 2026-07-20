from __future__ import annotations

import csv
import importlib.util
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

import pytest


UTC = timezone.utc
PROJECT_ID = "synthetic-project"
MISSION_ID = "mission-001"
ANALYZER = Path(__file__).with_name("analyze_trace.py")
TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _stamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H-%M-%SZ")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def _write_session(
    sessions_root: Path,
    *,
    provider_id: str,
    start: datetime,
    correlation_ids: tuple[str, ...],
    total_tokens: int,
) -> None:
    usage = {
        "input_tokens": total_tokens - 3,
        "cached_input_tokens": total_tokens - 5,
        "output_tokens": 2,
        "reasoning_output_tokens": 1,
        "total_tokens": total_tokens,
    }
    rows = [
        {
            "timestamp": _iso(start),
            "type": "session_meta",
            "payload": {
                "id": provider_id,
                "timestamp": _iso(start),
                "thread_source": "subagent",
                "source": {"project_id": PROJECT_ID},
            },
        },
        {
            "timestamp": _iso(start),
            "type": "event_msg",
            "payload": {"type": "task_started", "correlation_ids": correlation_ids},
        },
        {
            "timestamp": _iso(start + timedelta(seconds=2)),
            "type": "event_msg",
            "payload": {"type": "token_count", "info": {"total_token_usage": usage}},
        },
        {
            "timestamp": _iso(start + timedelta(seconds=4)),
            "type": "event_msg",
            "payload": {"type": "task_complete"},
        },
    ]
    path = sessions_root / f"{provider_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _write_attempt(runtime: Path, start: datetime, task_id: str) -> None:
    _write_json(
        runtime / "attempts" / f"{_stamp(start)}-0000__{task_id}.json",
        {"done": True, "passed": None, "request_attention": False},
    )


@pytest.fixture
def synthetic_trace(tmp_path: Path) -> tuple[Path, Path, set[str]]:
    project_root = tmp_path / "private-input" / "project"
    sessions_root = tmp_path / "private-input" / "sessions"
    runtime_root = project_root / ".zenith-runtime"
    runtime = runtime_root / "missions" / MISSION_ID
    durable = project_root / ".zenith" / "missions" / MISSION_ID
    start = datetime(2026, 1, 1, tzinfo=UTC)

    task_times = {
        "unique-task": start + timedelta(minutes=1),
        "unique-fallback": start + timedelta(minutes=2),
        "multi-fallback": start + timedelta(minutes=3),
        "multi-later-a": start + timedelta(minutes=3, seconds=30),
        "multi-later-b": start + timedelta(minutes=3, seconds=50),
        "equal-tie": start + timedelta(minutes=6),
        "tie-later-a": start + timedelta(minutes=6, seconds=30),
        "tie-later-b": start + timedelta(minutes=6, seconds=50),
        "unmatched-task": start + timedelta(minutes=8),
    }
    tasks = [{"id": task_id, "type": "work"} for task_id in task_times]
    _write_json(
        runtime_root / "project.json",
        {
            "id": PROJECT_ID,
            "current_mission_id": MISSION_ID,
            "created_at": _iso(start),
            "workspace_dir": str(tmp_path / "machine-specific-workspace"),
        },
    )
    _write_json(runtime_root / "state.json", {"state": "mission_running"})
    _write_json(runtime / "tasks.json", {"tasks": tasks})
    _write_json(
        runtime / "task-state.json",
        {"tasks": {task["id"]: {"status": "complete"} for task in tasks}},
    )
    _write_json(runtime / "contract-state.json", {"items": {}})
    for task_id, task_start in task_times.items():
        _write_attempt(runtime, task_start, task_id)

    provider_ids = {
        "synthetic-provider-unique",
        "synthetic-provider-fallback",
        "synthetic-provider-multi-a",
        "synthetic-provider-multi-b",
        "synthetic-provider-tie-a",
        "synthetic-provider-tie-b",
        "synthetic-provider-review",
    }
    _write_session(
        sessions_root,
        provider_id="synthetic-provider-unique",
        start=start + timedelta(minutes=1, seconds=5),
        correlation_ids=("unique-task",),
        total_tokens=11,
    )
    _write_session(
        sessions_root,
        provider_id="synthetic-provider-fallback",
        start=start + timedelta(minutes=2, seconds=5),
        correlation_ids=(),
        total_tokens=12,
    )
    _write_session(
        sessions_root,
        provider_id="synthetic-provider-multi-a",
        start=start + timedelta(minutes=2, seconds=55),
        correlation_ids=("multi-later-a",),
        total_tokens=13,
    )
    _write_session(
        sessions_root,
        provider_id="synthetic-provider-multi-b",
        start=start + timedelta(minutes=3, seconds=5),
        correlation_ids=("multi-later-b",),
        total_tokens=14,
    )
    _write_session(
        sessions_root,
        provider_id="synthetic-provider-tie-a",
        start=start + timedelta(minutes=5, seconds=55),
        correlation_ids=("equal-tie", "tie-later-a"),
        total_tokens=15,
    )
    _write_session(
        sessions_root,
        provider_id="synthetic-provider-tie-b",
        start=start + timedelta(minutes=6, seconds=5),
        correlation_ids=("equal-tie", "tie-later-b"),
        total_tokens=16,
    )

    review_start = start + timedelta(minutes=10)
    _write_json(
        runtime / "terminal-reviews" / f"{_stamp(review_start)}.json", {"done": False}
    )
    _write_session(
        sessions_root,
        provider_id="synthetic-provider-review",
        start=review_start + timedelta(seconds=2),
        correlation_ids=("terminal review",),
        total_tokens=17,
    )

    (durable / "evidence").mkdir(parents=True)
    (project_root / ".zenith" / "decisions").mkdir(parents=True)
    return project_root, sessions_root, provider_ids


def _run_analyzer(project_root: Path, sessions_root: Path, output_dir: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ANALYZER),
            "--project-root",
            str(project_root),
            "--sessions-root",
            str(sessions_root),
            "--output-dir",
            str(output_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def _load_analyzer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("synthetic_analyze_trace", ANALYZER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_session_aliases_are_stable_and_preserve_joins() -> None:
    analyzer = _load_analyzer()
    start = datetime(2026, 1, 1, tzinfo=UTC)

    def session(provider_id: str, offset: int) -> object:
        stamp = start + timedelta(seconds=offset)
        return analyzer.Session(
            path=Path(f"{provider_id}.jsonl"),
            session_id=provider_id,
            start=stamp,
            end=stamp,
            active_intervals=[],
            thread_source="subagent",
            source="synthetic",
            final_usage={},
            text="",
        )

    first = session("synthetic-provider-a", 10)
    same_provider = session("synthetic-provider-a", 20)
    earlier = session("synthetic-provider-b", 0)
    aliases = analyzer.build_session_aliases([first, same_provider, earlier])

    assert (
        aliases[first.session_id] == aliases[same_provider.session_id] == "session-002"
    )
    assert aliases[earlier.session_id] == "session-001"
    assert len(set(aliases.values())) == 2


def test_synthetic_cli_fails_closed_reconciles_and_is_deterministic(
    synthetic_trace: tuple[Path, Path, set[str]],
    tmp_path: Path,
) -> None:
    project_root, sessions_root, provider_ids = synthetic_trace
    first_output = tmp_path / "first-output"
    second_output = tmp_path / "second-output"
    _run_analyzer(project_root, sessions_root, first_output)
    _run_analyzer(project_root, sessions_root, second_output)

    first_files = sorted(
        path.relative_to(first_output)
        for path in first_output.rglob("*")
        if path.is_file()
    )
    second_files = sorted(
        path.relative_to(second_output)
        for path in second_output.rglob("*")
        if path.is_file()
    )
    assert (
        first_files
        == second_files
        == [
            Path("execution_ledger.csv"),
            Path("idle_gaps.csv"),
            Path("metrics.json"),
        ]
    )
    assert all(
        (first_output / relative).read_bytes()
        == (second_output / relative).read_bytes()
        for relative in first_files
    )

    with (first_output / "execution_ledger.csv").open(newline="") as handle:
        ledger = list(csv.DictReader(handle))
    metrics = json.loads((first_output / "metrics.json").read_text())
    rows = {row["event_id"]: row for row in ledger}

    assert rows["unique-task"]["match_method"] == "task_id_and_time"
    assert rows["unique-task"]["match_delta_seconds"] == "5.0"
    assert rows["unique-task"]["match_candidate_count"] == "1"
    assert rows["unique-task"]["match_ambiguity"] == "not_ambiguous"
    assert rows["unique-fallback"]["match_method"] == "time_only_unique"
    assert rows["unique-fallback"]["match_delta_seconds"] == "5.0"
    assert rows["unique-fallback"]["match_candidate_count"] == "1"
    assert rows["unique-fallback"]["match_ambiguity"] == "not_ambiguous"

    assert rows["multi-fallback"]["match_method"] == "ambiguous"
    assert rows["multi-fallback"]["match_delta_seconds"] == "5.0"
    assert rows["multi-fallback"]["match_candidate_count"] == "2"
    assert rows["multi-fallback"]["match_ambiguity"] == "multiple_time_only_candidates"
    assert rows["equal-tie"]["match_method"] == "ambiguous"
    assert rows["equal-tie"]["match_delta_seconds"] == "5.0"
    assert rows["equal-tie"]["match_candidate_count"] == "2"
    assert rows["equal-tie"]["match_ambiguity"] == "task_id_and_time_tie"
    assert rows["unmatched-task"]["match_method"] == "unmatched"
    assert rows["unmatched-task"]["match_delta_seconds"] == ""
    assert rows["unmatched-task"]["match_candidate_count"] == "0"
    assert rows["unmatched-task"]["match_ambiguity"] == "not_ambiguous"

    for event_id in ("multi-fallback", "equal-tie", "unmatched-task"):
        assert rows[event_id]["session_id"] == ""
        assert float(rows[event_id]["duration_seconds"]) == 0
        assert all(int(rows[event_id][field]) == 0 for field in TOKEN_FIELDS)

    assert rows["multi-later-a"]["match_method"] == "task_id_and_time"
    assert rows["multi-later-b"]["match_method"] == "task_id_and_time"
    assert rows["tie-later-a"]["match_method"] == "task_id_and_time"
    assert rows["tie-later-b"]["match_method"] == "task_id_and_time"

    match_rows = [row for row in ledger if row["match_method"]]
    recomputed_methods = Counter(row["match_method"] for row in match_rows)
    recomputed_ambiguities = Counter(
        row["match_ambiguity"]
        for row in match_rows
        if row["match_method"] == "ambiguous"
    )
    assert metrics["execution"]["match_method_counts"] == dict(recomputed_methods)
    assert metrics["execution"]["ambiguity_status_counts"] == dict(
        recomputed_ambiguities
    )
    assert (
        metrics["execution"]["ambiguous_match_count"]
        == recomputed_methods["ambiguous"]
        == 2
    )
    assert (
        metrics["execution"]["unmatched_match_count"]
        == recomputed_methods["unmatched"]
        == 1
    )
    assert metrics["execution"]["unmatched_attempt_count"] == 1
    assert metrics["execution"]["attempt_count"] == sum(
        row["event_kind"] == "attempt" for row in ledger
    )
    assert metrics["execution"]["terminal_review_count"] == sum(
        row["event_kind"] == "terminal_review" for row in ledger
    )

    recomputed_usage = {
        field: sum(int(row[field]) for row in match_rows) for field in TOKEN_FIELDS
    }
    assert metrics["usage"] == recomputed_usage
    stages = {row["stage"] for row in ledger}
    assert metrics["stage_active_seconds"] == {
        stage: sum(
            float(row["duration_seconds"]) for row in ledger if row["stage"] == stage
        )
        for stage in stages
    }
    assert metrics["stage_total_tokens"] == {
        stage: sum(int(row["total_tokens"]) for row in ledger if row["stage"] == stage)
        for stage in stages
    }

    public_bytes = b"\n".join(
        (first_output / relative).read_bytes() for relative in first_files
    )
    assert metrics["source"]["workspace_dir"] == "<historical-workspace>"
    assert str(tmp_path).encode() not in public_bytes
    assert not any(provider_id.encode() in public_bytes for provider_id in provider_ids)
    selected_aliases = {row["session_id"] for row in match_rows if row["session_id"]}
    assert len(selected_aliases) == 7
    assert all(re.fullmatch(r"session-\d{3}", alias) for alias in selected_aliases)
