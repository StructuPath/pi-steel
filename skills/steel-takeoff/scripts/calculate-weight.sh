#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Steel Weight Calculator
# Usage: ./scripts/calculate-weight.sh path/to/bom.csv [connection_pct] [misc_pct]
#
# BOM CSV format:
#   Mark,Qty,Size,Grade,Length_ft,Unit_Wt_plf,Total_Wt_lbs,Connections,Notes
#
# Optional arguments:
#   connection_pct  - Connection allowance percentage (default: 12)
#   misc_pct        - Misc steel allowance percentage (default: 5)
#
# Output: Line-by-line breakdown + totals with cost estimate
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

if [ $# -eq 0 ]; then
    echo "Usage: $0 <bom.csv> [connection_pct] [misc_pct]"
    echo ""
    echo "  bom.csv         CSV file with columns: Mark,Qty,Size,Grade,Length_ft,Unit_Wt_plf,..."
    echo "  connection_pct  Connection hardware allowance (default: 12%)"
    echo "  misc_pct        Misc steel allowance (default: 5%)"
    echo ""
    echo "Example:"
    echo "  $0 takeoff.csv 15 5"
    exit 1
fi

BOM_FILE="$1"
CONN_PCT="${2:-12}"
MISC_PCT="${3:-5}"

if [ ! -f "$BOM_FILE" ]; then
    echo "ERROR: File not found: $BOM_FILE"
    exit 1
fi

python3 - "$BOM_FILE" "$CONN_PCT" "$MISC_PCT" <<'PYTHON'
import csv
import sys
import os

bom_file = sys.argv[1]
conn_pct = float(sys.argv[2]) / 100.0
misc_pct = float(sys.argv[3]) / 100.0

print(f"\n{'='*78}")
print(f"  STEEL TAKEOFF — WEIGHT CALCULATION")
print(f"  File: {os.path.basename(bom_file)}")
print(f"{'='*78}\n")

# Header
print(f"  {'Mark':<8} {'Qty':>4} x {'Size':<14} x {'Length':>9} @ {'Wt/ft':>8} = {'Total':>12}  {'Grade':<8}")
print(f"  {'-'*8} {'-'*4}   {'-'*14}   {'-'*9}   {'-'*8}   {'-'*12}  {'-'*8}")

total_lbs = 0
total_pieces = 0
categories = {}
grade_totals = {}
line_count = 0

with open(bom_file) as f:
    reader = csv.DictReader(f)
    for row in reader:
        mark = row.get("Mark", "").strip()
        if not mark or mark.startswith("#"):
            continue

        qty = int(row.get("Qty", 0))
        size = row.get("Size", "?").strip()
        grade = row.get("Grade", "A992").strip()
        length_str = row.get("Length_ft", "0").strip()
        unit_wt_str = row.get("Unit_Wt_plf", "0").strip()

        # Parse length — support both decimal (28.5) and feet-inches (28'-6")
        if "'" in length_str:
            parts = length_str.replace('"', '').split("'")
            feet = float(parts[0].replace('-', '').strip())
            inches = float(parts[1].replace('-', '').strip()) if len(parts) > 1 and parts[1].strip() else 0
            length = feet + inches / 12.0
        else:
            length = float(length_str) if length_str else 0

        unit_wt = float(unit_wt_str) if unit_wt_str else 0

        line_wt = qty * length * unit_wt
        total_lbs += line_wt
        total_pieces += qty
        line_count += 1

        # Categorize by prefix
        if size.startswith("W"):
            cat = "W-Shapes"
        elif size.startswith("HSS"):
            cat = "HSS"
        elif size.startswith("L"):
            cat = "Angles"
        elif size.startswith("C") or size.startswith("MC"):
            cat = "Channels"
        elif size.startswith("PIPE"):
            cat = "Pipe"
        elif size.startswith("PL") or size.startswith("PLATE"):
            cat = "Plates"
        else:
            cat = "Other"

        categories[cat] = categories.get(cat, 0) + line_wt
        grade_totals[grade] = grade_totals.get(grade, 0) + line_wt

        print(f"  {mark:<8} {qty:>4} x {size:<14} x {length:>7.1f} ft @ {unit_wt:>6.1f} plf = {line_wt:>10,.0f} lb  {grade:<8}")

# Connection & misc allowances
conn_wt = total_lbs * conn_pct
misc_wt = total_lbs * misc_pct
grand_total = total_lbs + conn_wt + misc_wt

print(f"\n  {'='*78}")
print(f"\n  CATEGORY BREAKDOWN:")
for cat in sorted(categories.keys()):
    wt = categories[cat]
    pct = (wt / total_lbs * 100) if total_lbs > 0 else 0
    print(f"    {cat:<20} {wt:>12,.0f} lb  ({pct:>5.1f}%)")

print(f"\n  GRADE BREAKDOWN:")
for grade in sorted(grade_totals.keys()):
    wt = grade_totals[grade]
    pct = (wt / total_lbs * 100) if total_lbs > 0 else 0
    print(f"    {grade:<20} {wt:>12,.0f} lb  ({pct:>5.1f}%)")

print(f"\n  {'─'*60}")
print(f"  {'Members:':<30} {line_count:>8} marks")
print(f"  {'Total Pieces:':<30} {total_pieces:>8} pcs")
print(f"  {'Member Weight:':<30} {total_lbs:>12,.0f} lb  ({total_lbs/2000:>8,.1f} tons)")
print(f"  {'Connection Allow ({:.0f}%):':<30} {conn_wt:>12,.0f} lb  ({conn_wt/2000:>8,.1f} tons)".format(conn_pct*100))
print(f"  {'Misc Steel Allow ({:.0f}%):':<30} {misc_wt:>12,.0f} lb  ({misc_wt/2000:>8,.1f} tons)".format(misc_pct*100))
print(f"  {'─'*60}")
print(f"  {'GRAND TOTAL:':<30} {grand_total:>12,.0f} lb  ({grand_total/2000:>8,.1f} tons)")
print(f"  {'─'*60}")

# Cost estimates at various $/ton rates
print(f"\n  COST ESTIMATES:")
tons = grand_total / 2000
for rate in [2800, 3200, 3600, 4000]:
    cost = tons * rate
    print(f"    @ ${rate:,}/ton:  ${cost:>14,.0f}")

print(f"\n{'='*78}\n")
PYTHON
