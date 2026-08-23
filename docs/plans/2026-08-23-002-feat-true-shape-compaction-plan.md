---
title: "feat: True-Shape Compaction for Outlined Irregular Parts"
type: feat
date: 2026-08-23
---

# feat: True-Shape Compaction for Outlined Irregular Parts

## Summary

Make v0.5 the first placement-quality milestone for irregular geometry. Parts
that carry a validated polygon outline (added in v0.4.0) still occupy their
full bounding box during placement, so real yield is understated and layouts
waste plate. This plan adds a deterministic post-placement compaction pass
that slides outlined parts along fixed axes until their true profiles reach
the required clearance, plus an independent true-shape clearance verifier
that gates every compacted layout. Placement claims only improve when the
verifier proves them.

---

## Problem Frame

v0.4.0 gave irregular parts exact areas, exact hole checks, and true profile
rendering, but the MaxRects packer still reserves the whole bounding box.
Two L-shaped gussets whose profiles could interlock are laid out as if they
were rectangles, so sheets-needed and remnant candidates are pessimistic.
Full no-fit-polygon nesting is a dedicated CAM engine and remains out of
scope; the tractable, verifiable step is compaction: keep the proven
bounding-box packing as the starting layout, then recover space by sliding
parts toward the plate origin while their outlines (not their boxes) respect
kerf-plus-gap clearance.

The safety posture must not weaken. A compaction bug that overlaps two parts
would be worse than the pessimism it fixes, so the compacted layout is only
published when an independent polygon-clearance verifier — sharing no code
path with the compactor — proves every pairwise profile distance and plate
containment. Any verification failure discards compaction for that plate and
keeps the original bounding-box layout.

---

## Requirements

### Safety and verification

- R1. Compaction must never move a part such that any two true profiles come
  closer than kerf plus part gap, or any profile crosses the usable-area
  boundary; rectangles keep their exact-footprint guarantees.
- R2. An independent verifier must recheck every compacted plate using only
  published placement data: pairwise minimum polygon distance, plate bounds,
  and hole containment. A failed check discards compaction for that plate
  and records a finding; it never blocks the run that the uncompacted layout
  would have passed.
- R3. Burn-DXF eligibility rules are unchanged: any irregular part still
  suppresses burn output and holds the run at review_required.
- R4. Determinism: identical input must produce identical compacted layouts;
  no randomized restarts or time-dependent iteration.

### Reporting honesty

- R5. Metrics must distinguish the packing basis: bounding-box packing
  utilization stays as-is, and a new true-shape utilization is reported only
  for plates where every irregular part has a validated outline.
- R6. Remnant candidates remain rectangle-based and unverified; compaction
  may enlarge them but must not claim certified reusable stock.
- R7. The result must record per-plate whether compaction ran, how much slide
  distance it recovered, and whether the verifier accepted it.

---

## Design

### Polygon clearance primitives (shared `geometry_verify`)

- `polygon_min_distance(a, b)` — exact minimum distance between two simple
  polygons via pairwise segment distance, with an early exit when bounding
  boxes are farther apart than the current minimum. Zero when boundaries
  touch or interiors overlap (overlap detected by any vertex containment or
  edge intersection).
- `polygon_within_rect(outline, width, height)` — containment of a profile
  in the usable area.
- Rectangles participate as their four-corner polygons so mixed plates are
  handled uniformly.

### Compaction pass (in `nest.py`, after MaxRects placement)

Deterministic left-then-down sliding, one plate at a time:

1. Order placements by (x, y, placement_id).
2. For each placement, slide leftward (then downward) by scanning fixed
   1/32 in steps from the current position and stopping one step before the
   first offset where the profile violates `kerf + gap` clearance against
   any already-fixed profile or the usable boundary. Clearance along a
   slide is NOT monotonic for concave profiles (a notch can make an offset
   clear, then blocked, then clear again), so binary search is unsound
   here; the slide is a continuous motion, and the first blocking step is
   the physical stop. Step count is bounded by plate size over resolution,
   keeping the pass deterministic.
3. Repeat the sweep until a pass moves nothing (bounded iteration count).

U2's fixtures must include a concave alternating-clearance case — a
profile whose slide path is clear, blocked by a notch neighbor, then clear
again — proving the scan stops at the first contact rather than tunneling
to a later clear interval.

Only plates where every irregular part carries a validated outline are
eligible; mixed plates with outline-less irregular parts keep the
bounding-box layout untouched.

### Verification and gating

`verify_true_shape_placements(plate)` runs after compaction with the same
clearance contract as the rectangular verifier. Acceptance replaces the
plate's placements and recomputes plate metrics; rejection restores the
original placements, adds a `COMPACTION_REJECTED` warning finding, and the
run proceeds exactly as v0.4.0 would have.

### Result contract additions

- Plate report: `compaction: {ran, accepted, recovered_in, passes}`.
- Metrics: `true_shape_utilization_pct` with approximation label, present
  only when R5's condition holds.
- Nest-result schema additions are additive; schema version stays 1.0.0.

---

## Units of Work

- U1. Polygon distance and containment primitives with exhaustive unit tests
  (touching, overlapping, nested, translated-apart cases).
- U2. Compaction pass behind a `--compact-outlines` flag defaulting off in
  the direct engine and pipeline until U3 lands; deterministic-layout tests.
- U3. Independent true-shape verifier plus the discard-on-failure gate;
  adversarial tests that corrupt a compacted layout and prove rejection.
- U4. Metrics, plate-report contract, schema, renderer updates (compacted
  outlines drawn at their new positions), SKILL.md and README boundaries.
- U5. Flip the default on with a recorded before/after fixture comparison
  demonstrating recovered plate area, then release as v0.5.0.

## Non-Goals

- No-fit-polygon or free-rotation true-shape nesting.
- Any change to burn-DXF eligibility for irregular parts.
- Curved (arc/spline) outline segments; outlines remain polygonal.
- Remnant certification.
