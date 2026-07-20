---
name: steel-nest
description: "Nest steel parts onto stock plates and estimate material — the plate-layout / cutting step that CAM software (SigmaNEST, Hypertherm, FANUC) does. Use this skill whenever someone mentions nesting, plate layout, plate optimization, cut list, cutting plan, yield, drop/remnant, how many sheets/plates a job needs, how much plate to buy, or laying parts out on a sheet. Also trigger when a new order/SO comes in and someone asks 'how much material', 'how many plates', 'what's the yield', or 'lay these parts out' — even if they don't say the word 'nest'. Produces a nesting layout (PDF + PNG), a cut list, yield/scrap/remnant numbers, material cost, and a DXF of the nest. Rectangular parts nest exactly; irregular parts nest by bounding box."
---

# Steel Plate Nesting & Estimate

## What This Skill Does

This is the in-house version of the plate-nesting step a CAM package (SigmaNEST / Hypertherm / FANUC) performs: it takes a list of parts and the plate stock on hand, packs the parts onto as few plates as possible, and tells you the yield, the drops you can reuse, the material weight, and the cost. It also draws the layout and exports a DXF.

It exists so that the moment an order lands, anyone in the shop can get a fast, repeatable material number for quoting and a layout the cutter can follow — without waiting on the CAM seat.

## What It Does Well vs. What It Doesn't

Be honest with the user about the boundary — it protects the shop from over-trusting the output.

**Reliable:**
- Rectangular / plate-blank parts nest **exactly** (MaxRects bin-packing with rotation).
- Multiple plate sizes, kerf + gap spacing, edge margin (grip/clamp keep-out).
- **Holes and rectangular cutouts** on any part — subtracted from weight/cost, rotated with the part, and cut as real geometry in the output.
- Yield %, scrap weight, largest reusable **drop** per plate.
- Material weight and cost (by $/lb — which also values scrap — or by $/sheet).
- Labeled layout (PDF + one PNG per plate).
- **Burn-table files**: one DXF **per sheet** (`burn_plate_N.dxf`) with part outlines on layer `PROFILE` and holes on layer `HOLES`, origin at the sheet corner — ready to import into the table's CAM. Plus `nest.dxf`, an all-sheets overview.

**Approximate — always flag it:**
- **Irregular parts** (gussets, brackets, curved profiles, parts with holes) are nested by their **bounding box**, not true shape. Real yield is a little better than reported. For exact weight/cost on those, get the true cut area (in²) into the part's `area` field. This is NOT true-shape nesting like a dedicated CAM engine.

**Do NOT pretend to do:**
- **Machine-ready G-code / NC** with kerf compensation, pierce points, and lead-ins for a specific controller. That is machine-specific and safety-critical and must come from the real post-processor. The burn DXF from this skill is a geometry/import file — the table's CAM (Hypertherm ProNest, FastCAM, SigmaNEST, Lantek, or the controller's own importer) applies kerf comp, lead-ins and pierce. Say so plainly if asked for G-code; offer the DXF as the correct hand-off.

## Inputs to Gather

Everything drives a single job JSON (schema in `references/job_template.json`; a worked example in `references/example_job.json`). Build that JSON from whatever the user gives you — a typed part list in chat, a takeoff/BOM spreadsheet, or a `steel-rfq` estimate file.

Gather three things:

1. **Parts** — for each unique part: name, width × height (inches; use the bounding box for odd shapes), quantity, whether it's `rect` or `irregular`, and whether rotation is allowed (`rotatable: false` locks grain/rolling direction for anisotropic material or directional finish). If a part has **holes or cutouts** and you want them cut in the burn file (and netted out of weight), add a `holes` list — each hole's `x,y` is its center from the part's lower-left corner: round = `{"dia":, "x":, "y":}`, rectangular cutout = `{"w":, "h":, "x":, "y":}`. Holes are optional; skip them if you only need the layout/estimate.
2. **Stock** — plate size(s) on hand (width × height × thickness), how many sheets are available (or `unlimited` to buy as needed), and price (`cost_per_lb` preferred; `cost_per_sheet` works too).
3. **Cut settings** — kerf, part gap, edge margin, material density. Sensible defaults are in the template; only ask if the user hasn't implied them. Common kerf: plasma ~0.06", oxy-fuel ~0.10", laser ~0.02", waterjet ~0.03".

If a spreadsheet is provided, read it with pandas first, map columns to the part fields, and confirm your interpretation before nesting. Do not silently guess quantities or dimensions.

### Defaults (only override when the user gives you a reason)
- kerf 0.06", part gap 0.25", edge margin 0.5"
- A36 mild steel density 0.2836 lb/in³ (aluminum 0.098, 304 stainless 0.289)
- Standard sheet sizes to offer if they don't specify: 96×48, 120×48, 144×48, 240×96 in

## How to Run

Write the job JSON, then run the engine:

```bash
python3 scripts/nest.py --job <job.json> --out <outdir>
```

Outputs land in `<outdir>/`:
- `layout.pdf` — every plate drawn (holes shown) + a summary page (the main deliverable)
- `plate_1.png`, `plate_2.png`, … — one image per plate
- `burn_plate_1.dxf`, `burn_plate_2.dxf`, … — **one DXF per sheet for the burn table** (PROFILE + HOLES layers, origin at sheet corner)
- `nest.dxf` — all sheets side-by-side, one overview file
- `rfq_nesting.json` — the Material / Nesting Plan / Drop Notes block for the `steel-rfq` hand-off (see below)
- `report.txt` — the text report
- `result.json` — structured result (plates, placements, holes, yield, cost) for downstream use

The engine has no third-party build dependencies beyond `ezdxf`, `matplotlib`, and `numpy`. Install once if missing: `pip install --break-system-packages ezdxf matplotlib numpy`.

## What to Deliver

Always deliver the **PDF layout** and give the headline numbers in the message: plates used, overall yield %, total material cost, and any parts that **did not fit** (the report flags these — never hide them; it means they need more or bigger stock). Offer the DXF and per-plate PNGs. If the parts were irregular, restate the bounding-box caveat so the quote isn't over-trusted.

Verify before presenting: the engine already checks that no parts overlap and all fit in-bounds, but sanity-check the yield and cost against the plate count (e.g., cost = plates × sheet cost, or plate weight × $/lb). If a plate shows very low yield, mention it — it's usually the tail plate and may be worth holding parts for the next order.

## Integration with steel-rfq

The `steel-rfq` skill has a "Nesting / Drop Reference" table. This engine writes exactly that data to `rfq_nesting.json` on every run — one row per plate material with `material`, `nesting_plan`, `drop_notes`, plus `sheets_needed` (for cross-checking the estimate's assumed sheet count) and `total_cost`. When an RFQ involves plate, `steel-rfq` builds a nest job from the plate parts, runs this engine, and reads `rfq_nesting.json` straight into its table. Keep this JSON shape stable — the RFQ skill depends on those field names.

## Common Variations

**Mixed thickness / grade in one order** — nest each thickness as its own job (parts of different thickness can't share a plate). Run the engine once per thickness and combine the numbers in the summary.

**"Just tell me how many sheets"** — still run it; the plate count is the answer, and you get the yield and cost for free. Don't estimate sheet count by dividing areas — packing loss makes that wrong.

**Remnant/drop reuse** — add the leftover drop from a previous job as another `stock` entry (its size, `qty: 1`) so the engine tries to consume it first-ish. Note: with multiple stock sizes the engine fills them in the order listed, so list drops/offcuts first if you want them used up.

**Grain / directional material** — set `rotatable: false` on those parts so the nester won't spin them 90°.
