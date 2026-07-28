#!/usr/bin/env python3
"""Fail when public repository files contain known private-data indicators."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from bisect import bisect_left
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
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
SENSITIVE_SUFFIXES = {".key", ".p12", ".pem", ".pfx"}
PRIVATE_KEY_NAMES = {
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "private-key",
    "private_key",
}
AUDITED_PUBLIC_BINARY_SHA256 = {
    Path("docs/assets/pi-steel-demo.gif"):
        "ae6ad7286fc5f1eca31e960d4ac4414b7a32a566b975ddacc7d662824c34d91c",
    Path("docs/assets/pi-steel-gallery.webp"):
        "9d8f2b1dedb00fa6c53c78f4578a12225f84bded4f7bbabe33182486372d12a8",
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
        r"\b(?:api[_-]?key|password|secret|token)\s*[:=]\s*"
        r"(?:[\"'][^\"'\r\n]+[\"']|[^\s#;,]+)",
        re.I,
    ),
    "private key material": re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    "AWS access key identifier": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "GitHub access token": re.compile(
        r"\b(?:gh[opusr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{22,255})\b"
    ),
    "OpenAI API key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
}


def is_audited_public_binary(relative: Path, content: bytes) -> bool:
    expected = AUDITED_PUBLIC_BINARY_SHA256.get(relative)
    return expected is not None and hashlib.sha256(content).hexdigest() == expected


def tracked_files(root: Path = ROOT) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return [root / line for line in result.stdout.splitlines() if line]
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and not any(part in SKIP_PARTS for part in path.parts)
    ]


def scan_patterns(root: Path = ROOT) -> dict[str, re.Pattern[str]]:
    patterns = dict(PATTERNS)
    private_terms = root / ".pi-steel" / "private-terms.txt"
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
    return patterns


def sensitive_path_reason(relative: Path) -> str | None:
    name = relative.name.lower()
    if name == ".env" or name.startswith(".env."):
        return "sensitive environment file"
    if relative.suffix.lower() in SENSITIVE_SUFFIXES:
        return "sensitive key or certificate file"
    if name in PRIVATE_KEY_NAMES:
        return "private key file"
    return None


def scan_paths(
    paths: list[Path],
    *,
    root: Path = ROOT,
    patterns: dict[str, re.Pattern[str]] | None = None,
) -> list[str]:
    findings: list[str] = []
    active_patterns = scan_patterns(root) if patterns is None else patterns
    for path in paths:
        relative = path.relative_to(root)
        if (
            relative in SKIP_FILES
            or any(part in SKIP_PARTS for part in relative.parts)
            or not path.is_file()
        ):
            continue
        sensitive_reason = sensitive_path_reason(relative)
        if sensitive_reason:
            findings.append(f"{relative}: {sensitive_reason}")
            continue
        suffix = path.suffix.lower()
        if suffix in FORBIDDEN_BINARY_SUFFIXES:
            findings.append(f"{relative}: public repository must not contain {suffix} artifacts")
            continue
        content = path.read_bytes()
        if is_audited_public_binary(relative, content):
            continue
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            findings.append(f"{relative}: unknown binary file")
            continue
        if "\x00" in text:
            findings.append(f"{relative}: unknown binary file")
            continue
        newline_offsets = [
            index for index, character in enumerate(text) if character == "\n"
        ]
        for label, pattern in active_patterns.items():
            for match in pattern.finditer(text):
                line = bisect_left(newline_offsets, match.start()) + 1
                findings.append(f"{relative}:{line}: {label}")
    return findings


def _scan_bytes(
    relative: Path,
    content: bytes,
    *,
    patterns: dict[str, re.Pattern[str]],
    prefix: str = "",
) -> list[str]:
    if relative in SKIP_FILES or any(part in SKIP_PARTS for part in relative.parts):
        return []
    sensitive_reason = sensitive_path_reason(relative)
    if sensitive_reason:
        return [f"{prefix}{relative}: {sensitive_reason}"]
    suffix = relative.suffix.lower()
    if suffix in FORBIDDEN_BINARY_SUFFIXES:
        return [
            f"{prefix}{relative}: public repository must not contain {suffix} artifacts"
        ]
    if is_audited_public_binary(relative, content):
        return []
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return [f"{prefix}{relative}: unknown binary file"]
    if "\x00" in text:
        return [f"{prefix}{relative}: unknown binary file"]

    findings: list[str] = []
    newline_offsets = [
        index for index, character in enumerate(text) if character == "\n"
    ]
    for label, pattern in patterns.items():
        for match in pattern.finditer(text):
            line = bisect_left(newline_offsets, match.start()) + 1
            findings.append(f"{prefix}{relative}:{line}: {label}")
    return findings


def staged_findings(
    root: Path = ROOT,
    *,
    patterns: dict[str, re.Pattern[str]] | None = None,
) -> list[str]:
    """Scan the exact stage-zero blobs that would be included in the next commit."""
    changed = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if changed.returncode != 0:
        return []

    active_patterns = scan_patterns(root) if patterns is None else patterns
    findings: list[str] = []
    blob_cache: dict[str, bytes] = {}
    for raw_path in changed.stdout.split(b"\0"):
        if not raw_path:
            continue
        relative = Path(raw_path.decode("utf-8", errors="surrogateescape"))
        index_entry = subprocess.run(
            ["git", "ls-files", "--stage", "-z", "--", str(relative)],
            cwd=root,
            check=False,
            capture_output=True,
        )
        entries = [entry for entry in index_entry.stdout.split(b"\0") if entry]
        stage_zero = [
            entry for entry in entries if entry.split(b"\t", 1)[0].endswith(b" 0")
        ]
        if not stage_zero:
            continue
        metadata, _ = stage_zero[0].split(b"\t", 1)
        _, object_id, _ = metadata.decode("ascii").split()
        if object_id not in blob_cache:
            blob = subprocess.run(
                ["git", "cat-file", "blob", object_id],
                cwd=root,
                check=False,
                capture_output=True,
            )
            if blob.returncode != 0:
                continue
            blob_cache[object_id] = blob.stdout
        findings.extend(
            _scan_bytes(
                relative,
                blob_cache[object_id],
                patterns=active_patterns,
                prefix="staged ",
            )
        )
    return findings


def revision_findings(
    revision_args: list[str],
    root: Path = ROOT,
    *,
    patterns: dict[str, re.Pattern[str]] | None = None,
) -> list[str]:
    """Scan committed blobs reachable from the supplied ``git rev-list`` arguments."""
    commits = subprocess.run(
        ["git", "rev-list", *revision_args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if commits.returncode != 0:
        raise ValueError(commits.stderr.strip() or "invalid Git revision")

    active_patterns = scan_patterns(root) if patterns is None else patterns
    findings: list[str] = []
    blob_cache: dict[str, bytes] = {}
    scanned: set[tuple[str, Path]] = set()
    for commit in commits.stdout.splitlines():
        tree = subprocess.run(
            ["git", "ls-tree", "-r", "-z", commit],
            cwd=root,
            check=False,
            capture_output=True,
        )
        if tree.returncode != 0:
            continue
        for entry in tree.stdout.split(b"\0"):
            if not entry:
                continue
            metadata, raw_path = entry.split(b"\t", 1)
            _, object_type, object_id = metadata.decode("ascii").split()
            if object_type != "blob":
                continue
            relative = Path(raw_path.decode("utf-8", errors="surrogateescape"))
            identity = (object_id, relative)
            if identity in scanned:
                continue
            scanned.add(identity)
            if object_id not in blob_cache:
                blob = subprocess.run(
                    ["git", "cat-file", "blob", object_id],
                    cwd=root,
                    check=False,
                    capture_output=True,
                )
                if blob.returncode != 0:
                    continue
                blob_cache[object_id] = blob.stdout
            findings.extend(
                _scan_bytes(
                    relative,
                    blob_cache[object_id],
                    patterns=active_patterns,
                    prefix=f"commit {commit[:12]} ",
                )
            )
    return findings


def revision_metadata_findings(
    revision_args: list[str],
    root: Path = ROOT,
) -> list[str]:
    """Report non-noreply author addresses without exposing the address itself."""
    commits = subprocess.run(
        ["git", "log", "--format=%H%x00%ae", *revision_args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if commits.returncode != 0:
        raise ValueError(commits.stderr.strip() or "invalid Git revision")

    findings: list[str] = []
    seen_addresses: set[str] = set()
    for entry in commits.stdout.splitlines():
        if "\0" not in entry:
            continue
        commit, address = entry.split("\0", 1)
        normalized = address.strip().lower()
        if (
            not normalized
            or normalized in seen_addresses
            or normalized.endswith("@users.noreply.github.com")
        ):
            continue
        seen_addresses.add(normalized)
        findings.append(
            f"commit {commit[:12]} author metadata: non-noreply email address"
        )
    return findings


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check public repository content without printing matched values."
    )
    revisions = parser.add_mutually_exclusive_group()
    revisions.add_argument(
        "--history",
        action="store_true",
        help="also scan every commit reachable from every local ref",
    )
    revisions.add_argument(
        "--range",
        metavar="REVISION_RANGE",
        help="also scan commits selected by a git rev-list revision range",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    findings = scan_paths(tracked_files(), root=ROOT)
    findings.extend(staged_findings(ROOT))
    if args.history:
        findings.extend(revision_findings(["--all"], ROOT))
        findings.extend(revision_metadata_findings(["--all"], ROOT))
    elif args.range:
        try:
            findings.extend(revision_findings([args.range], ROOT))
            findings.extend(revision_metadata_findings([args.range], ROOT))
        except ValueError as error:
            print(f"Public-data check could not scan revisions: {error}", file=sys.stderr)
            return 2
    findings = list(dict.fromkeys(findings))

    if findings:
        print("Public-data check failed:", file=sys.stderr)
        for finding in findings:
            print(f"  - {finding}", file=sys.stderr)
        return 1

    print("Public-data check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
