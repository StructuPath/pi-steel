# pi-steel

[![npm version](https://img.shields.io/npm/v/%40structupath%2Fpi-steel)](https://www.npmjs.com/package/@structupath/pi-steel)
[![CI](https://github.com/StructuPath/pi-steel/actions/workflows/ci.yml/badge.svg)](https://github.com/StructuPath/pi-steel/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Pi package](https://img.shields.io/badge/Pi-package-7c3aed)](https://pi.dev/packages?name=pi-steel)

Structural-steel estimating skills for the [Pi coding agent](https://pi.dev):
validated takeoffs, plate nesting, guarded DXF output, draft vendor RFQs, and a
review-gated estimate pipeline.

Built by [StructuPath](https://structupath.ai).

## Demo

![pi-steel builds a synthetic estimate package](https://raw.githubusercontent.com/StructuPath/pi-steel/main/docs/assets/pi-steel-demo.gif)

This demo uses only the repository's synthetic fixture. It runs the complete
`takeoff → nest → draft RFQ` pipeline and publishes an isolated package with a
machine-readable `rfq_ready_for_review` outcome.

## Install

```bash
pi install npm:@structupath/pi-steel
```

Then ask Pi:

```text
Do a structural-steel takeoff from these drawings and build a validated BOM.
Nest these rectangular plate parts on 96 × 48 stock.
Prepare a draft RFQ from this estimate.
```

Run the local dependency check when using the source repository:

```bash
npm run doctor
```

## What is included

| Skill | Purpose | Primary outputs |
| --- | --- | --- |
| `steel-takeoff` | Validate member designations and calculate BOM weight and tonnage | Validated BOM and findings |
| `steel-nest` | Lay out plate parts with kerf, gap, and edge-margin controls | Nest results, cut list, reference drawings, and guarded burn DXFs |
| `steel-rfq` | Compile estimate data into a reviewable vendor request | Draft `.xlsx` RFQ and semantic workbook record |
| `steel-estimate` | Orchestrate the complete review-gated workflow | Immutable run directory, QA report, lineage, manifests, nesting, and draft RFQ |

### Takeoff

`steel-takeoff` provides AISC shape lookup, weight calculation, and BOM
validation helpers. It checks member designations, grades, duplicate marks, and
unreasonable weights. It calculates from supplied quantities and allowances; it
does not invent pricing.

### Nesting and DXF safety

`steel-nest` uses MaxRects bin packing for rectangular parts and reports yield,
scrap, reusable drops, and unplaced material. Irregular parts are estimated by
bounding box and are always flagged.

Per-sheet `burn_plate_N.dxf` files are emitted only when the full nest is
complete and every supported hole remains inside its part. Otherwise, pi-steel
suppresses burn DXFs for the entire run and leaves clearly labeled estimating
and reference artifacts for review. It does not emit G-code or claim
machine-specific CAM compatibility.

### Draft RFQs

`steel-rfq` groups material by stock family, carries approved nesting data into
the workbook, and provides fill-in columns for vendor pricing. Workbooks remain
drafts until a person reviews and issues them.

Copy the example company profile to a private project location:

```bash
mkdir -p .pi-steel
cp skills/steel-rfq/assets/company-profile.example.json \
  .pi-steel/company-profile.json
```

Complete that local copy with approved company information. Never commit the
completed profile.

## Workflow and outcomes

```text
estimate input
    ↓
contract validation → plate nesting → draft RFQ compilation
    ↓
QA findings + lineage + immutable run manifest
    ↓
ready | needs_review | blocked
```

Each run is published below the requested output root and referenced by
`latest-run.json`. Exit status `0` means geometry-verified, `2` means human
review is required, and `3` means the workflow is blocked. A blocked run never
contains an RFQ workbook.

## Public-repository safety

This repository and all committed examples are public. Do not add:

- company profiles or internal business context;
- customer, vendor, employee, project, bid, or contract data;
- live pricing, margins, terms, credentials, or private contact information;
- generated RFQs, takeoffs, PDFs, DXFs, spreadsheets, or output directories.

Keep operational inputs and generated artifacts outside the repository. See the
[public data policy](PUBLIC_DATA_POLICY.md) and
[data provenance record](DATA_PROVENANCE.md) before contributing.

## Documentation

- [GitHub wiki](https://github.com/StructuPath/pi-steel/wiki)
- [Public data policy](PUBLIC_DATA_POLICY.md)
- [Data provenance](DATA_PROVENANCE.md)
- [Pi package catalog](https://pi.dev/packages?name=pi-steel)
- [npm package](https://www.npmjs.com/package/@structupath/pi-steel)

## Development

```bash
npm test                 # base, no-render suite
npm run test:full        # PDF/PNG/DXF/LibreOffice smoke tests
npm run privacy:check    # current public-repository data guard
npm run privacy:history  # redacted audit of reachable history
npm run pack:check       # npm contents and installed-runtime smoke test
npm run provenance:check # shape-data integrity and recorded decision
npm run release:check    # complete release gate
```

The latest npm release is `0.2.2`. The source repository also declares `0.2.2`
until a later release passes every publishing gate.

`release:check` intentionally blocks a new npm publication while redistribution
permission for the transformed AISC shape dataset remains unverified. Do not
bypass that gate. An updated README or demo reaches the Pi catalog only through
a future, fully approved npm release.

## License

StructuPath-authored code and documentation are MIT licensed. That license does
not grant rights in third-party data. The checked-in AISC-derived shape data has
a separate, currently blocked redistribution decision documented in
[DATA_PROVENANCE.md](DATA_PROVENANCE.md).
