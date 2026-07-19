from __future__ import annotations

import subprocess
from pathlib import Path

from . import __version__
from .models import RuntimeIdentity


def detect_runtime_identity(source_file: str | Path = __file__) -> RuntimeIdentity:
    """Return package version plus git identity when running from a checkout."""
    source = Path(source_file).resolve()
    root = next((parent for parent in source.parents if (parent / ".git").exists()), None)
    if root is None:
        return RuntimeIdentity(version=__version__)

    commit = _git(root, "rev-parse", "HEAD")
    status = _git(root, "status", "--porcelain", "--untracked-files=no")
    return RuntimeIdentity(
        version=__version__,
        git_commit=commit or None,
        git_dirty=bool(status) if status is not None else None,
        source_root=str(root),
    )


def _git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


__all__ = ["detect_runtime_identity"]
