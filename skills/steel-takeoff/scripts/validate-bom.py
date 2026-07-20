#!/usr/bin/env python3
"""
BOM Validator — Validates a steel bill of materials CSV.

Usage: python3 scripts/validate-bom.py path/to/bom.csv

Checks:
  ✓ Valid AISC designations (cross-references shapes database)
  ✓ Non-zero quantities and lengths
  ✓ Correct grade for shape type
  ✓ Reasonable weight-per-foot values
  ✓ No duplicate marks
  ✓ Required columns present
"""

import csv
import json
import os
import sys
from pathlib import Path

def load_shapes_db():
    """Load the AISC shapes database."""
    skill_dir = Path(__file__).resolve().parent.parent
    db_path = skill_dir / "assets" / "aisc-shapes-database.json"
    if not db_path.exists():
        print(f"WARNING: Shapes database not found at {db_path}")
        return {}

    with open(db_path) as f:
        shapes = json.load(f)

    return {s["designation"]: s for s in shapes}


def normalize_designation(raw: str) -> str:
    """Normalize a steel designation for lookup."""
    return raw.upper().replace(" ", "").strip()


def validate_grade(shape_type: str, grade: str) -> list[str]:
    """Check if the material grade is appropriate for the shape type."""
    warnings = []
    grade_upper = grade.upper().strip()

    # Standard grade assignments
    standard_grades = {
        "W":        ["A992", "A572", "A913", "A36"],
        "HSS-RECT": ["A500", "A500 GR.C", "A500 GR. C", "A500GRC", "A500C"],
        "HSS-RND":  ["A500", "A500 GR.B", "A500 GR. B", "A500GRB", "A500B", "A53"],
        "C":        ["A36", "A572"],
        "L":        ["A36", "A572"],
        "PIPE":     ["A53", "A53 GR.B", "A53B", "A500"],
    }

    if shape_type in standard_grades:
        valid = standard_grades[shape_type]
        # Check if grade matches any valid option
        matches = any(
            grade_upper.replace(" ", "").replace(".", "").startswith(v.replace(" ", "").replace(".", ""))
            for v in valid
        )
        if not matches:
            warnings.append(
                f"Grade '{grade}' unusual for {shape_type} — "
                f"expected one of: {', '.join(standard_grades[shape_type][:3])}"
            )

    return warnings


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 validate-bom.py <bom.csv>")
        sys.exit(1)

    bom_file = sys.argv[1]
    if not os.path.exists(bom_file):
        print(f"ERROR: File not found: {bom_file}")
        sys.exit(1)

    shapes_db = load_shapes_db()
    errors = []
    warnings = []
    marks_seen = {}
    total_weight = 0
    line_num = 0

    required_columns = {"Mark", "Qty", "Size", "Length_ft", "Unit_Wt_plf"}

    print(f"\n{'='*60}")
    print(f"  BOM VALIDATION: {os.path.basename(bom_file)}")
    print(f"{'='*60}\n")

    with open(bom_file) as f:
        reader = csv.DictReader(f)

        # Check required columns
        if reader.fieldnames:
            actual_cols = set(reader.fieldnames)
            missing_cols = required_columns - actual_cols
            if missing_cols:
                errors.append(f"Missing required columns: {', '.join(missing_cols)}")

        for row in reader:
            line_num += 1
            mark = row.get("Mark", "").strip()
            if not mark or mark.startswith("#"):
                continue

            size = row.get("Size", "").strip()
            grade = row.get("Grade", "").strip()
            qty_str = row.get("Qty", "0").strip()
            length_str = row.get("Length_ft", "0").strip()
            unit_wt_str = row.get("Unit_Wt_plf", "0").strip()

            prefix = f"Line {line_num} ({mark})"

            # Check for duplicate marks
            if mark in marks_seen:
                warnings.append(f"{prefix}: Duplicate mark (also on line {marks_seen[mark]})")
            marks_seen[mark] = line_num

            # Validate quantity
            try:
                qty = int(qty_str) if qty_str else 0
                if qty <= 0:
                    errors.append(f"{prefix}: Quantity is {qty} — must be > 0")
            except ValueError:
                errors.append(f"{prefix}: Invalid quantity '{qty_str}'")
                qty = 0

            # Validate length
            try:
                if "'" in length_str:
                    parts = length_str.replace('"', '').split("'")
                    feet = float(parts[0].replace('-', '').strip())
                    inches = float(parts[1].replace('-', '').strip()) if len(parts) > 1 and parts[1].strip() else 0
                    length = feet + inches / 12.0
                else:
                    length = float(length_str) if length_str else 0
                if length <= 0:
                    errors.append(f"{prefix}: Length is {length} — must be > 0")
                elif length > 80:
                    warnings.append(f"{prefix}: Length {length:.1f} ft exceeds typical max (80 ft) — verify")
            except ValueError:
                errors.append(f"{prefix}: Invalid length '{length_str}'")
                length = 0

            # Validate unit weight
            try:
                unit_wt = float(unit_wt_str) if unit_wt_str else 0
                if unit_wt <= 0:
                    errors.append(f"{prefix}: Unit weight is {unit_wt} — must be > 0")
            except ValueError:
                errors.append(f"{prefix}: Invalid unit weight '{unit_wt_str}'")
                unit_wt = 0

            # Validate AISC designation
            normalized = normalize_designation(size)
            if shapes_db:
                if normalized in shapes_db:
                    db_shape = shapes_db[normalized]
                    db_wt = db_shape["weight_per_ft"]
                    if unit_wt > 0 and abs(unit_wt - db_wt) > 0.5:
                        warnings.append(
                            f"{prefix}: Unit weight {unit_wt} plf doesn't match "
                            f"AISC database ({db_wt} plf) for {size}"
                        )
                    # Validate grade
                    if grade:
                        grade_warns = validate_grade(db_shape["type"], grade)
                        warnings.extend(f"{prefix}: {w}" for w in grade_warns)
                else:
                    # Not a fatal error — could be a plate or built-up section
                    if not any(normalized.startswith(p) for p in ["PL", "PLATE", "BU", "WT"]):
                        warnings.append(f"{prefix}: '{size}' not found in AISC database — verify designation")

            # Validate grade is present
            if not grade:
                warnings.append(f"{prefix}: No material grade specified")

            total_weight += qty * length * unit_wt

    # Print results
    if errors:
        print("  ❌ ERRORS (must fix):")
        for e in errors:
            print(f"     • {e}")
        print()

    if warnings:
        print("  ⚠️  WARNINGS (review):")
        for w in warnings:
            print(f"     • {w}")
        print()

    print(f"  📊 SUMMARY:")
    print(f"     Lines validated:  {line_num}")
    print(f"     Unique marks:    {len(marks_seen)}")
    print(f"     Errors:          {len(errors)}")
    print(f"     Warnings:        {len(warnings)}")
    print(f"     Total weight:    {total_weight:,.0f} lbs ({total_weight/2000:,.1f} tons)")

    if errors:
        print(f"\n  ❌ VALIDATION FAILED — {len(errors)} error(s) found")
        print(f"{'='*60}\n")
        sys.exit(1)
    elif warnings:
        print(f"\n  ⚠️  PASSED WITH WARNINGS — review {len(warnings)} warning(s)")
        print(f"{'='*60}\n")
    else:
        print(f"\n  ✅ VALIDATION PASSED — no issues found")
        print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
