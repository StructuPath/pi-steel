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

### `steel-rfq` — vendor quote requests

Turns a steel estimate/takeoff spreadsheet into a standardized vendor RFQ (.xlsx): materials grouped the way vendors stock them (W-shapes / plate / flat bar), yellow fill-in pricing columns, nesting/drop reference, and terms & conditions — branded with **your** company profile.

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
