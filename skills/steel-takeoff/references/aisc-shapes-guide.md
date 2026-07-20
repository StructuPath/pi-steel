# AISC Shapes Guide — 16th Edition

## Shape Families

### W-Shapes (Wide Flange)
- **Designation**: WdXw (e.g., W14X30 = 14" nominal depth, 30 plf)
- **Grade**: A992 (Fy=50 ksi) — default for all W-shapes
- **Range**: W4X13 to W44X335 (standard) up to W14X730 (jumbo column)
- **Use**: Beams, columns, girders — the workhorse of structural steel
- **Key Properties**: d, bf, tf, tw, A, Ix, Sx, Iy, Sy, Zx, Zy, ry

**Common Beam Sizes**: W8, W10, W12, W14, W16, W18, W21, W24, W27, W30, W33, W36
**Common Column Sizes**: W10, W12, W14 (wide flange series with bf ≈ d)

### S-Shapes (American Standard)
- **Designation**: SdXw (e.g., S12X35)
- **Grade**: A36 (Fy=36 ksi)
- **Note**: Rarely specified in new construction. Replaced by W-shapes.

### HP-Shapes (Bearing Piles)
- **Designation**: HPdXw (e.g., HP14X73)
- **Grade**: A572 Gr. 50 or A36
- **Use**: Driven piles, foundation support
- **Key Feature**: Approximately equal flange width and depth (bf ≈ d)

### C-Shapes (American Standard Channels)
- **Designation**: CdXw (e.g., C10X20)
- **Grade**: A36 (Fy=36 ksi)
- **Use**: Struts, framing, edge members, stair stringers
- **Key Properties**: Shear center is NOT at the centroid — beware of lateral-torsional effects

### MC-Shapes (Miscellaneous Channels)
- **Designation**: MCdXw (e.g., MC8X22.8)
- **Grade**: A36
- **Use**: Similar to C-shapes but non-standard proportions

### L-Shapes (Angles)
- **Designation**: LaxbXt (e.g., L4X4X3/8)
  - Equal leg: L4X4X3/8 (4" x 4" x 3/8" thick)
  - Unequal leg: L6X4X1/2 (6" x 4" x 1/2" thick)
- **Grade**: A36 (Fy=36 ksi)
- **Use**: Bracing, struts, lintels, clip angles, connections
- **Key Feature**: Properties about geometric axes AND principal axes differ

### WT-Shapes (Structural Tees)
- **Designation**: WTdXw (e.g., WT7X15)
- **Grade**: A992 (same as parent W-shape)
- **Note**: Cut from W-shapes — WT7X15 is half of W14X30

### HSS — Rectangular / Square
- **Designation**: HSSaxbXt (e.g., HSS8X6X1/2 = 8" x 6" x 1/2" wall)
- **Grade**: A500 Gr. C (Fy=50 ksi) for rectangular/square
- **Use**: Columns, bracing, truss members, exposed applications
- **Key Feature**: Excellent for compression (no weak axis). Clean appearance.
- **Wall thickness**: Nominal vs. design — design thickness = 0.93 × nominal

### HSS — Round
- **Designation**: HSSd.dXt (e.g., HSS6.625X0.280)
- **Grade**: A500 Gr. C (Fy=42 ksi for round)
- **Use**: Columns, bracing, handrails, pipe bollards
- **Note**: Round HSS Fy is LOWER than rectangular HSS

### Pipe
- **Designation**: PIPEdXtype (e.g., PIPE6STD, PIPE6XS, PIPE6XXS)
  - STD = Standard wall
  - XS = Extra Strong
  - XXS = Double Extra Strong
- **Grade**: A53 Gr. B (Fy=35 ksi)
- **Use**: Columns, bollards, handrails, process structures

## Property Definitions

| Symbol | Property | Units | What It Means |
|--------|----------|-------|---------------|
| d | Depth | in | Overall depth of section |
| bf | Flange width | in | Width of flange (W, C shapes) |
| tf | Flange thickness | in | Thickness of flange |
| tw | Web thickness | in | Thickness of web |
| A | Area | in² | Cross-sectional area — used for axial capacity |
| Ix | Moment of inertia (x) | in⁴ | Stiffness about strong axis — controls deflection |
| Sx | Section modulus (x) | in³ | Bending capacity about strong axis |
| Iy | Moment of inertia (y) | in⁴ | Stiffness about weak axis |
| Sy | Section modulus (y) | in³ | Bending capacity about weak axis |
| Zx | Plastic section modulus (x) | in³ | Full plastic bending capacity (strong axis) |
| Zy | Plastic section modulus (y) | in³ | Full plastic bending capacity (weak axis) |
| rx | Radius of gyration (x) | in | Column buckling parameter (strong axis) |
| ry | Radius of gyration (y) | in | Column buckling parameter (weak axis) — controls column capacity |
| J | Torsional constant | in⁴ | Resistance to twisting |
| Cw | Warping constant | in⁶ | Warping resistance |

## Selection Tips for Takeoff

1. **Beams**: Higher Ix = less deflection. Sx controls bending strength. Deeper beams are more efficient but check clearances.
2. **Columns**: ry controls capacity (weak axis buckles first). W14 column series (W14X48 to W14X730) have bf ≈ d for balanced buckling.
3. **Bracing**: HSS members are excellent — high r values in both directions. Angles are cheaper but less efficient.
4. **Weight**: Always verify unit weight from database. Never estimate — the difference between W14X30 (30 plf) and W14X34 (34 plf) is 13% more steel.
