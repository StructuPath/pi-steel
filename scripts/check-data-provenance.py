#!/usr/bin/env python3
"""Verify shipped shape data and enforce its public-release decision."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROVENANCE_PATH = ROOT / "DATA_PROVENANCE.md"
PROVENANCE_RECORD_PATH = ROOT / "DATA_PROVENANCE.json"


def audit() -> dict:
    errors: list[str] = []
    record = json.loads(PROVENANCE_RECORD_PATH.read_text(encoding="utf-8"))
    datasets = record.get("datasets", [])
    if len(datasets) != 1:
        errors.append("expected exactly one declared shipped dataset")
        dataset = {}
    else:
        dataset = datasets[0]
    shapes_path = ROOT / dataset.get("shipped_file", "")
    raw = shapes_path.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    if checksum != dataset.get("sha256"):
        errors.append("shape data checksum differs from DATA_PROVENANCE.json")

    rows = json.loads(raw)
    expected_rows = dataset.get("rows")
    if not isinstance(rows, list) or len(rows) != expected_rows:
        errors.append(f"expected {expected_rows} shape rows")
        rows = rows if isinstance(rows, list) else []

    required_fields = set(dataset.get("required_fields", []))
    designations: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"shape row {index} is not an object")
            continue
        missing = required_fields - row.keys()
        if missing:
            errors.append(f"shape row {index} is missing {sorted(missing)}")
        designation = row.get("designation")
        if isinstance(designation, str):
            designations.append(designation)

    if len(designations) != len(set(designations)):
        errors.append("shape designations are not unique")

    provenance = PROVENANCE_PATH.read_text(encoding="utf-8")
    permission = dataset.get("redistribution_permission")
    release_readiness = dataset.get("release_readiness")
    release_blocked = permission == "unverified" and release_readiness == "blocked"
    documented_values = (
        dataset.get("claimed_edition"),
        str(expected_rows),
        dataset.get("sha256"),
        "Redistribution permission | Unverified",
    )
    if not all(value and value in provenance for value in documented_values):
        errors.append("DATA_PROVENANCE.md differs from the machine-readable record")

    return {
        "schema_version": "1.0.0",
        "integrity": "passed" if not errors else "failed",
        "claimed_edition": dataset.get("claimed_edition"),
        "release_readiness": release_readiness,
        "redistribution_permission": permission,
        "shape_rows": len(rows),
        "sha256": checksum,
        "errors": errors,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release",
        action="store_true",
        help="fail while redistribution permission is unresolved",
    )
    args = parser.parse_args(argv)
    report = audit()
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["errors"]:
        return 1
    if args.release and report["release_readiness"] != "ready":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
