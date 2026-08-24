# Changelog

All notable changes to `@structupath/pi-steel` are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0] - 2026-08-24

### Added

- Compaction-aware refill: verified true-shape compaction now runs inside
  the packing loop, not only after it. When a part fails to fit on every
  open plate, eligible plates that changed since their last attempt are
  compacted (behind the same independent verification gate) and the
  insertion is retried against the rebuilt free rectangles before a new
  sheet is opened or the part is stranded — so recovered plate becomes
  fewer purchased sheets and fewer `stock_exhausted` parts, never just a
  bigger remnant. Refilled parts keep full bounding-box clearance to
  everything on the plate, a rejected compaction permanently disqualifies
  that plate and packing proceeds exactly as the bounding-box flow would,
  and with compaction enabled a run never uses more plates or strands
  more parts than with it disabled. `compaction.recovered_in` and
  `compaction.passes` accumulate across attempts on the same plate; no
  schema changes.

## [0.5.0] - 2026-08-24

### Added

- Verified true-shape compaction for outlined irregular parts: after
  MaxRects bounding-box packing, placements slide left-then-down in
  fixed 1/32-in scan-to-first-contact steps until their true profiles
  (not their boxes) reach the kerf-plus-gap clearance, so complementary
  profiles interlock and recover plate. Every compacted plate is
  re-checked by an independent polygon-clearance verifier that rebuilds
  profiles from the published placement data alone; any failure discards
  compaction for that plate with a non-blocking `COMPACTION_REJECTED`
  finding and keeps the proven bounding-box layout. Plate reports record
  `compaction` (`ran`, `accepted`, `recovered_in`, `passes`), remnant
  candidates are rebuilt from the compacted bounding boxes (still
  rectangle-based and uncertified), and a `true_shape_utilization_pct`
  metric reports exact profile area on plates whose irregular parts all
  carry validated outlines. Enabled by default in the direct engine and
  the estimate pipeline; `--no-compact-outlines` opts out, and the choice
  is captured in the configuration hash. Burn-DXF eligibility and the
  review-required posture for irregular parts are unchanged.

## [0.4.0] - 2026-08-23

### Added

- True polygon outlines for irregular plate parts: an optional
  `geometry.outline` vertex list gives exact shoelace areas and weights
  (`outline_exact`, replacing hand-declared estimates), exact
  hole-inside-profile verification (a hole in a notch now blocks instead
  of passing the bounding-box check), and real profile rendering in
  layouts and reference DXFs. Outlines are validated as simple polygons
  whose bounding box matches the declared part size, at the canonical
  contract and in the direct nesting engine alike. Placement remains by
  bounding box and burn-DXF suppression for irregular parts is unchanged.

## [0.3.1] - 2026-08-23

### Added

- Bounded exact cut-list optimization: designation + grade groups with up
  to 12 pieces run a deterministic branch-and-bound search (seeded and
  bounded by the portfolio result, fixed node budget) that explores
  complete and partial placements alike and only ever replaces the greedy
  plan with a strictly better one — including stranding fewer members when
  finite stock cannot hold everything.
- `output-contract.md` documents the cut-list artifacts and
  `cutlist_partial` status; the estimate-package example now includes
  member items and vendor linear stock.

### Changed

- Ranking now minimizes purchase cost before purchased length when every
  stock entry in a group carries a known cost basis — buying cheaper beats
  buying shorter; groups without complete pricing keep the least-purchased-
  length objective.

## [0.3.0] - 2026-08-23

### Added

- **`steel-cutlist` skill** — deterministic 1D bar nesting for long products
  (beams, channels, angles, HSS, tube, pipe). Packs required member lengths
  onto purchasable mill lengths with explicit saw kerf and end-trim
  allowances, a documented fit contract, and a strategy portfolio per
  designation + grade group (mixed-stock greedy plus each single-stock-length
  restriction) ranked by fewest unplaced members, least total stock length,
  lowest known cost, then fewest bars.
- Independent post-placement cut-list verification (bar overcommitment,
  material mismatch, duplicate or missing member instances) gating
  publication; the per-bar `cutting_list.csv` is emitted only for verified,
  fully placed runs.
- Member weights from explicit `unit_weight_plf` or the bundled AISC shape
  database; unknown weights surface as warnings, never silent zeros.
- Bar diagrams (`layout.pdf`, `bars.png`), purchase summary by stock length,
  drop candidates against a reusable threshold, and a versioned
  `rfq_linear.json` handoff.
- **Pipeline integration** — `steel-estimate` now optimizes member items
  (designation + length, no plate geometry) onto configurable mill lengths
  (`--mill-lengths-ft`, default `40,50,60`; `--cutlist-kerf-in`,
  `--end-trim-in`, `--min-drop-in`). Cut-list blockers, verifier findings,
  and members longer than every mill length gate the run exactly like nest
  blockers, publishing `cutlist_partial` diagnostics.
- **RFQ integration** — the draft workbook renders a
  "LINEAR STOCK / CUT-LIST REFERENCE" section from a validated linear
  handoff; the standalone `generate-rfq.py` accepts `--linear` with schema
  and staleness validation against the estimate identity.
- `cutlist-result` schema (`1.0.0`) and the `cutlist_partial` /
  `cutlist_verified` package statuses.
- **Linear stock in the canonical contract** — `stock` entries with
  `stock_form: "linear"` model vendor-declared purchasable lengths and
  on-hand sticks. Declared purchasable lengths replace the default mill
  lengths for their designation + grade group; on-hand sticks require the
  same hash-bound reviewer confirmation as on-hand plate and enter the
  optimizer as finite, cost-free inventory. The portfolio ranks by
  purchased length first, so confirmed sticks reduce buying whenever they
  genuinely can, and purchase summaries, handoffs, and reports label
  `on_hand` rows explicitly.

## [0.2.3] - 2026-07-28

### Fixed

- Corrected shape dataset ownership metadata in the provenance record.

### Added

- Pi gallery preview image, public demo recording, and public project guide.

## [0.2.2] - 2026-07-28

### Added

- Trustworthy estimate package pipeline: canonical estimate contract and
  shared validation, grouped nest placement verification, deterministic draft
  RFQ compilation, review-gated orchestration with immutable manifested runs,
  and release gates for privacy and provenance.
- `steel-nest` plate nesting with guarded burn DXF output.

## [0.1.0] - 2026-07-19

### Added

- Initial release: `steel-takeoff` and `steel-rfq` skills for Pi.
