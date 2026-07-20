# pi-steel

Structural steel estimating skills for the [Pi coding agent](https://pi.dev) — built by working steel estimators, not by people guessing what a takeoff is.

By [StructuPath](https://structupath.ai), from the team behind a production structural-steel fabrication shop in Denver, CO.

## Install

```bash
pi install npm:@structupath/pi-steel
```

## What's Inside

### `steel-takeoff` — takeoffs, BOMs, tonnage

Structural steel quantity takeoff with a bundled **AISC 16th Edition shapes database (477 shapes)** — W, HSS, angles, channels, pipe — plus scripts the agent runs directly:

- `lookup-member.sh` — full property set for any AISC designation (`W14X30` → plf, d, bf, A, Ix, Sx, …)
- `calculate-weight.sh` — BOM totals with connection and misc-steel allowances, tonnage, cost sensitivity
- `validate-bom.py` — catches invalid designations, wrong grades, duplicate marks, unreasonable weights

Also includes reference guides for AISC shape families, takeoff procedures with worked examples, connection types and hardware weights, material grades, and bolt capacities.

Ask your agent things like:

> "Do a takeoff from these drawings and build me a BOM"
> "What's the lightest W-shape with depth ≥ 18" and Ix ≥ 1000?"
> "Total tonnage on this BOM with 12% connections"

### `steel-nest` — plate nesting & burn-table DXF

The plate-layout step CAM software does, minus the CAM seat: MaxRects bin-packing of parts onto stock plates with kerf/gap/edge-margin spacing, holes and rectangular cutouts, yield/scrap/reusable-drop numbers, and material cost. Outputs a labeled layout (PDF + PNG per plate), a cut list, and **one DXF per sheet for the burn table** (part outlines on `PROFILE`, holes on `HOLES`, origin at sheet corner — ready for ProNest/FastCAM/SigmaNEST import).

Honest about its limits: rectangular parts nest exactly; irregular parts nest by bounding box (flagged, never hidden); it deliberately does **not** emit G-code — kerf comp, lead-ins, and pierce points belong to your table's real post-processor.

> "How many sheets does this job need?"
> "Nest these parts on 96×48 plate and give me the yield"
> "Lay this out for the burn table"

Requires `ezdxf`, `matplotlib`, `numpy` (`pip install ezdxf matplotlib numpy`).

### `steel-rfq` — vendor quote requests

Turns a steel estimate/takeoff spreadsheet into a standardized vendor RFQ (.xlsx): materials grouped the way vendors stock them (W-shapes / plate / flat bar), yellow fill-in pricing columns, nesting/drop reference, and terms & conditions — branded with **your** company profile. When `steel-nest` has run for the job, its cutting plan flows straight into the RFQ's nesting table.

The three skills chain into a full estimating pipeline: **takeoff → nest → RFQ**.

One-time setup: copy `skills/steel-rfq/assets/company-profile.example.json` to `company-profile.json` and put in your company name, city, and payment terms. The skill will ask and offer to save it if you skip this.

> "Send this takeoff out for pricing"
> "Generate an RFQ from this estimate"

## Requirements

- `jq` and `python3` (with `pandas` + `openpyxl` for RFQ generation)
- macOS or Linux

## License

MIT. AISC shape data derived from the publicly available AISC Shapes Database v16.0.

---

Building software for steel fabricators? See [structupath.ai](https://structupath.ai).
