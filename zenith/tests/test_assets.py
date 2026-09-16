"""AssetLoader tests — skill discovery and bundled agent metadata."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from zenith_harness.assets import AssetLoader, iter_skill_directories, parse_frontmatter
from zenith_harness.config import HarnessConfig
from zenith_harness.models import ASSERTION_ID_REGEX


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
def loader(config: HarnessConfig) -> AssetLoader:
    return AssetLoader(config)


class TestSkillResolution:
    def test_missing_skill_directory_lists_empty(self, tmp_path: Path) -> None:
        assert iter_skill_directories(tmp_path / "missing") == []

    @pytest.mark.parametrize(
        "skill_name", ["scrutiny-validator", "engineering-mission-playbook"]
    )
    def test_bundled_skill_loads(self, loader: AssetLoader, skill_name: str) -> None:
        s = loader.load_skill(skill_name)
        assert s.name == skill_name
        assert s.source == "bundled"
        assert s.body.strip()

    def test_all_bundled_skills_have_parseable_metadata(
        self, loader: AssetLoader
    ) -> None:
        for skill_name in sorted(_bundled_skill_names()):
            skill = loader.load_skill(skill_name)
            assert skill.name == skill_name
            assert skill.description
            assert skill.body.strip()

    def test_project_authored_worker_skill_loads(
        self,
        loader: AssetLoader,
        config: HarnessConfig,
        workspace: Path,
    ) -> None:
        # Project skills live in the bucket — create a project, then drop the
        # skill into `<bucket>/.zenith/skills/<name>/SKILL.md`.
        from zenith_harness.storage import ProjectStore

        store = ProjectStore(config)
        store.create_project("brief", workspace, project_id="p1")
        proj_skill = config.zenith_dir("p1") / "skills" / "api-contract-worker"
        proj_skill.mkdir(parents=True, exist_ok=True)
        (proj_skill / "SKILL.md").write_text(
            "---\nname: api-contract-worker\ndescription: project-authored worker procedure\n---\n\nProject body.\n"
        )
        s = loader.load_skill("api-contract-worker", project_id="p1")
        assert s.source == "project"
        assert "Project body" in s.body

    def test_load_skill_missing_raises(self, loader: AssetLoader) -> None:
        with pytest.raises(FileNotFoundError, match="Skill not found: no-such-skill"):
            loader.load_skill("no-such-skill")

    def test_list_skills_prefers_project_then_personal_then_bundled(
        self,
        loader: AssetLoader,
        config: HarnessConfig,
    ) -> None:
        project_skill = config.zenith_dir("p-list") / "skills" / "project" / "SKILL.md"
        project_skill.parent.mkdir(parents=True, exist_ok=True)
        project_skill.write_text(
            "---\n"
            "name: shared-skill\n"
            "description: project copy wins\n"
            "---\n\n"
            "Project body.\n",
            encoding="utf-8",
        )
        personal_skill = config.harness_home / "skills" / "personal" / "SKILL.md"
        personal_skill.parent.mkdir(parents=True, exist_ok=True)
        personal_skill.write_text(
            "---\n"
            "name: shared-skill\n"
            "description: personal copy loses\n"
            "---\n\n"
            "Personal body.\n",
            encoding="utf-8",
        )

        with_project = loader.list_skills(project_id="p-list")
        without_project = loader.list_skills()

        shared = [skill for skill in with_project if skill.name == "shared-skill"]
        assert len(shared) == 1
        assert shared[0].source == "project"
        assert shared[0].description == "project copy wins"
        assert all(skill.source != "project" for skill in without_project)


class TestFrontmatter:
    def test_parse_with_frontmatter(self) -> None:
        raw = "---\nname: x\ndescription: y\n---\nbody here\n"
        fm, body = parse_frontmatter(raw)
        assert fm == {"name": "x", "description": "y"}
        assert body.strip() == "body here"

    def test_parse_without_frontmatter(self) -> None:
        raw = "just a body\n"
        fm, body = parse_frontmatter(raw)
        assert fm == {} and body == raw

    def test_parse_incomplete_frontmatter_as_body(self) -> None:
        raw = "---\nname: x\nbody without closing delimiter\n"
        fm, body = parse_frontmatter(raw)
        assert fm == {}
        assert body == raw

    def test_parse_non_mapping_frontmatter_as_empty(self) -> None:
        raw = "---\n- not\n- a\n- mapping\n---\nbody here\n"
        fm, body = parse_frontmatter(raw)
        assert fm == {}
        assert body == "body here\n"


class TestPrompts:
    def test_missing_prompt_file_raises(self, loader: AssetLoader) -> None:
        with pytest.raises(FileNotFoundError, match="Prompt file not found"):
            loader.load_prompt_file("worker", "missing.md")


class TestOpenCodeBundledAgents:
    def test_opencode_subagents_use_markdown_frontmatter(self) -> None:
        agents_dir = BUNDLED_DIR / "providers" / "opencode" / "agents"
        for agent_name in OPENCODE_AGENT_NAMES:
            path = agents_dir / f"{agent_name}.md"
            assert path.exists(), f"missing bundled OpenCode agent: {agent_name}"

            frontmatter, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            permission = frontmatter.get("permission")

            assert frontmatter["description"]
            assert frontmatter["mode"] == "subagent"
            assert "model" not in frontmatter
            assert isinstance(permission, dict)
            assert permission["edit"] == "deny"
            assert permission["task"] == "deny"
            assert body.lstrip().startswith("#")

    def test_opencode_subagent_bodies_preserve_role_intent(self) -> None:
        opencode_dir = BUNDLED_DIR / "providers" / "opencode" / "agents"
        claude_dir = BUNDLED_DIR / "providers" / "claude" / "agents"
        for agent_name in OPENCODE_AGENT_NAMES:
            _, opencode_body = parse_frontmatter(
                (opencode_dir / f"{agent_name}.md").read_text(encoding="utf-8")
            )
            _, claude_body = parse_frontmatter(
                (claude_dir / f"{agent_name}.md").read_text(encoding="utf-8")
            )
            assert opencode_body == claude_body


BUNDLED_DIR = Path(__file__).resolve().parents[1] / "src" / "zenith_harness" / "bundled"
OPENCODE_AGENT_NAMES = (
    "contract-review",
    "feature-reviewer",
    "flow-validator",
    "investigator",
)


def _bundled_md_files() -> list[Path]:
    return sorted(BUNDLED_DIR.rglob("*.md"))


def _bundled_text_files() -> list[Path]:
    return sorted(
        [
            *BUNDLED_DIR.rglob("*.md"),
            *BUNDLED_DIR.rglob("*.toml"),
        ]
    )


def _bundled_skill_names() -> set[str]:
    skills_dir = BUNDLED_DIR / "skills"
    return {p.name for p in skills_dir.iterdir() if (p / "SKILL.md").exists()}


# Match validator-skill references in DAG examples and prose. Two shapes:
#   JSON: "skill": "<name>"
#   Prose: `skill: <name>` (single-backtick code span)
_SKILL_REF_RE = re.compile(
    r'"skill"\s*:\s*"(?P<json>[a-z][a-z0-9-]*)"'
    r'|`skill:\s*(?P<prose>[a-z][a-z0-9-]+)`'
)


class TestAssetConsistency:
    """Static consistency checks across bundled prompts, skills, and playbooks.

    These catch reference drift — playbooks pointing at renamed/deleted skills,
    invalid assertion ids in examples — that the per-skill load tests miss.
    """

    def test_no_stale_example_validator_refs(self) -> None:
        # The `example-*` validator skills were renamed to drop the prefix; no
        # bundled file may still reference them.
        stale_names = (
            "example-scrutiny-validator",
            "example-user-testing-validator",
            "example-benchmark-validator",
        )
        offenders: list[str] = []
        for path in _bundled_text_files():
            text = path.read_text()
            for name in stale_names:
                if name in text:
                    offenders.append(
                        f"{path.relative_to(BUNDLED_DIR)}: contains '{name}'"
                    )
        assert not offenders, (
            "Bundled assets still reference removed example-* validator skills:\n"
            + "\n".join(offenders)
        )

    def test_no_stale_worker_base_refs(self) -> None:
        # `worker-base/SKILL.md` was removed; bundled assets must not load it
        # via Skill(...) or reference it as a node skill.
        offenders: list[str] = []
        patterns = (
            re.compile(r'Skill\(\s*["\']worker-base["\']'),
            re.compile(r'"skill"\s*:\s*"worker-base"'),
            re.compile(r'`skill:\s*worker-base`'),
        )
        for path in _bundled_text_files():
            text = path.read_text()
            for pat in patterns:
                if pat.search(text):
                    offenders.append(
                        f"{path.relative_to(BUNDLED_DIR)}: references removed 'worker-base'"
                    )
                    break
        assert not offenders, (
            "Bundled assets reference removed 'worker-base' skill:\n"
            + "\n".join(offenders)
        )

    def test_validator_skill_refs_resolve(self) -> None:
        # Every `*-validator` skill name referenced in a bundled playbook must
        # exist as a real bundled skill. Project-authored worker skills (which
        # don't end in `-validator`) are exempt — those live in the user's
        # workspace, not the bundled tree.
        existing = _bundled_skill_names()
        offenders: list[str] = []
        for path in _bundled_text_files():
            text = path.read_text()
            for m in _SKILL_REF_RE.finditer(text):
                name = m.group("json") or m.group("prose")
                if name and name.endswith("-validator") and name not in existing:
                    offenders.append(
                        f"{path.relative_to(BUNDLED_DIR)}: '{name}' not in bundled skills"
                    )
        assert not offenders, (
            "Bundled playbook references unknown validator skills:\n"
            + "\n".join(offenders)
        )

    def test_assertion_ids_in_examples_are_valid(self) -> None:
        # `VAL-bench` etc. (lowercase tail) violates ASSERTION_ID_REGEX. Catch
        # invalid ids that appear inside `"targets": ["..."]` in example DAGs.
        targets_re = re.compile(r'"targets"\s*:\s*\[\s*([^\]]+?)\s*\]')
        id_re = re.compile(r'"([^"]+)"')
        offenders: list[str] = []
        for path in _bundled_md_files():
            text = path.read_text()
            for m in targets_re.finditer(text):
                for id_match in id_re.finditer(m.group(1)):
                    aid = id_match.group(1)
                    if not ASSERTION_ID_REGEX.fullmatch(aid):
                        offenders.append(
                            f"{path.relative_to(BUNDLED_DIR)}: invalid assertion id '{aid}'"
                        )
        assert not offenders, (
            "Bundled playbook examples contain invalid assertion ids:\n"
            + "\n".join(offenders)
        )
