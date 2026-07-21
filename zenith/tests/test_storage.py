"""Storage layer tests. See specs/memory_v2/PRODUCT.md for layout."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from zenith_harness.config import HarnessConfig
from zenith_harness.models import (
    AttentionItemInternal,
    Decision,
    Task,
    TaskList,
    TaskStateFile,
    TerminalReviewHandoff,
    ValidateHandoff,
    ValidationItem,
    WorkHandoff,
)
from zenith_harness.storage import (
    ProjectStore,
    WorkspaceLeaseConflict,
    slugify,
    utc_now_filesafe,
)


@pytest.fixture
def config(harness_home: Path) -> HarnessConfig:
    bundled = Path(__file__).resolve().parents[1] / "src" / "zenith_harness" / "bundled"
    return HarnessConfig(
        bundled_dir=bundled,
        harness_home=harness_home,
        projects_dir=harness_home / "projects",
        orchestrator_provider_name="claude",
        worker_provider_name="claude",
        worker_acp_command=None,
        validator_provider_name=None,
        validator_acp_command=None,
        terminal_reviewer_provider_name=None,
        terminal_reviewer_acp_command=None,
    )


@pytest.fixture
def store(config: HarnessConfig) -> ProjectStore:
    return ProjectStore(config)


class TestProjectLifecycle:
    def test_create_lays_out_bucket(
        self, store: ProjectStore, workspace: Path, harness_home: Path
    ) -> None:
        record = store.create_project("Build a thing.", workspace, project_id="p1")
        assert record.id == "p1"
        bucket_root = harness_home / "projects" / "p1"
        zenith = bucket_root / ".zenith"
        runtime = bucket_root / ".zenith-runtime"
        # Durable
        assert (zenith / "brief.md").read_text().startswith("Build a thing.")
        assert (zenith / "AGENTS.md").exists()
        assert (zenith / "MEMORY.md").read_text().startswith("# Project memory")
        assert (zenith / "decisions").is_dir()
        assert (zenith / "skills").is_dir()
        assert (zenith / "missions").is_dir()
        # Runtime
        assert (runtime / "project.json").exists()
        assert (runtime / "missions").is_dir()
        # Workspace stays clean of .zenith/
        assert not (workspace / ".zenith").exists()

    def test_workspace_gitignore_untouched(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        gitignore = workspace / ".gitignore"
        gitignore.write_text("node_modules/\n")
        original = gitignore.read_text()
        store.create_project("brief", workspace, project_id="p1")
        assert gitignore.read_text() == original

    def test_symlink_shims_created(
        self, store: ProjectStore, workspace: Path, harness_home: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        skills_target = (harness_home / "projects" / "p1" / ".zenith" / "skills").resolve()
        for host in (".agents", ".claude", ".codex"):
            link = workspace / host / "skills"
            assert link.is_symlink()
            assert link.resolve() == skills_target
        root_md = workspace / "AGENTS.md"
        assert root_md.is_symlink()
        assert root_md.resolve() == (
            harness_home / "projects" / "p1" / ".zenith" / "AGENTS.md"
        ).resolve()

    def test_existing_workspace_agents_md_is_preserved(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        agents_md = workspace / "AGENTS.md"
        agents_md.write_text("# User project guidance\n\nKeep this.\n")

        store.create_project("brief", workspace, project_id="p1")
        store.sync_workspace_skill_surfaces("p1")

        assert agents_md.is_file()
        assert not agents_md.is_symlink()
        assert agents_md.read_text() == "# User project guidance\n\nKeep this.\n"

    @pytest.mark.parametrize("host", [".agents", ".claude", ".codex"])
    def test_existing_host_skills_dir_is_merged(
        self, store: ProjectStore, workspace: Path, host: str
    ) -> None:
        skills_dir = workspace / host / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "project-skill" / "SKILL.md").parent.mkdir()
        (skills_dir / "project-skill" / "SKILL.md").write_text("# Project skill\n")

        store.create_project("brief", workspace, project_id="p1")
        bucket_skills = store.zenith_dir("p1") / "skills"

        assert skills_dir.is_dir()
        assert not skills_dir.is_symlink()
        assert (bucket_skills / "project-skill" / "SKILL.md").read_text() == (
            "# Project skill\n"
        )
        assert (skills_dir / "scrutiny-validator" / "SKILL.md").exists()

    def test_sync_workspace_skill_surfaces_updates_preserved_host_dir(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        skills_dir = workspace / ".codex" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "project-skill" / "SKILL.md").parent.mkdir()
        (skills_dir / "project-skill" / "SKILL.md").write_text("# Project skill\n")

        store.create_project("brief", workspace, project_id="p1")
        bucket_skill = store.zenith_dir("p1") / "skills" / "new-worker" / "SKILL.md"
        bucket_skill.parent.mkdir(parents=True)
        bucket_skill.write_text("# New worker\n")

        assert skills_dir.is_dir()
        assert not skills_dir.is_symlink()
        assert not (skills_dir / "new-worker" / "SKILL.md").exists()

        store.sync_workspace_skill_surfaces("p1")

        assert skills_dir.is_dir()
        assert not skills_dir.is_symlink()
        assert (skills_dir / "new-worker" / "SKILL.md").read_text() == "# New worker\n"

    @pytest.mark.parametrize("host", [".agents", ".claude", ".codex"])
    def test_bootstrap_host_skills_dir_becomes_bucket_symlink(
        self, store: ProjectStore, workspace: Path, harness_home: Path, host: str
    ) -> None:
        skills_dir = workspace / host / "skills"
        bundled_skill = (
            store.config.bundled_dir / "skills" / "scrutiny-validator" / "SKILL.md"
        )
        seeded_skill = skills_dir / "scrutiny-validator" / "SKILL.md"
        seeded_skill.parent.mkdir(parents=True)
        seeded_skill.write_text(bundled_skill.read_text())

        store.create_project("brief", workspace, project_id="p1")

        assert skills_dir.is_symlink()
        assert skills_dir.resolve() == (
            harness_home / "projects" / "p1" / ".zenith" / "skills"
        ).resolve()
        assert (skills_dir / "scrutiny-validator" / "SKILL.md").exists()

    def test_init_is_idempotent(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        zenith = store.zenith_dir("p1")
        original_brief = (zenith / "brief.md").read_text()
        memory_path = zenith / "MEMORY.md"
        memory_path.write_text("custom memory\n")
        store.create_project("DIFFERENT brief", workspace, project_id="p1")
        assert (zenith / "brief.md").read_text() == original_brief
        assert memory_path.read_text() == "custom memory\n"

    def test_dangling_shim_retargeted(
        self, store: ProjectStore, workspace: Path, harness_home: Path, tmp_path: Path
    ) -> None:
        # Plant a dangling symlink at workspace/.claude/skills.
        (workspace / ".claude").mkdir()
        dangling = workspace / ".claude" / "skills"
        dangling.symlink_to(tmp_path / "does-not-exist")
        store.create_project("brief", workspace, project_id="p1")
        assert dangling.is_symlink() and dangling.exists()
        assert dangling.resolve() == (
            harness_home / "projects" / "p1" / ".zenith" / "skills"
        ).resolve()

    def test_load_project_roundtrip(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        loaded = store.load_project("p1")
        assert loaded.id == "p1"
        assert loaded.workspace_dir == str(workspace.resolve())

    def test_missing_workspace_rejected(
        self, store: ProjectStore, tmp_path: Path
    ) -> None:
        with pytest.raises(FileNotFoundError):
            store.create_project("brief", tmp_path / "ghost", project_id="p1")

    def test_list_projects(
        self, store: ProjectStore, workspace: Path, tmp_path: Path
    ) -> None:
        ws2 = tmp_path / "ws2"
        ws2.mkdir()
        store.create_project("a", workspace, project_id="a-pid")
        store.create_project("b", ws2, project_id="b-pid")
        ids = {p.id for p in store.list_projects()}
        assert ids == {"a-pid", "b-pid"}


class TestTaskListAndContract:
    def test_save_and_load_task_list(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        tl = TaskList(tasks=[
            Task(id="w1", type="work", body="b", targets=["VAL-001"], skill="s")
        ])
        store.save_task_list("p1", "mission-001", tl)
        back = store.load_task_list("p1", "mission-001")
        assert back == tl

    def test_list_contract_assertions(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        d = store.ensure_contract_dir("p1", "mission-001")
        (d / "VAL-001.md").write_text("body 1\n")
        (d / "VAL-002.md").write_text("body 2\n")
        (d / "README.md").write_text("overview\n")
        assert store.list_contract_assertions("p1", "mission-001") == [
            "VAL-001",
            "VAL-002",
        ]

    def test_load_contract_assertion(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        d = store.ensure_contract_dir("p1", "mission-001")
        (d / "VAL-001.md").write_text("Hello.\n")
        assert store.load_contract_assertion("p1", "mission-001", "VAL-001") == "Hello.\n"


class TestTaskState:
    def test_default_empty(self, store: ProjectStore, workspace: Path) -> None:
        store.create_project("brief", workspace, project_id="p1")
        ts = store.load_task_state("p1", "mission-001")
        assert ts.tasks == {}

    def test_roundtrip(self, store: ProjectStore, workspace: Path) -> None:
        store.create_project("brief", workspace, project_id="p1")
        ts = TaskStateFile()
        ts.set_status("w1", "running")
        ts.set_status("v1", "cleared")
        store.save_task_state("p1", "mission-001", ts)
        back = store.load_task_state("p1", "mission-001")
        assert back.status_of("w1") == "running"
        assert back.status_of("v1") == "cleared"


class TestAttempts:
    def test_roundtrip_work(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        h = WorkHandoff(node_id="w1", done=True, report="done", request_attention=False)
        ts = utc_now_filesafe()
        path = store.save_attempt("p1", "mission-001", ts, "w1", h)
        assert path.exists()
        back = store.read_attempt("p1", "mission-001", ts, "w1")
        assert isinstance(back, WorkHandoff)
        assert back == h
        # JSON handoff lives in the runtime cursor tree; MD mirror in durable .zenith.
        assert path.parent == store.attempts_runtime_dir("p1", "mission-001")
        assert ".zenith-runtime" in path.parts
        md_path = store.attempt_report_path("p1", "mission-001", ts, "w1")
        assert md_path.exists()
        assert md_path.parent == store.attempts_dir("p1", "mission-001")

    def test_roundtrip_validate(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        h = ValidateHandoff(
            node_id="v1",
            done=True,
            report="audited",
            items=[ValidationItem(item_id="VAL-001", passed=True)],
            passed=True,
        )
        ts = utc_now_filesafe()
        store.save_attempt("p1", "mission-001", ts, "v1", h)
        back = store.read_attempt("p1", "mission-001", ts, "v1")
        assert isinstance(back, ValidateHandoff)
        assert back.items[0].item_id == "VAL-001"

    def test_idempotent_overwrite(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        h = WorkHandoff(node_id="w1", done=True, report="v1")
        ts = utc_now_filesafe()
        store.save_attempt("p1", "mission-001", ts, "w1", h)
        h2 = WorkHandoff(node_id="w1", done=True, report="v2")
        store.save_attempt("p1", "mission-001", ts, "w1", h2)
        back = store.read_attempt("p1", "mission-001", ts, "w1")
        assert isinstance(back, WorkHandoff)
        assert back.report == "v2"

    def test_list_filters_by_node(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        for ts, nid in [("2026-01-01T00-00-00Z", "w1"), ("2026-01-02T00-00-00Z", "w2")]:
            store.save_attempt(
                "p1", "mission-001", ts, nid,
                WorkHandoff(node_id=nid, done=True, report=""),
            )
        records = store.list_attempts("p1", "mission-001", node_id="w1")
        assert len(records) == 1 and records[0].node_id == slugify("w1", "w1")


class TestAttention:
    def test_save_and_load(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        items = [
            AttentionItemInternal(
                id="att-1",
                kind="gate_checkpoint",
                mission_id="mission-001",
                report="Gate report from g1",
                node_id="g1",
            )
        ]
        store.save_attention("p1", items)
        back = store.load_attention("p1")
        assert back[0].id == "att-1"

    def test_clear(self, store: ProjectStore, workspace: Path) -> None:
        store.create_project("brief", workspace, project_id="p1")
        store.save_attention(
            "p1",
            [
                AttentionItemInternal(
                    id="x",
                    kind="gate_checkpoint",
                    mission_id="m1",
                    report="Gate report from g1",
                )
            ],
        )
        store.clear_attention("p1")
        assert store.load_attention("p1") == []


class TestDecisions:
    def test_appends_numbered_files(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        items = [
            AttentionItemInternal(
                id="att-1",
                kind="gate_checkpoint",
                mission_id="mission-001",
                report="Gate report from g1",
                node_id="g1",
            )
        ]
        decisions = [Decision(item_id="att-1", action="continue")]
        path1 = store.append_decision_record("p1", decisions, items, summary="first")
        path2 = store.append_decision_record("p1", decisions, items, summary="second")
        assert path1.stem.startswith("001-")
        assert path2.stem.startswith("002-")


class TestTerminalReviews:
    def test_save_and_path(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        rep = TerminalReviewHandoff(done=False, report="One blocking gap")
        ts = utc_now_filesafe()
        path = store.save_terminal_review("p1", "mission-001", ts, rep)
        assert path.exists()
        assert path.parent.name == "terminal-reviews"
        # JSON handoff lives in the runtime cursor tree; MD mirror in durable .zenith.
        assert path.parent == store.terminal_reviews_dir("p1", "mission-001")
        assert store.mission_dir("p1", "mission-001") in path.parents
        assert store.mission_runtime_dir("p1", "mission-001") not in path.parents
        assert path.suffix == ".md"
        json_path = store.terminal_review_path("p1", "mission-001", ts)
        assert json_path.exists()
        assert json_path.parent == store.terminal_reviews_runtime_dir(
            "p1", "mission-001"
        )
        assert store.mission_runtime_dir("p1", "mission-001") in json_path.parents
        assert store.mission_dir("p1", "mission-001") not in json_path.parents
        assert json_path.suffix == ".json"


class TestSeal:
    def test_writes_closeout(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        path = store.seal_mission(
            "p1", "mission-001", status="done", body="Everything shipped."
        )
        text = path.read_text()
        assert "status: done" in text and "Everything shipped." in text
        assert path == store.mission_dir("p1", "mission-001") / "closeout.md"


class TestWorkspaceLease:
    def test_same_owner_can_reenter(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        first = store.claim_workspace_lease("p1", "owner-a")
        second = store.claim_workspace_lease("p1", "owner-a")
        assert second.owner_id == first.owner_id
        assert second.claimed_at == first.claimed_at

    def test_different_owner_is_blocked(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        store.claim_workspace_lease("p1", "owner-a")
        with pytest.raises(WorkspaceLeaseConflict, match="owner-a"):
            store.claim_workspace_lease("p1", "owner-b")

    def test_same_owner_cannot_claim_second_project_for_workspace(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("one", workspace, project_id="p1")
        store.create_project("two", workspace, project_id="p2")
        store.claim_workspace_lease("p1", "owner-a")
        with pytest.raises(WorkspaceLeaseConflict, match="p1"):
            store.claim_workspace_lease("p2", "owner-a")

    def test_different_workspaces_allow_parallel_owners(
        self, store: ProjectStore, tmp_path: Path
    ) -> None:
        one = tmp_path / "one"
        two = tmp_path / "two"
        one.mkdir()
        two.mkdir()
        store.create_project("one", one, project_id="p1")
        store.create_project("two", two, project_id="p2")
        assert store.claim_workspace_lease("p1", "owner-a").owner_id == "owner-a"
        assert store.claim_workspace_lease("p2", "owner-b").owner_id == "owner-b"

    def test_non_owner_cannot_release(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        store.claim_workspace_lease("p1", "owner-a")
        with pytest.raises(WorkspaceLeaseConflict, match="owner-a"):
            store.release_workspace_lease("p1", "owner-b")

    def test_release_allows_explicit_handoff(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        store.claim_workspace_lease("p1", "owner-a")
        store.release_workspace_lease("p1", "owner-a")
        assert store.claim_workspace_lease("p1", "owner-b").owner_id == "owner-b"

    def test_record_contains_forensic_identity(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        lease = store.claim_workspace_lease("p1", "owner-a")
        payload = json.loads(lease.path.read_text(encoding="utf-8"))
        assert payload["owner_id"] == "owner-a"
        assert payload["project_id"] == "p1"
        assert payload["workspace_dir"] == str(workspace.resolve())
        assert payload["claimed_at"]
        assert payload["last_seen_at"]
        assert payload["host"]
        assert payload["pid"] > 0
        marker = json.loads(
            (lease.path.parent / "claim.json").read_text(encoding="utf-8")
        )
        assert marker["owner_id"] == "owner-a"
        assert marker["pid"] == payload["pid"]

    def test_atomic_claim_has_exactly_one_winner(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")

        def claim(owner: str) -> str:
            try:
                return store.claim_workspace_lease("p1", owner).owner_id
            except WorkspaceLeaseConflict:
                return "blocked"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, ["owner-a", "owner-b"]))
        assert results.count("blocked") == 1
        assert len({value for value in results if value != "blocked"}) == 1

    def test_live_incomplete_claim_cannot_be_overwritten_by_second_owner(
        self,
        store: ProjectStore,
        workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        first_ready = Event()
        allow_first_publish = Event()
        original_write = store._write_workspace_lease_record

        def pause_first_writer(dir_fd: int, payload: object) -> None:
            assert isinstance(payload, dict)
            if payload["owner_id"] == "owner-a":
                first_ready.set()
                assert allow_first_publish.wait(timeout=5)
            original_write(dir_fd, payload)

        monkeypatch.setattr(
            store, "_write_workspace_lease_record", pause_first_writer
        )

        def claim_first() -> str:
            try:
                return store.claim_workspace_lease("p1", "owner-a").owner_id
            except WorkspaceLeaseConflict:
                return "blocked"

        def claim_second() -> str:
            try:
                return store.claim_workspace_lease("p1", "owner-b").owner_id
            except WorkspaceLeaseConflict:
                return "blocked"

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(claim_first)
            assert first_ready.wait(timeout=2)
            second = pool.submit(claim_second)
            assert second.result(timeout=5) == "blocked"
            allow_first_publish.set()
            assert first.result(timeout=5) == "owner-a"

        assert store.claim_workspace_lease("p1", "owner-a").owner_id == "owner-a"

    def test_ownerless_dead_claim_is_fenced_and_recovered(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        lease = store.claim_workspace_lease("p1", "owner-a")
        lease.path.unlink()
        claim_path = lease.path.parent / "claim.json"
        claim = json.loads(claim_path.read_text(encoding="utf-8"))
        claim["pid"] = 999_999_999
        claim_path.write_text(json.dumps(claim), encoding="utf-8")

        recovered = store.claim_workspace_lease("p1", "owner-b")
        assert recovered.owner_id == "owner-b"

    def test_malformed_dead_claim_is_fenced_and_recovered(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        lease = store.claim_workspace_lease("p1", "owner-a")
        lease.path.write_text("{partial", encoding="utf-8")
        claim_path = lease.path.parent / "claim.json"
        claim = json.loads(claim_path.read_text(encoding="utf-8"))
        claim["pid"] = 999_999_999
        claim_path.write_text(json.dumps(claim), encoding="utf-8")

        recovered = store.claim_workspace_lease("p1", "owner-b")
        assert recovered.owner_id == "owner-b"

    def test_malformed_live_claim_remains_fenced(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        lease = store.claim_workspace_lease("p1", "owner-a")
        lease.path.write_text("{partial", encoding="utf-8")

        with pytest.raises(WorkspaceLeaseConflict, match="incomplete active claim"):
            store.claim_workspace_lease("p1", "owner-b")

    def test_owner_id_is_bounded_and_safe(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        with pytest.raises(ValueError, match="unsupported"):
            store.claim_workspace_lease_for_workspace(
                workspace, "p1", "owner with spaces"
            )
        with pytest.raises(ValueError, match="at most 200"):
            store.claim_workspace_lease_for_workspace(
                workspace, "p1", "x" * 201
            )

    def test_dead_process_cannot_silently_reuse_same_owner_id(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        lease = store.claim_workspace_lease("p1", "owner-a")
        for name in ("claim.json", "owner.json"):
            path = lease.path.parent / name
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["pid"] = 999_999_999
            path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(WorkspaceLeaseConflict, match="explicit recovery"):
            store.claim_workspace_lease("p1", "owner-a")

    def test_release_removes_abandoned_temp_files_atomically(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        lease = store.claim_workspace_lease("p1", "owner-a")
        (lease.path.parent / "owner.json.tmp.crashed").write_text(
            "partial", encoding="utf-8"
        )

        store.release_workspace_lease("p1", "owner-a")
        assert store.claim_workspace_lease("p1", "owner-b").owner_id == "owner-b"

    def test_concurrent_same_owner_refreshes_use_unique_temp_files(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        store.claim_workspace_lease("p1", "owner-a")

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(
                pool.map(
                    lambda _: store.claim_workspace_lease("p1", "owner-a").owner_id,
                    range(8),
                )
            )
        assert results == ["owner-a"] * 8

    def test_claim_requires_existing_absolute_workspace(
        self, store: ProjectStore
    ) -> None:
        with pytest.raises(ValueError, match="absolute"):
            store.claim_workspace_lease_for_workspace(
                "relative-workspace", "p1", "owner-a"
            )
