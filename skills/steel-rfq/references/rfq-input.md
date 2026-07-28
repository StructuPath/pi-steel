# RFQ compiler input contract

The deterministic compiler accepts either:

1. A canonical estimate package at schema version `1.0.0`.
2. A legacy `.xlsx` workbook with a sheet named exactly `Steel Takeoff` and
   these exact row-1 headers:

   `Source_ID`, `Item_ID`, `Scope`, `Description`, `Material`, `Grade`,
   `Thickness`, `Size`, `Qty`, `Currency`, `Purchase Weight`.

The legacy adapter is intentionally narrow. `Scope` must be exactly `IN SCOPE`,
`BY OTHERS`, or `EXCLUDED`; descriptions never control scope. Missing stable
IDs, renamed columns, inferred section headers, and ambiguous quantities are
rejected for explicit mapping outside the compiler.

Canonical filtering uses `intent`. Allowances, exclusions, and by-others items
never become vendor lines. A purchased-stock or hardware item replaces
fabricated items only when its `dimensions.replaces_item_ids` explicitly names
those canonical item IDs.

The optional nesting input is the versioned `rfq_nesting.json` object:

```json
{
  "schema_version": "1.0.0",
  "source_nest_result_version": "1.0.0",
  "geometry_readiness": "geometry_verified",
  "rows": []
}
```

Unknown versions are blocked. Rows stay separate by stock identity, material,
grade, thickness, and sheet size.

The company profile is resolved in this order:

1. File named by `PI_STEEL_CONFIG`.
2. Ignored project file `.pi-steel/company-profile.json` beside the input.
3. Platform user configuration at `pi-steel/company-profile.json`.

Runtime profiles must not be saved under the installed package. The profile
requires company identity and an approved `terms_template` whose SHA-256
matches its exact UTF-8 content. Editing terms invalidates approval. A missing
optional logo uses the text header.

The command requires an explicit issue date:

```bash
python3 scripts/generate-rfq.py \
  --input estimate-package.json \
  --nest rfq_nesting.json \
  --issued-date 2026-07-28 \
  --out published/
```

Every workbook is marked `DRAFT — NOT SENT OR AWARDED`. The compiler contains
no send, award, vendor-selection, or purchase-authorization action.
