---
name: steel-rfq
description: "Compile a deterministic draft steel RFQ workbook from a validated canonical estimate package or an exact-header legacy workbook. Use for material quote lists, RFQ spreadsheets, or versioned nesting references. Produces artifacts only; it never sends, awards, or authorizes purchasing."
---

# Steel RFQ Compiler

## Boundary

This skill creates a reviewable draft workbook. It does not contact vendors,
send RFQs, select a quote, approve substitutions, award work, or authorize a
purchase. Every workbook and manifest records `DRAFT — NOT SENT OR AWARDED`.

## Required inputs

- Canonical estimate-package JSON `1.0.0`, or the conservative exact-header
  legacy XLSX contract in `references/rfq-input.md`.
- Explicit issue date.
- A runtime company profile with company name, city/state, and an approved,
  hash-bound terms template.
- Optional versioned nesting handoff `1.0.0`.

Resolve the company profile from `PI_STEEL_CONFIG`, project-local ignored
`.pi-steel/company-profile.json`, then the platform user-config directory.
Never write runtime identity, terms, or logos into this installed skill.

The shipped `assets/company-profile.example.json` is deliberately unapproved.
Copy it to a runtime config location, supply reviewed terms and approval
metadata, recompute the exact UTF-8 SHA-256, then change status to `approved`.

## Deterministic scope and purchasing rules

- Canonical `intent` controls scope. Description text cannot exclude an item.
- `allowance`, `exclusion`, and `by_others` never become vendor quantities.
- Zero quantity in the legacy adapter maps to excluded scope.
- Consolidated purchased stock replaces fabricated pieces only through explicit
  `dimensions.replaces_item_ids`.
- Lines remain traceable by source and item ID.
- Groups and nesting references remain separate by material, grade, thickness,
  size, and stock identity.
- Missing identity, approved terms, supported versions, or valid input blocks
  workbook generation.

## Workbook contract

The compiler owns:

- `RFQ Draft` and hidden `RFQ Metadata` sheets.
- Dark-blue title block, fillable vendor block, fixed A:N headers, grouped
  purchase lines, yellow vendor-response cells, formulas, borders, widths, and
  alternating row fills.
- Exact total formulas covering the deterministic material range.
- Versioned nesting/remnant reference rows with visible reference-only labels.
- Approved terms content and approval lineage.
- Landscape print setup, one-page width, repeated row-8 headers, and stable
  project-derived filename.

A missing optional logo falls back to the text header and does not invent
branding.

## Run

```bash
python3 scripts/generate-rfq.py \
  --input <estimate-package.json-or-exact-legacy.xlsx> \
  --nest <optional-rfq_nesting.json> \
  --issued-date <YYYY-MM-DD> \
  --project-location "Example City, ST" \
  --out <publication-root>
```

Each invocation publishes an isolated run with `run-manifest.json`,
`qa-report.json`, the draft `.xlsx` when gates pass, and
`workbook-semantic.json`.

Exit codes:

- `0`: draft RFQ ready for human review.
- `2`: draft generated with review-required warnings or reference-only nesting.
- `3`: blocked; diagnostics only, no workbook.
- `1`: usage or internal input error.

## Formula calculation status

The compiler always requests full recalculation on open. If LibreOffice is
available and succeeds, QA says `baked_via_libreoffice`. Otherwise QA says
`deferred_recalculate_on_open`; it never claims cached formula values were
computed.

## Verification before delivery

- Confirm the manifest outcome and artifact allow-list.
- Confirm workbook metadata remains draft-only.
- Confirm every purchase line is traceable and typed in scope.
- Confirm totals formulas span the intended material rows.
- Confirm nesting rows preserve material/grade/thickness/size boundaries.
- Report deferred formula caching and reference-only nesting visibly.
