"""Relocatable import bootstrap for scripts shipped inside the npm package."""

from __future__ import annotations

import sys
from pathlib import Path


class BootstrapError(RuntimeError):
    """Raised when an entry point cannot locate the shipped skills tree."""


def find_skills_root(entry_file: str | Path) -> Path:
    """Find ``skills/`` relative to an entry point, without using the cwd."""
    entry = Path(entry_file).resolve()
    for parent in entry.parents:
        if parent.name == "skills" and (parent / "_shared").is_dir():
            return parent
        candidate = parent / "skills"
        if (candidate / "_shared").is_dir():
            return candidate
    raise BootstrapError(f"cannot locate the shipped skills directory from {entry.name}")


def bootstrap_shared(entry_file: str | Path) -> Path:
    """Put the shipped shared module directory on ``sys.path`` and return skills root."""
    skills_root = find_skills_root(entry_file)
    shared_root = skills_root / "_shared"
    shared_text = str(shared_root)
    if shared_text not in sys.path:
        sys.path.insert(0, shared_text)
    return skills_root
