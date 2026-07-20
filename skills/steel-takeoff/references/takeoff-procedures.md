# Steel Takeoff Procedures — Detailed Guide

## Overview

A steel takeoff quantifies every piece of structural steel on a project to determine total tonnage for bidding. Accuracy directly impacts profit margin — a 5% error on a 200-ton job is 10 tons ($32,000+ at current rates).

## Takeoff Order (recommended)

1. **Columns** — Start at foundations, work up
2. **Girders** — Primary spanning members (grid-to-grid)
3. **Beams** — Secondary members (between girders)
4. **Bracing** — Vertical and horizontal
5. **Joists & Joist Girders** — If in scope (often separate trade)
6. **Miscellaneous Steel** — Lintels, embeds, loose angles, stair framing
7. **Connections** — Percentage allowance based on complexity

## Step-by-Step Procedure

### 1. Gather Documents
- Structural plans (S sheets)
- Structural details (SD sheets)
- General notes and specifications
- Architectural drawings (for clearances, finishes)
- Addenda and bulletins
- Geotechnical report (for pile/foundation type)

### 2. Read General Notes FIRST
General notes override everything. Look for:
- Steel grade specifications (may differ from standard)
- Coating/painting requirements
- Fireproofing requirements (affects schedule, not weight)
- Special inspection requirements (affects cost)
- Fabrication standards (AISC certification level)
- Erection procedures or sequences
- Design loads (helps verify member sizes)

### 3. Mark Up the Drawings
Use colored pencils/markers on prints (or layers in PDF):
- **Red** — Columns
- **Blue** — Beams/Girders
- **Green** — Bracing
- **Orange** — Misc steel
- **Yellow highlight** — Items already counted

### 4. Column Takeoff

For each column mark:
```
Mark | Qty | Size | Grade | Length (TOS to TOS) | Splice? | Base Plate
C1   | 8   | W14X48 | A992 | 14'-6" (FTG to 2nd) | No | 18"x18"x1"
C1a  | 8   | W14X48 | A992 | 14'-0" (2nd to Roof) | Yes | N/A
```

**Length rules:**
- Foundation to first floor: Top of base plate to TOS
- Floor to floor: TOS to TOS (top of steel)
- Top column: TOS to TOS at roof

**Watch for:**
- Column splices (add splice plate weight)
- Cap plates at top
- Stepped columns (different sizes at different levels)
- Cantilevered columns (verify fixed vs. pinned base)

### 5. Beam/Girder Takeoff

```
Mark | Qty | Size | Grade | Length | Camber | Studs | Connections
B1   | 12  | W16X26 | A992 | 28'-6" | None | (24) 3/4"x4-1/2" | 2x shear tab
G1   | 6   | W24X76 | A992 | 36'-0" | 3/4" | (56) 3/4"x4-1/2" | 2x moment
```

**Length determination:**
- Grid line to grid line MINUS column setbacks
- Add for overhang/cantilever past column face
- If not dimensioned, scale from drawings (note as "SCALED")

**Watch for:**
- Camber requirements (affects fabrication cost)
- Composite design (shear studs — count them)
- Coped beams (note "COPE TOP" or "COPE BOT")
- Moment vs. shear connections (different hardware)
- Typical bays — count ALL typical bays, don't assume

### 6. Bracing Takeoff

```
Mark | Qty | Size | Grade | Length | Connection
BR1  | 8   | HSS6X6X3/8 | A500C | 18'-9" (diag) | Gusset both ends
BR2  | 4   | L4X4X3/8 | A36 | 12'-4" (diag) | Clip angle
```

**Length:** Use diagonal length, not horizontal projection:
```
Diagonal = √(horizontal² + vertical²)
Example: 24'-0" horizontal, 14'-0" vertical
Diagonal = √(24² + 14²) = √(576 + 196) = √772 = 27.78' → 27'-9"
```

### 7. Miscellaneous Steel

These items are easy to miss but add up:
- **Lintels** — Over CMU openings (angles, typically L4X4, L5X3-1/2)
- **Embed plates** — In concrete for attachments
- **Loose angles** — Shelf angles, relief angles, ledger angles
- **Kicker angles** — Diagonal braces for masonry/curtain wall support
- **Sag rods** — Between purlins
- **Stair framing** — Stringers (C10, C12), landing beams, toe plates
- **Handrail posts** — Pipe or HSS posts
- **Safety cable anchors** — Roof perimeter life safety

### 8. Verify Completeness

Checklist:
- [ ] All grid intersections have a column
- [ ] Every bay has beams spanning both directions
- [ ] Bracing is shown at required locations (check all elevations)
- [ ] Stair/elevator framing accounted for
- [ ] Opening framing (headers, trimmers) included
- [ ] Roof framing matches roof plan
- [ ] Mezzanine/platform framing included
- [ ] Equipment support steel included
- [ ] Canopy/awning framing included

## Common Takeoff Errors

| Error | Impact | How to Avoid |
|---|---|---|
| Missed symmetry | Under by 50% | Check "SIM OPP HAND" notes |
| Wrong bay count | Under/over 10-20% | Count every bay, mark on plan |
| Forgot elevation change | Wrong lengths | Cross-ref plans with sections |
| Didn't count connections | Under 10-15% | Always add connection allowance |
| Scaled instead of calculated | ±5-10% error | Calculate from grid dimensions |
| Missed addendum | Variable | Always read ALL addenda |
| Wrong grade assumed | Cost impact | Read general notes for grade specs |
| Forgot misc steel | Under 3-8% | Use the misc steel checklist above |

## Output Format

Final takeoff should be organized by:

### Level 1: By Drawing Sheet
```
Sheet S-101: Foundation Plan
  C1 - 8ea W14X48 @ 14'-6" = 5,568 lbs
  ...
Sheet subtotal: XX,XXX lbs
```

### Level 2: By Category
```
Columns:    XX,XXX lbs (XX.X tons)
Beams:      XX,XXX lbs (XX.X tons)
Girders:    XX,XXX lbs (XX.X tons)
Bracing:    XX,XXX lbs (XX.X tons)
Misc:       XX,XXX lbs (XX.X tons)
Connection: XX,XXX lbs (XX.X tons) — X% allowance
```

### Level 3: Grand Total
```
TOTAL: XXX,XXX lbs = XX.X tons
```
