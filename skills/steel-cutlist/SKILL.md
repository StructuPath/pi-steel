---
name: steel-cutlist
description: "Optimize cut lengths of beams, channels, angles, HSS, tube, pipe, and any long product purchased by length — the 1D bar-nesting step. Use this skill whenever someone mentions cutting stock lengths, bar optimization, mill lengths, how many sticks/bars/lengths to buy, member cut lists, saw schedules, drops, or minimizing offcut waste on linear material. Produces a verified per-bar cutting plan, purchase summary by stock length, drop candidates, utilization, member weights, and optional cost totals only when an explicit basis exists."
---

# Steel Linear Cut-List Optimization

## What This Skill Does

This is the length-optimization step for long products: it packs required member lengths onto purchasable stock bars (mill lengths), accounting for saw kerf and end trim, then independently verifies every bar before publishing a cutting list. It answers "how many sticks do I buy, at which lengths, and how do I cut them" with a repeatable, reviewable result.

It complements `steel-nest` (2D plates). Plates go to `steel-nest`; anything bought by the foot goes here.

## What It Does Well vs. What It Doesn't

**Reliable:**
- Exact 1D packing per designation + grade group. Stock never crosses groups: a W12X26 member is only cut from W12X26 stock of the same grade.
- A deterministic strategy portfolio per group — a mixed-stock greedy plus each single-stock-length restriction — refined by a bounded exact branch-and-bound search for small groups (up to 12 pieces) that explores complete and partial placements alike and only ever replaces the portfolio result with a strictly better one. Ranking always minimizes unplaced members first; when every stock entry in the group carries a known cost basis, lowest purchase cost decides next (buying cheaper beats buying shorter), otherwise least purchased stock length decides (on-hand consumption is free). Fewest purchased bars and least total length settle ties. The same input always produces the same plan.
- Explicit fit contract: usable length = bar length − 2 × end trim; a piece fits when its length alone fits the remainder; each placed piece then consumes its length plus one kerf, saturating at the bar end.
- Independent post-placement verification (bar overcommitment, material mismatch, duplicate or missing instances) before any cutting list is published.
- Drops classified against a reusable-candidate threshold (`min_drop_in`) — candidates are never certified reusable stock.
- Member weights from explicit `unit_weight_plf` or the bundled AISC shape database; unknown weights are a visible warning, never a silent zero.
- Optional cost by one explicit basis per stock entry (`cost_per_ft` or `cost_per_bar`, never both).
- Labeled bar diagrams (PDF + PNG) and a per-bar `cutting_list.csv` emitted only for fully verified, fully placed runs.

**Deliberately NOT done:**
- No saw-controller programs or claims of machine-specific compatibility; the cutting list is a shop document that an operator verifies.
- No remnant-inventory or scrap-market optimization. Drop candidates need a person to measure, identify, and approve before they become stock.
- No global optimum guarantee for large groups — small groups (up to 12 pieces) are solved exactly within a fixed search budget, larger ones fall back to the deterministic portfolio heuristic; say so if asked.

## Inputs to Gather

Everything drives a single job JSON (schema in `references/job_template.json`; a worked example in `references/example_job.json`).

1. **Members** — for each line: name/mark, designation (e.g. `W12X26`, `HSS6X6X1/2`, `L4X4X1/4`), grade, required length (exactly one of `length_in` or `length_ft`; `length_ft` accepts `28.5` or `"28'-6"`), and quantity. Optional `unit_weight_plf` overrides the AISC lookup.
2. **Stock** — for each purchasable bar length: designation, grade, length (`length_in` or `length_ft`), and finite `qty` or `"unlimited": true`. Common mill lengths: 20, 25, 30, 35, 40, 45, 50, 55, 60 ft. A price is optional; if provided, use exactly one basis (`cost_per_ft` or `cost_per_bar`).
3. **Cut settings** — `kerf_in` (band saw ~0.06", cold saw ~0.09", abrasive/miter ~0.19"), `end_trim_in` per bar end (mill-end cleanup, default 0.25"), and `min_drop_in` (drops at or above this length are reported as reusable candidates, default 24").

If a takeoff/BOM spreadsheet is provided, map its columns to member fields and confirm the interpretation before running. Do not silently guess quantities or lengths.

## How to Run

Write the job JSON, then run the engine:

```bash
python3 scripts/cutlist.py --job <job.json> --out <outdir>
```

The designation, grade, and imperial unit basis must be explicit; the engine never infers them from display names. `<outdir>` is a publication root: every invocation creates `<outdir>/runs/<run-id>/` and atomically updates `<outdir>/latest-run.json`; follow that pointer to find the current run.

Each run contains:

- `run-manifest.json` and `qa-report.json` — outcome, readiness, hashes, warnings, and the exact artifact allow-list
- `layout.pdf` — every bar drawn with its cuts and drop, plus a summary page (the main deliverable)
- `bars.png` — the bar diagram as one image
- `cutting_list.csv` — the per-bar cut sequence; present only when the run is `ready` (verified and fully placed)
- `rfq_linear.json` — versioned `1.0.0` linear-stock rows for the `steel-rfq` hand-off; absent on blocked runs
- `report.txt` — the text report
- `result.json` — schema-versioned result with normalized input/configuration hashes, algorithm version, bar reports, verifier findings, purchase summary, drops, and cost status

Exit meanings:

- `0` — `ready`; every member is placed and the plan passed independent verification
- `3` — `blocked`; validation errors or unplaced members prevented a cutting list
- `4` — a required runtime capability is missing
- `1` — usage or internal error

Install the declared dependencies from the package root with `python3 -m pip install -r requirements-dev.txt`.

## What to Deliver

Always deliver the **PDF layout** and give the headline numbers in the message: bars to buy by length, length utilization, drop candidates, weight status, and cost status. Attach `cutting_list.csv` when it exists and state that saw-operator verification is still required.

Verify before presenting: require `verification.status = verified`, reconcile known cost to its recorded per-foot or per-bar basis, and never turn a missing or incomplete cost into `$0`. If members did not fit, lead with what is unplaced and why — never present a partial plan as complete.

## Integration with steel-rfq

The engine writes `rfq_linear.json` — `{schema_version, source_cutlist_result_version, rows}` with one row per stock identity: bars needed, bar length, total feet, cutting plan, and drop notes. Rows stay separate by stock identity even when display names match. Resolve the current run through `latest-run.json` and reject unknown handoff versions.

## Common Variations

**Mixed designations in one order** — list them all; the engine forms independent designation + grade groups and optimizes each on its own stock.

**"Just tell me how many sticks"** — still run it; the purchase summary is the answer. Cost remains absent unless an explicit basis is supplied.

**Drop reuse** — output drops are candidates only. Measure, identify, and approve a candidate before supplying it as its own finite stock entry in a later run (a shorter `length_in` entry with `qty: 1`).

**On-hand material first** — enter on-hand bars as finite-quantity stock entries with `"stock_kind": "on_hand"` alongside purchasable lengths. On-hand stock must be finite and carries no cost basis; the optimizer treats on-hand consumption as free (zero cost, zero purchased length), so sticks are consumed whenever they genuinely reduce buying, and every report labels on-hand rows explicitly.
