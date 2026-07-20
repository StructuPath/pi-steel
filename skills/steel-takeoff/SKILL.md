---
name: steel-takeoff
description: >
  Structural steel takeoff, AISC member lookup, and quantity estimating.
  Use when performing steel takeoffs, reading structural prints/blueprints,
  looking up AISC member properties (W-shapes, HSS, angles, channels, pipe),
  building bills of materials (BOM), calculating steel tonnage, or preparing
  steel bid packages. Keywords: steel, takeoff, BOM, AISC, W-shape, HSS,
  angle, channel, weight, tonnage, structural, estimating, blueprint,
  quantity survey, beam, column, brace, connection, erection, ironwork.
license: MIT
compatibility: Requires jq and python3. macOS or Linux.
metadata:
  domain: structural-steel
  version: "1.0.0"
  aisc-edition: "16th"
  shapes-count: "400+"
allowed-tools: Bash Read Edit Write
---

# Steel Takeoff Skill

Structural steel quantity takeoff and AISC member data lookup using the 16th Edition shapes database.

## Setup (run once per machine)

```bash
cd "$(dirname "$0")"
chmod +x scripts/*.sh
python3 -c "import json, csv, sys" || echo "ERROR: python3 required"
command -v jq >/dev/null || echo "ERROR: install jq (brew install jq / apt install jq)"
```

## Quick Reference: AISC Member Lookup

Look up any AISC shape's full property set:

```bash
# Single member lookup — returns all properties
./scripts/lookup-member.sh "W14X30"

# Search for W-shapes by minimum moment of inertia
jq '[.[] | select(.type == "W" and .Ix >= 800)] | sort_by(.weight_per_ft) | .[:5]' assets/aisc-shapes-database.json

# Find lightest W-shape with depth >= 18" and Ix >= 1000 in⁴
jq '[.[] | select(.type == "W" and .d >= 18 and .Ix >= 1000)] | sort_by(.weight_per_ft) | .[0]' assets/aisc-shapes-database.json

# List all HSS rectangular shapes
jq '[.[] | select(.type == "HSS-RECT")] | sort_by(.weight_per_ft)' assets/aisc-shapes-database.json

# Find angles with leg >= 4"
jq '[.[] | select(.type == "L" and .d >= 4)]' assets/aisc-shapes-database.json

# Find channels by weight range
jq '[.[] | select(.type == "C" and .weight_per_ft >= 15 and .weight_per_ft <= 30)]' assets/aisc-shapes-database.json
```

## Takeoff Procedure

### Step 1 — Parse Drawings
Read the structural drawings and extract:
- Member marks (e.g., B1, B2, C1, G1, BR1)
- Member sizes (e.g., W14X30, HSS6X6X1/4, L4X4X3/8)
- Lengths (from grid dimensions or explicit call-outs, use feet-inches: 28'-6")
- Quantities (count per mark — check symmetry, typical bays, similar conditions)
- Connection types at each end

### Step 2 — Build the BOM
For each unique member mark, create a line item:

```bash
cat assets/bom-template.csv
```

Fields: Mark, Qty, Size, Grade, Length_ft, Unit_Wt_plf, Total_Wt_lbs, Connections, Notes

### Step 3 — Look Up Unit Weights
For every member size in the BOM, look up the unit weight from the AISC database:

```bash
./scripts/lookup-member.sh "W14X30"
# Output: W14X30 | 30.0 plf | d=13.84" | bf=6.730" | A=8.85 in² | Ix=291 in⁴ | Sx=42.0 in³

./scripts/lookup-member.sh "HSS8X6X1/2"
# Output: HSS8X6X1/2 | 42.1 plf | d=8.00" | b=6.00" | A=11.7 in² | Ix=96.4 in⁴
```

### Step 4 — Calculate Totals

```bash
# From a BOM CSV file
./scripts/calculate-weight.sh path/to/bom.csv

# Output includes:
#   Per-line weights
#   Total weight in lbs and tons
#   Connection allowance (12%)
#   Misc steel allowance (5%)
#   Grand total with estimated cost
```

### Step 5 — Add Connections & Misc Steel
See [connection types reference](references/connection-types.md) for standard connection weights.

Rules of thumb for connection allowance:
| Building Type | Connection % |
|---|---|
| Simple warehouse / pre-eng | 8-10% |
| Standard commercial | 10-12% |
| Moment frames / complex | 12-18% |
| Heavy industrial / power | 15-20% |

### Step 6 — Validate

```bash
python3 scripts/validate-bom.py path/to/bom.csv
# Checks:
#   ✓ Valid AISC designations
#   ✓ Non-zero quantities and lengths
#   ✓ Correct grade for shape type
#   ✓ Reasonable weight-per-foot values
#   ✓ No duplicate marks
```

## Material Grades Quick Reference

| Grade | Typical Use | Fy (ksi) | Fu (ksi) |
|---|---|---|---|
| A992 | W-shapes (default) | 50 | 65 |
| A500 Gr. B | HSS round | 42 | 58 |
| A500 Gr. C | HSS rectangular | 50 | 62 |
| A36 | Angles, channels, plates | 36 | 58 |
| A572 Gr. 50 | Plates, built-ups | 50 | 65 |
| A913 Gr. 50/65 | Jumbo shapes | 50/65 | 65/80 |
| A514 | High-strength plates | 100 | 110-130 |
| A588 | Weathering steel | 50 | 70 |

Full grade specs: `cat assets/material-grades.json`

## Bolt Reference

| Bolt Type | Grade | Tensile (ksi) | Shear (ksi) | Common Sizes |
|---|---|---|---|---|
| A325 / F1852 (TC) | — | 120 | 54/68 | 3/4", 7/8", 1" |
| A490 / F2280 (TC) | — | 150 | 68/84 | 3/4", 7/8", 1" |
| A307 | Gr. A | 60 | 24 | 1/2" - 1" |

- N = threads in shear plane (lower capacity)
- X = threads excluded (higher capacity)
- SC = slip-critical (higher bolt pretension required)

## Detailed References

For in-depth guidance on specific topics:
- [AISC Shapes Guide](references/aisc-shapes-guide.md) — all shape families, property definitions, selection guidance
- [Takeoff Procedures](references/takeoff-procedures.md) — detailed step-by-step with worked examples
- [Connection Types](references/connection-types.md) — standard connection details, hardware weights, bolt patterns
