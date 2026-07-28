# Synthetic Workflow Fixtures

These fixtures were created from scratch to test pi-steel's public workflow. They
are not copied, transformed, rounded, renamed, or anonymized from production,
customer, vendor, bid, drawing, takeoff, inventory, or RFQ data.

| Fixture | Synthetic family | Purpose |
|---|---|---|
| `member_only.csv` | Mixed W-shape and HSS member takeoff | Exercises supported member validation and weight calculation. |
| `mixed_plate_job.json` | Rectangular and unresolved irregular plate parts | Exercises reference-only geometry and approximation propagation. |
| `blocked_plate_job.json` | Part larger than finite stock | Exercises unplaced-part diagnostics and the missing process-level stop contract. |
| `ambiguous_scope.csv` | Member rows with ambiguous scope and purchasing intent | Proves that current CSV validation cannot determine scope or purchase relationships. |

The fixtures deliberately contain:

- different section families and material grades;
- member and plate workflows;
- explicit synthetic scope text;
- both complete and blocked nesting cases;
- no company identity, contact details, pricing, commercial terms, or real project
  identifiers.

No fixture establishes CAM compatibility. A named CAM product/version may be added
only with a separate, recorded import acceptance check using synthetic geometry.

## Provenance

- Creator: StructuPath pi-steel maintainers
- Creation method: deliberately invented values and geometry
- Public-data review: 2026-07-28
- Private source artifacts: none
- Release approval: required through the repository public-data check
