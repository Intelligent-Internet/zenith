"""Codex ACP subprocess environment regression tests."""
from __future__ import annotations

import os
from pathlib import Path

from zenith_harness.acp_auth import ACPAuthContext
from zenith_harness.acp_runner import _acp_subprocess_env
from zenith_harness.providers import PROVIDERS


def test_claude_env_is_sanitized() -> None:
    env = _acp_subprocess_env(PROVIDERS["claude"])
    assert env.get("PATH", "") == os.environ.get("PATH", "")
    # Claude provider must NOT receive codex-specific hints.
    assert "CODEX_SANDBOX" not in env
    assert "CODEX_DISABLE_SANDBOX" not in env


def test_codex_preserves_path_when_bwrap_is_present(tmp_path: Path, monkeypatch) -> None:
    fake_bwrap_dir = tmp_path / "bwrap-bin"
    fake_bwrap_dir.mkdir()
    (fake_bwrap_dir / "bwrap").write_text("#!/bin/sh\nexit 0\n")
    (fake_bwrap_dir / "bwrap").chmod(0o755)

    other_dir = tmp_path / "other"
    other_dir.mkdir()
    (other_dir / "useful-tool").write_text("#!/bin/sh\nexit 0\n")
    (other_dir / "useful-tool").chmod(0o755)

    new_path = f"{fake_bwrap_dir}{os.pathsep}{other_dir}"
    monkeypatch.setenv("PATH", new_path)

    env = _acp_subprocess_env(
        PROVIDERS["codex"],
        ACPAuthContext(mode="subscription", codex_home=tmp_path / "codex-home"),
    )
    parts = env["PATH"].split(os.pathsep)
    assert str(fake_bwrap_dir) in parts
    assert str(other_dir) in parts


def test_codex_with_no_bwrap_on_path_unchanged(monkeypatch, tmp_path: Path) -> None:
    only_other = tmp_path / "other"
    only_other.mkdir()
    monkeypatch.setenv("PATH", str(only_other))
    env = _acp_subprocess_env(
        PROVIDERS["codex"],
        ACPAuthContext(mode="subscription", codex_home=tmp_path / "codex-home"),
    )
    assert env["PATH"] == str(only_other)


def test_codex_does_not_set_sandbox_bypass_hints(tmp_path: Path) -> None:
    env = _acp_subprocess_env(
        PROVIDERS["codex"],
        ACPAuthContext(mode="subscription", codex_home=tmp_path / "codex-home"),
    )
    assert "CODEX_SANDBOX" not in env
    assert "CODEX_DISABLE_SANDBOX" not in env
