# Estimate package output contract

Each invocation publishes an immutable directory at `runs/<run-id>/` and
updates `latest-run.json` only after the run is complete. Read the manifest
before using any artifact.

## Core artifacts

| Artifact | Purpose | Produced when |
| --- | --- | --- |
| `estimate-package.json` | Deterministically ordered canonical input | Always |
| `normalized-bom.json` | Typed BOM and calculated weight projection | Always |
| `nest-result.json` | Placements, verification, utilization, and unplaced parts | Valid input contains plate parts |
| `rfq-nesting.json` | Versioned nesting lineage for RFQ compilation | A nest was attempted |
| `inventory-consumption.json` | Confirmed on-hand sheets consumed and corresponding RFQ demand reduction | Eligible on-hand inventory was consumed |
| `qa-report.json` | Findings, approximations, gate decisions, and recalculation status | Always |
| `run-manifest.json` | Input/configuration hashes and artifact hashes/readiness | Always |
| `<project>_RFQ_Material_List.xlsx` | Draft RFQ workbook | All blocking gates pass |
| `workbook-semantic.json` | Stable workbook content projection | Workbook exists |

Rendered PDF, PNG, and DXF files are optional. Reference artifacts are not
fabrication authority. Burn DXF is eligible only for a fully ready run with
verified exact geometry.

## Outcomes

- `ready` / `rfq_ready_for_review`: all gates pass; the workbook is still a
  draft requiring human review.
- `review_required` / `rfq_draft_review_required`: a workbook exists, but
  warnings or reference-only geometry must be resolved or accepted by a human.
- `blocked`: diagnostics exist, but no workbook exists.
- `dependency_missing`: required rendering support is absent and no workbook
  exists.

Unplaced parts use `blocked` with package status `nested_partial`; their nest
diagnostics remain available. A validation failure stops before nesting.

## Determinism and lineage

Canonical JSON is sorted before publication. The manifest records the canonical
input hash, effective configuration hash, tool/schema versions, explicit dates,
and SHA-256 for each artifact. Run IDs and filesystem paths are volatile and do
not affect the semantic hash. A changed revision, quantity, profile, date, or
nest setting changes the applicable downstream lineage.

Never treat warnings, approximations, exclusions, allowances, or source
evidence as presentation-only metadata. They are part of the review contract.
