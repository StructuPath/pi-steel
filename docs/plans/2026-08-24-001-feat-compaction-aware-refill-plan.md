---
title: "feat: Compaction-Aware Refill — Recovered Plate Becomes Fewer Sheets"
type: feat
date: 2026-08-24
---

# feat: Compaction-Aware Refill — Recovered Plate Becomes Fewer Sheets

## Summary

v0.5.0's verified true-shape compaction recovers plate area, but it runs
after every part has already been assigned to a plate, so the recovered
space never changes what the shop buys: sheet count and stranded parts are
decided by the bounding-box packing alone. This plan interleaves the
existing verified compaction into the packing loop — when a part fails to
fit on every open plate, eligible plates are compacted and the insertion is
retried before a new sheet is opened or the part is declared unplaced. The
compactor, the independent verifier, the discard-on-failure gate, and every
safety posture from v0.5.0 are reused unchanged; the only new behavior is
that recovered space is offered back to the packer.

---

## Problem Frame

Today `run_job` packs every unit, then compacts each eligible plate once.
Two consequences:

- A part that almost fit opens a fresh plate (or strands as
  `stock_exhausted`) even when compacting an existing plate would have made
  room for it.
- The recovered space only enlarges remnant candidates; utilization
  improves on paper while the purchase list stays pessimistic.

The refill must not weaken v0.5.0's guarantees. Space freed by compaction
is only ever offered through the rebuilt MaxRects free rectangles — which
are computed by subtracting every compacted part's bounding box plus
spacing — so a refilled part keeps at least the kerf-plus-gap clearance to
every existing bounding box, and therefore to every true profile. The
independent true-shape verifier still gates each compaction, and the final
result-level verification is unchanged.

---

## Requirements

- R1. Safety identical to v0.5.0: every compaction is gated by
  `verify_true_shape_placements`; a rejected compaction restores the plate,
  records the `COMPACTION_REJECTED` warning, permanently disqualifies that
  plate from further compaction in the run, and packing proceeds exactly as
  it would have without the attempt.
- R2. Refill placements go only into rebuilt free rectangles, preserving
  the bounding-box clearance invariant between any refilled part and every
  other part on the plate.
- R3. Never worse: with compaction enabled, the run uses at most as many
  plates and strands at most as many parts as the v0.5.0 flow would.
  (Compacting before opening a plate can only add placement options.)
- R4. Determinism: identical input produces identical output; compaction
  attempts are triggered by deterministic events (a failed insertion with a
  dirty eligible plate), never by heuristics with hidden state.
- R5. Bounded work: a plate is re-compacted only when it has received new
  placements since its last compaction (dirty flag), so each plate is
  compacted at most once per placement wave, and the existing pass/step
  bounds apply to each attempt.
- R6. Contract stability: no schema changes. `compaction.recovered_in` and
  `compaction.passes` accumulate across attempts on the same plate;
  `ran`/`accepted` reflect whether any attempt ran and whether the plate's
  current layout comes from an accepted compaction. Burn-DXF eligibility,
  review posture, metrics definitions, and hashes behave as in v0.5.0
  (the algorithm version string is bumped, which reaches the configuration
  hash as before).

## Design

In `run_job`'s placement loop, when a unit fails to insert into every
compatible open plate:

1. Collect compatible plates that are compaction-eligible (their irregular
   parts all outlined), not disqualified by a prior rejection, and dirty
   (new placements since their last accepted compaction).
2. For each such plate in index order: run `compact_placements`, gate with
   the independent verifier (accept → rebuild free rectangles, clear dirty,
   accumulate `recovered_in`/`passes`; reject → restore, warn, disqualify),
   then retry the unit's insertion.
3. Only if the unit still does not fit anywhere: open a new plate as
   before; only if that fails too: mark it unplaced.

Any successful insertion marks its plate dirty. After the placement loop,
the v0.5.0 end-of-run compaction still runs once for dirty, qualified
plates, so the final layouts are as tight as before.

## Units of Work

- U1. Extract the compact-verify-gate block into a helper shared by the
  mid-pack and end-of-run paths; add dirty/disqualified plate state.
- U2. Interleave refill into the placement loop per the design; keep the
  end-of-run pass.
- U3. Tests: a job where refill avoids opening a second sheet (plate count
  drops versus `--no-compact-outlines`); a job where a `stock_exhausted`
  part becomes placed (blocked → review_required); rejection mid-pack falls
  back to the v0.5.0 outcome; determinism; never-worse comparison against
  the flag-off run for every fixture.
- U4. Docs (SKILL.md, README, CHANGELOG), algorithm version bump, release
  v0.6.0.

## Non-Goals

- Moving already-placed parts between plates, or re-ordering the unit
  queue based on compaction outcomes.
- True-shape-aware initial placement (skyline/profile packing) and
  no-fit-polygon nesting.
- Any change to remnant certification, burn eligibility, or the verifier.
