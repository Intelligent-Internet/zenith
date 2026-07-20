"""Storage layer tests. See specs/memory_v2/PRODUCT.md for layout."""
from __future__ import annotations

from pathlib import Path

import pytest

from zenith_harness.config import HarnessConfig
from zenith_harness.models import (
    AttentionItemInternal,
    Decision,
    Task,
    TaskList,
    TaskStateFile,
    TerminalReviewConfig,
    TerminalReviewHandoff,
    ValidateHandoff,
    ValidationItem,
    WorkHandoff,
)
from zenith_harness.storage import ProjectStore, slugify, utc_now_filesafe


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

    def test_declared_roots_are_narrow_and_persisted(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        mission = store.mission_dir("p1", "mission-001")
        report = mission / "evidence" / "report.md"
        report.parent.mkdir(parents=True)
        report.write_text("report")

        roots = store.resolve_terminal_review_roots(
            "p1", "mission-001", [str(report)]
        )
        config = TerminalReviewConfig(deliverable_roots=roots)
        store.save_terminal_review_config("p1", "mission-001", config)
        assert store.load_terminal_review_config("p1", "mission-001") == config

        with pytest.raises(ValueError, match="forbidden mission artifact"):
            store.resolve_terminal_review_roots("p1", "mission-001", [str(mission)])
        with pytest.raises(ValueError, match="forbidden workspace artifact"):
            store.resolve_terminal_review_roots("p1", "mission-001", [str(workspace)])

    def test_declared_roots_reject_escaping_or_injecting_paths(
        self, store: ProjectStore, workspace: Path
    ) -> None:
        store.create_project("brief", workspace, project_id="p1")
        mission = store.mission_dir("p1", "mission-001")
        report_dir = mission / "evidence" / "report"
        report_dir.mkdir(parents=True)
        (report_dir / "escape").symlink_to(store.zenith_dir("p1") / "MEMORY.md")
        with pytest.raises(ValueError, match="symlink outside"):
            store.resolve_terminal_review_roots(
                "p1", "mission-001", [str(report_dir)]
            )

        bad_name = mission / "evidence" / "report\ninjected.md"
        bad_name.write_text("report")
        with pytest.raises(ValueError, match="control characters"):
            store.resolve_terminal_review_roots(
                "p1", "mission-001", [str(bad_name)]
            )


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
