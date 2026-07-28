#!/usr/bin/env python3
"""Fail when public repository files contain known private-data indicators."""

from __future__ import annotations

import re
import subprocess
import sys
from bisect import bisect_left
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_SUFFIXES = {
    ".csv",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
ALLOWED_NAMES = {".gitignore", "LICENSE", "package.json"}
SKIP_PARTS = {".git", ".a5c", "__pycache__", "node_modules"}
SKIP_FILES = {Path("scripts/check-public-data.py")}
FORBIDDEN_BINARY_SUFFIXES = {
    ".doc",
    ".docx",
    ".dxf",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".xls",
    ".xlsx",
}
PATTERNS = {
    "private operating-company claim": re.compile(
        r"team behind (?:a|the) production structural[- ]steel", re.I
    ),
    "local absolute path": re.compile(r"(?:/Users/|/home/|[A-Z]:\\\\Users\\\\)"),
    "realistic sales-order identifier": re.compile(r"\bSO-\d{3,}\b", re.I),
    "current-market pricing claim": re.compile(r"\bcurrent (?:market )?rates?\b", re.I),
    "contact email": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    "phone number": re.compile(
        r"(?<!\d)(?:\+?1[-. ]?)?\(?[2-9]\d{2}\)?[-. ]\d{3}[-. ]\d{4}(?!\d)"
    ),
    "credential assignment": re.compile(
        r"\b(?:api[_-]?key|password|secret|token)\s*[:=]\s*[\"'][^\"']+[\"']", re.I
    ),
}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if line]


def main() -> int:
    findings: list[str] = []
    patterns = dict(PATTERNS)
    private_terms = ROOT / ".pi-steel" / "private-terms.txt"
    if private_terms.is_file():
        terms = [
            line.strip()
            for line in private_terms.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if terms:
            patterns["private local denylist term"] = re.compile(
                "|".join(re.escape(term) for term in sorted(terms, key=len, reverse=True)),
                re.I,
            )

    for path in tracked_files():
        relative = path.relative_to(ROOT)
        if (
            relative in SKIP_FILES
            or any(part in SKIP_PARTS for part in relative.parts)
            or not path.is_file()
        ):
            continue
        suffix = path.suffix.lower()
        if suffix in FORBIDDEN_BINARY_SUFFIXES:
            findings.append(f"{relative}: public repository must not contain {suffix} artifacts")
            continue
        if suffix not in ALLOWED_SUFFIXES and path.name not in ALLOWED_NAMES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        newline_offsets = [
            index for index, character in enumerate(text) if character == "\n"
        ]
        for label, pattern in patterns.items():
            for match in pattern.finditer(text):
                line = bisect_left(newline_offsets, match.start()) + 1
                findings.append(f"{relative}:{line}: {label}")

    if findings:
        print("Public-data check failed:", file=sys.stderr)
        for finding in findings:
            print(f"  - {finding}", file=sys.stderr)
        return 1

    print("Public-data check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
