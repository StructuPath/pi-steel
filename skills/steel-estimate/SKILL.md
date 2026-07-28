---
name: steel-estimate
description: "Build a deterministic, review-gated steel estimate package from canonical estimate JSON. Use when a complete takeoff-to-nest-to-draft-RFQ workflow is needed with validation, lineage, QA, and isolated run artifacts."
---

# Steel Estimate Package

## Boundary

This skill produces estimating and draft purchasing artifacts for human review.
It does not send an RFQ, select a vendor, approve substitutions, award work, or
authorize a purchase. The workbook remains `DRAFT — NOT SENT OR AWARDED`.

## Required inputs

- Canonical estimate-package JSON at schema version `1.0.0`.
- Explicit prepared and RFQ issue dates.
- A runtime company profile accepted by `steel-rfq`.
- Plate stock compatible with every plate part by material, grade, thickness,
  and usable dimensions.

Use `references/estimate-package-example.json` as a synthetic input example.
The company profile resolution and approval rules are documented by
`../steel-rfq/SKILL.md`.

## Workflow and gates

The orchestrator composes the shared estimate validator, deterministic nesting
engine, RFQ compiler, and run publisher. It does not duplicate their
calculations.

1. Normalize and validate the canonical package.
2. Build the typed BOM projection without converting exclusions or allowances
   into vendor quantities.
3. Nest plate parts only within compatible stock groups.
4. Verify placements and retain diagnostic nest artifacts.
5. Compile a draft RFQ only when validation, placement, and company-profile
   gates pass.
6. Publish an isolated run manifest and QA report.

Validation failures, unplaced parts, invalid company data, failed nest
verification, or required rendering dependencies block workbook generation.
Complete bounding-box nests for irregular geometry may produce a workbook, but
the run and workbook remain explicitly review-required. Reference DXF is never
burn-ready DXF.

## Run

```bash
python3 scripts/build-estimate-package.py \
  --input <estimate-package.json> \
  --out <publication-root> \
  --prepared-date <YYYY-MM-DD> \
  --issued-date <YYYY-MM-DD> \
  --project-location "Example City, ST"
```

Use `--no-render` when only JSON and workbook artifacts are needed. Use
`--no-bake` to defer formula calculation to spreadsheet open. Explicit dates
and unchanged input/configuration yield stable semantic artifacts.

Exit codes:

- `0`: package is ready for human RFQ review.
- `2`: a draft exists, but warnings or reference-only geometry require review.
- `3`: blocked; diagnostics are published and no workbook is produced.
- `4`: a required runtime dependency is missing; no workbook is produced.
- `1`: usage, file, or input parsing error.

See `references/output-contract.md` for artifact and status semantics.

## Delivery checks

- Read `run-manifest.json` and `qa-report.json`; do not infer readiness from a
  workbook filename.
- Confirm there are no blocker findings or unplaced parts.
- Confirm material, grade, thickness, source IDs, and replacement lineage.
- Surface every warning and approximation to the reviewer.
- Treat all workbook and rendered artifacts according to their manifest
  readiness labels.
