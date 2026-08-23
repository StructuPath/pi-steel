# Changelog

All notable changes to `@structupath/pi-steel` are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
