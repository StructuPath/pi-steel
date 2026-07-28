#!/usr/bin/env python3
"""Validate a legacy BOM through the canonical estimate-package contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SHARED_ROOT = Path(__file__).resolve().parents[2] / "_shared"
if str(SHARED_ROOT) not in sys.path:
    sys.path.insert(0, str(SHARED_ROOT))
from bootstrap import bootstrap_shared  # noqa: E402

bootstrap_shared(__file__)
from pi_steel.parsing import adapt_legacy_bom_csv  # noqa: E402
from pi_steel.validation import validate_estimate_package  # noqa: E402


def load_shapes_db() -> dict[str, dict]:
    db_path = Path(__file__).resolve().parent.parent / "assets" / "aisc-shapes-database.json"
    if not db_path.exists():
        return {}
    shapes = json.loads(db_path.read_text(encoding="utf-8"))
    return {shape["designation"]: shape for shape in shapes}


def normalize_designation(raw: str) -> str:
    return raw.upper().replace(" ", "").strip()


def grade_warnings(shape_type: str, grade: str) -> list[str]:
    normalized = grade.upper().replace(" ", "").replace(".", "")
    expected = {
        "W": ("A992", "A572", "A913", "A36"),
        "HSS-RECT": ("A500", "A500GRC"),
        "HSS-RND": ("A500", "A500GRB", "A53"),
        "C": ("A36", "A572"),
        "L": ("A36", "A572"),
        "PIPE": ("A53", "A500"),
    }.get(shape_type, ())
    if expected and not any(normalized.startswith(value) for value in expected):
        return [f"Grade {grade!r} is unusual for shape type {shape_type}."]
    return []


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("bom", type=Path)
    result.add_argument(
        "--project-id",
        default="SYNTHETIC-UNSPECIFIED",
        help="Stable project identity used to derive canonical item IDs.",
    )
    result.add_argument(
        "--revision-id",
        default="SYNTHETIC-REV-UNSPECIFIED",
        help="Source revision identity used to derive canonical item IDs.",
    )
    result.add_argument(
        "--json",
        action="store_true",
        help="Print the validation result as JSON.",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not args.bom.is_file():
        print(f"ERROR: File not found: {args.bom}", file=sys.stderr)
        return 1
    try:
        package = adapt_legacy_bom_csv(
            args.bom,
            project_id=args.project_id,
            revision_id=args.revision_id,
        )
    except (OSError, ValueError, TypeError) as exc:
        print(f"ERROR: Could not parse BOM: {exc}", file=sys.stderr)
        return 1

    result = validate_estimate_package(package)
    findings = list(result.active_findings)
    shapes = load_shapes_db()
    for index, item in enumerate(package["items"]):
        designation = normalize_designation(item.get("designation", ""))
        shape = shapes.get(designation)
        if designation and shapes and shape is None and not designation.startswith(
            ("PL", "PLATE", "BU", "WT")
        ):
            findings.append(
                {
                    "finding_id": f"legacy-shape:{index}",
                    "code": "unverified_designation",
                    "severity": "warning",
                    "path": f"$.items[{index}].designation",
                    "message": f"{item.get('designation')!r} was not found in the bundled reference data.",
                    "relevant_hash": result.input_hash,
                }
            )
        elif shape is not None:
            unit_weight = item.get("unit_weight_plf")
            if unit_weight and abs(unit_weight - shape["weight_per_ft"]) > 0.5:
                findings.append(
                    {
                        "finding_id": f"legacy-weight:{index}",
                        "code": "unit_weight_mismatch",
                        "severity": "warning",
                        "path": f"$.items[{index}].unit_weight_plf",
                        "message": (
                            f"Unit weight {unit_weight:g} plf does not match the "
                            f"bundled reference value {shape['weight_per_ft']:g} plf."
                        ),
                        "relevant_hash": result.input_hash,
                    }
                )
            for message in grade_warnings(shape["type"], item.get("grade", "")):
                findings.append(
                    {
                        "finding_id": f"legacy-grade:{index}",
                        "code": "unusual_grade",
                        "severity": "warning",
                        "path": f"$.items[{index}].grade",
                        "message": message,
                        "relevant_hash": result.input_hash,
                    }
                )
        if item.get("length_ft", 0) > 80:
            findings.append(
                {
                    "finding_id": f"legacy-length:{index}",
                    "code": "unusual_member_length",
                    "severity": "warning",
                    "path": f"$.items[{index}].length_ft",
                    "message": "Member length exceeds 80 ft; verify the source.",
                    "relevant_hash": result.input_hash,
                }
            )

    total_weight = sum(
        item["quantity"] * item.get("length_ft", 0) * item.get("unit_weight_plf", 0)
        for item in package["items"]
        if item.get("intent") == "fabricated_part"
    )
    blockers = [finding for finding in findings if finding["severity"] == "blocker"]
    warnings = [finding for finding in findings if finding["severity"] == "warning"]
    output = {
        "status": "invalid" if blockers else ("review_required" if warnings else "validated"),
        "input_hash": result.input_hash,
        "line_count": len(package["items"]),
        "total_weight_lbs": total_weight,
        "findings": findings,
    }
    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        print(f"BOM VALIDATION: {args.bom.name}")
        for finding in findings:
            label = "ERROR" if finding["severity"] == "blocker" else finding["severity"].upper()
            print(f"{label}: {finding['path']}: {finding['message']}")
        print(
            f"SUMMARY: {len(package['items'])} lines; "
            f"{total_weight:,.0f} lb; {len(blockers)} blockers; {len(warnings)} warnings"
        )
        print(f"STATUS: {output['status']}")
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
