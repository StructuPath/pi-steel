#!/usr/bin/env python3
"""
Steel linear cut-list engine  (1D bar nesting for members)
==========================================================
Deterministic length optimization for long products: beams, channels, angles,
HSS, tube, pipe, bar, and any stock purchased by length and cut to member
lengths.

Reliable:
  * Packs required member lengths onto stock bars with a best-fit-decreasing
    heuristic plus simulated new-bar selection across multiple stock lengths.
  * Explicit saw kerf per cut and end-trim allowance per bar end.
  * Independent post-placement verification re-checks every bar against the
    declared fit model before any cutting list is published.
  * Reports drops (with a reusable-candidate threshold), utilization, member
    weights from explicit plf values or the bundled AISC shape database, and
    optional reconciled purchase cost.
  * Labeled bar diagrams (PNG + combined PDF) and a per-bar cutting list CSV
    that is only emitted for fully verified, fully placed runs.

Deliberately NOT done:
  * No cut sequencing for a specific saw controller and no claim of
    machine-specific compatibility; the cutting list is a shop document.
  * No scrap-market or remnant-inventory optimization. Drops are reported as
    unverified candidates for a person to disposition.

Fit model (documented contract):
  * usable bar length = stock length - 2 x end_trim_in
  * a piece fits when its length alone fits in the remaining usable length
  * each placed piece then consumes its length plus one kerf width,
    saturating at the bar end (the final cut coincides with the end trim)

Usage:
  python3 cutlist.py --job job.json --out published/

The output root receives isolated runs/<run-id>/ directories plus a
latest-run.json pointer. Exit 0 is ready, 2 requires review, and 3 is blocked.
"""

import argparse
import csv
import io
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path


SHARED_ROOT = Path(__file__).resolve().parents[2] / "_shared"
if str(SHARED_ROOT) not in sys.path:
    sys.path.insert(0, str(SHARED_ROOT))
from bootstrap import bootstrap_shared  # noqa: E402

SKILLS_ROOT = bootstrap_shared(__file__)
from pi_steel import (  # noqa: E402
    RunPublisher,
    StageArgumentParser,
    canonical_json_bytes,
    is_sha256,
    item_id_for,
    missing_optional_modules,
    outcome_exit_code,
    package_version,
    placement_ids,
    publish_failure_diagnostic,
    sha256_bytes,
)
from pi_steel.contracts import content_hash, fallback_source_id, instance_ids  # noqa: E402
from pi_steel.parsing import normalize_designation, parse_length_ft  # noqa: E402

CUTLIST_RESULT_VERSION = "1.0.0"
CUTLIST_ALGORITHM_VERSION = "portfolio-bfd-exact-v1"
EXACT_SEARCH_MAX_UNITS = 12
EXACT_SEARCH_NODE_BUDGET = 250_000
EPS = 1e-6
AISC_DATABASE_RELATIVE = Path("steel-takeoff") / "assets" / "aisc-shapes-database.json"


def load_unit_weights():
    """Map normalized designation -> weight_per_ft from the bundled AISC data."""
    database_path = SKILLS_ROOT / AISC_DATABASE_RELATIVE
    try:
        rows = json.loads(database_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    weights = {}
    for row in rows:
        designation = normalize_designation(row.get("designation", ""))
        weight = row.get("weight_per_ft")
        if designation and isinstance(weight, (int, float)) and weight > 0:
            weights[designation] = float(weight)
    return weights


def _validation_finding(code, path, message, severity="error"):
    return {
        "code": code,
        "severity": severity,
        "path": path,
        "message": message,
    }


def _finite_positive(value):
    return isinstance(value, (int, float)) and math.isfinite(value) and value > 0


# --------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------
def _length_in(entry, path, findings):
    """Resolve an explicit imperial length from length_in or length_ft."""
    has_inches = entry.get("length_in") is not None
    has_feet = entry.get("length_ft") is not None
    if has_inches == has_feet:
        findings.append(
            _validation_finding(
                "ambiguous_length_basis",
                path,
                "Provide exactly one of length_in or length_ft.",
            )
        )
        return 0.0
    try:
        if has_inches:
            parsed = float(entry["length_in"])
        else:
            raw = entry["length_ft"]
            parsed = (
                parse_length_ft(raw) if isinstance(raw, str) else float(raw)
            ) * 12.0
    except (TypeError, ValueError):
        parsed = math.nan
    if not math.isfinite(parsed) or parsed <= 0:
        findings.append(
            _validation_finding(
                "invalid_length",
                path,
                "Length must be finite and greater than zero.",
            )
        )
        return 0.0
    return parsed


def normalize_job(job):
    """Normalize and validate the direct-use JSON before any placement."""
    findings = []
    settings = job.get("settings", {})

    def number(value, path, *, positive=False, nonnegative=False):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = math.nan
        valid = math.isfinite(parsed)
        if positive:
            valid = valid and parsed > 0
        if nonnegative:
            valid = valid and parsed >= 0
        if not valid:
            findings.append(
                _validation_finding(
                    "invalid_numeric_input",
                    path,
                    "Value must be finite"
                    + (" and greater than zero." if positive else " and non-negative."),
                )
            )
            return 0.0
        return parsed

    kerf = number(settings.get("kerf_in", 0.125), "$.settings.kerf_in", nonnegative=True)
    end_trim = number(
        settings.get("end_trim_in", 0.25),
        "$.settings.end_trim_in",
        nonnegative=True,
    )
    min_drop = number(
        settings.get("min_drop_in", 24.0),
        "$.settings.min_drop_in",
        nonnegative=True,
    )
    unit_system = job.get("unit_system")
    if unit_system is None:
        findings.append(
            _validation_finding(
                "missing_unit_basis",
                "$.unit_system",
                "The cut-list engine requires an explicit imperial unit basis.",
            )
        )
    elif unit_system != "imperial":
        findings.append(
            _validation_finding(
                "unsupported_unit_system",
                "$.unit_system",
                "The cut-list engine currently requires imperial units.",
            )
        )

    project_id = job.get("project_id") or job.get("job_name") or "LEGACY-CUTLIST"
    revision_id = job.get("revision_id", "LEGACY-REVISION")
    for identity_field, value in (
        ("project_id", project_id),
        ("revision_id", revision_id),
    ):
        if not isinstance(value, str) or not value:
            findings.append(
                _validation_finding(
                    f"invalid_{identity_field}",
                    f"$.{identity_field}",
                    f"{identity_field} must be a non-empty string.",
                )
            )
            if identity_field == "project_id":
                project_id = "LEGACY-CUTLIST"
            else:
                revision_id = "LEGACY-REVISION"
    estimate_input_hash = job.get("estimate_input_hash")
    if estimate_input_hash is not None and not is_sha256(estimate_input_hash):
        findings.append(
            _validation_finding(
                "invalid_estimate_input_hash",
                "$.estimate_input_hash",
                "Estimate input hash must be a lowercase SHA-256 value.",
            )
        )
        estimate_input_hash = None

    default_grade = job.get("grade")
    unit_weights = load_unit_weights()
    members = []
    for index, member in enumerate(job.get("members", [])):
        path = f"$.members[{index}]"
        designation = normalize_designation(member.get("designation", ""))
        if not designation:
            findings.append(
                _validation_finding(
                    "missing_designation",
                    f"{path}.designation",
                    "Member designation is required for stock compatibility.",
                )
            )
        grade = member.get("grade", default_grade)
        if not grade:
            findings.append(
                _validation_finding(
                    "missing_material_basis",
                    f"{path}.grade",
                    "Member grade must be explicit before placement.",
                )
            )
        length = _length_in(member, path, findings)
        try:
            quantity = int(member.get("qty", 1))
            quantity_valid = quantity > 0 and quantity == float(member.get("qty", 1))
        except (TypeError, ValueError):
            quantity, quantity_valid = 0, False
        if not quantity_valid:
            findings.append(
                _validation_finding(
                    "invalid_quantity", f"{path}.qty", "Quantity must be a positive integer."
                )
            )
            quantity = 0
        unit_weight = member.get("unit_weight_plf")
        weight_basis = "declared"
        if unit_weight is not None:
            unit_weight = number(
                unit_weight, f"{path}.unit_weight_plf", positive=True
            )
        elif designation in unit_weights:
            unit_weight = unit_weights[designation]
            weight_basis = "aisc_database"
        else:
            weight_basis = "unknown"
            findings.append(
                _validation_finding(
                    "unknown_unit_weight",
                    f"{path}.unit_weight_plf",
                    (
                        f"No unit weight declared and {designation or 'the designation'} "
                        "is not in the bundled AISC data; weights are incomplete."
                    ),
                    severity="warning",
                )
            )
        explicit_source = member.get("source_id")
        source_id = explicit_source or fallback_source_id(
            revision_id,
            {
                key: member.get(key)
                for key in ("name", "designation", "grade", "length_in", "length_ft")
            },
        )
        item_id = member.get("item_id") or item_id_for(
            project_id, revision_id, source_id
        )
        members.append(
            {
                "source_id": source_id,
                "item_id": item_id,
                "label": member.get("name", source_id),
                "designation": designation,
                "grade": grade,
                "length_in": length,
                "quantity": quantity,
                "unit_weight_plf": unit_weight,
                "weight_basis": weight_basis,
            }
        )

    stock_types = []
    for index, stock in enumerate(job.get("stock", [])):
        path = f"$.stock[{index}]"
        stock_kind = stock.get("stock_kind", "purchasable")
        if stock_kind not in {"purchasable", "on_hand"}:
            findings.append(
                _validation_finding(
                    "invalid_stock_kind",
                    f"{path}.stock_kind",
                    "Stock kind must be purchasable or on_hand.",
                )
            )
            stock_kind = "purchasable"
        designation = normalize_designation(stock.get("designation", ""))
        if not designation:
            findings.append(
                _validation_finding(
                    "missing_designation",
                    f"{path}.designation",
                    "Stock designation is required for member compatibility.",
                )
            )
        grade = stock.get("grade", default_grade)
        if not grade:
            findings.append(
                _validation_finding(
                    "missing_material_basis",
                    f"{path}.grade",
                    "Stock grade must be explicit.",
                )
            )
        length = _length_in(stock, path, findings)
        usable = length - 2 * end_trim
        if length > 0 and usable <= EPS:
            findings.append(
                _validation_finding(
                    "unusable_stock_length",
                    f"{path}",
                    "End trim consumes the entire stock length.",
                )
            )
        unlimited = stock.get("unlimited", False)
        if not isinstance(unlimited, bool):
            findings.append(
                _validation_finding(
                    "invalid_unlimited_flag",
                    f"{path}.unlimited",
                    "Unlimited must be a JSON boolean.",
                )
            )
            unlimited = False
        if unlimited and stock_kind == "on_hand":
            findings.append(
                _validation_finding(
                    "unlimited_on_hand_stock",
                    f"{path}.unlimited",
                    "On-hand stock must be a finite, measured quantity.",
                )
            )
        try:
            quantity = math.inf if unlimited else int(stock.get("qty", 1))
            quantity_valid = unlimited or (
                quantity >= 0 and quantity == float(stock.get("qty", 1))
            )
        except (TypeError, ValueError):
            quantity, quantity_valid = 0, False
        if not quantity_valid:
            findings.append(
                _validation_finding(
                    "invalid_stock_quantity",
                    f"{path}.qty",
                    "Stock quantity must be a non-negative integer or unlimited.",
                )
            )
        per_foot = stock.get("cost_per_ft")
        per_bar = stock.get("cost_per_bar")
        if per_foot is not None and per_bar is not None:
            findings.append(
                _validation_finding(
                    "conflicting_cost_basis",
                    path,
                    "Use either cost_per_ft or cost_per_bar for one stock entry, not both.",
                )
            )
        if stock_kind == "on_hand" and (per_foot is not None or per_bar is not None):
            findings.append(
                _validation_finding(
                    "cost_basis_on_hand_stock",
                    path,
                    "On-hand stock carries no purchase cost basis; cost applies to purchasable stock only.",
                )
            )
        if per_foot is not None:
            per_foot = number(per_foot, f"{path}.cost_per_ft", nonnegative=True)
        if per_bar is not None:
            per_bar = number(per_bar, f"{path}.cost_per_bar", nonnegative=True)
        stock_id = stock.get("stock_id") or (
            "stock:"
            + content_hash(
                {
                    "name": stock.get("name", "Bar"),
                    "stock_kind": stock_kind,
                    "designation": designation,
                    "grade": grade,
                    "length_in": length,
                }
            )[:24]
        )
        stock_types.append(
            {
                "stock_id": stock_id,
                "name": stock.get("name", designation or "Bar"),
                "stock_kind": stock_kind,
                "designation": designation,
                "grade": grade,
                "length_in": length,
                "usable_in": max(usable, 0.0),
                "qty": quantity,
                "cost_per_ft": per_foot,
                "cost_per_bar": per_bar,
                "used": 0,
            }
        )

    for collection_name, values, identity_field in (
        ("members", members, "item_id"),
        ("stock", stock_types, "stock_id"),
    ):
        seen = {}
        for index, value in enumerate(values):
            identity = value[identity_field]
            if identity in seen:
                findings.append(
                    _validation_finding(
                        f"duplicate_{identity_field}",
                        f"$.{collection_name}[{index}].{identity_field}",
                        (
                            f"{identity_field} duplicates row {seen[identity]}; "
                            "indistinguishable rows are not merged."
                        ),
                    )
                )
            else:
                seen[identity] = index
    members.sort(key=lambda member: member["item_id"])
    stock_types.sort(key=lambda stock: stock["stock_id"])
    if not members:
        findings.append(
            _validation_finding(
                "missing_members", "$.members", "At least one member is required."
            )
        )
    if not stock_types:
        findings.append(
            _validation_finding(
                "missing_stock", "$.stock", "At least one stock entry is required."
            )
        )
    normalized = {
        "job_name": job.get("job_name", "Cut-list job"),
        "customer": job.get("customer", ""),
        "project_id": project_id,
        "revision_id": revision_id,
        "estimate_input_hash": estimate_input_hash,
        "unit_system": unit_system or "unspecified",
        "settings": {
            "kerf_in": kerf,
            "end_trim_in": end_trim,
            "min_drop_in": min_drop,
        },
        "members": members,
        "stock": [
            {
                key: ("unlimited" if key == "qty" and math.isinf(value) else value)
                for key, value in stock.items()
                if key != "used"
            }
            for stock in stock_types
        ],
    }
    return normalized, stock_types, findings


# --------------------------------------------------------------------------
# Placement engine
# --------------------------------------------------------------------------
def _group_key(value):
    return value["designation"], value["grade"]


def _simulate_fill(usable, kerf, queue):
    """Greedy first-fit of a sorted queue onto one bar; returns used length."""
    remaining = usable
    used = 0.0
    for length in queue:
        if length <= remaining + EPS:
            used += length
            remaining -= length + kerf
            if remaining < 0:
                remaining = 0.0
    return used


def _place_on_bar(bar, unit, kerf):
    bar["cuts"].append(unit)
    bar["remaining"] -= unit["length_in"] + kerf
    if bar["remaining"] < 0:
        bar["remaining"] = 0.0


def _greedy_pack(units, stocks, kerf, classification_stock):
    """Best-fit-decreasing over open bars; new bars open by simulated fill.

    ``stocks`` restricts which stock this attempt may open; unplaceable
    reasons are classified against ``classification_stock`` (the full group)
    so restricted attempts never mislabel a genuinely placeable member.
    """
    used = {stock["stock_id"]: 0 for stock in stocks}
    bars = []
    unplaced = []
    pending = [unit["length_in"] for unit in units]

    def open_bar(unit):
        best = None
        best_score = None
        for stock in stocks:
            if used[stock["stock_id"]] >= stock["qty"]:
                continue
            if unit["length_in"] > stock["usable_in"] + EPS:
                continue
            fill = _simulate_fill(stock["usable_in"], kerf, pending)
            fill_ratio = fill / stock["usable_in"] if stock["usable_in"] else 0.0
            score = (round(fill_ratio, 9), round(fill, 6), stock["stock_id"])
            if best_score is None or score > best_score:
                best_score = score
                best = stock
        if best is None:
            return None
        used[best["stock_id"]] += 1
        bar = {"stock": best, "cuts": [], "remaining": best["usable_in"]}
        bars.append(bar)
        return bar

    for unit in units:
        fits_group = any(
            unit["length_in"] <= stock["usable_in"] + EPS
            for stock in classification_stock
        )
        fits_attempt = any(
            unit["length_in"] <= stock["usable_in"] + EPS for stock in stocks
        )
        if not fits_group or not fits_attempt:
            reason = "no_compatible_stock_fit" if not fits_group else "stock_exhausted"
            unplaced.append({**unit, "reason": reason})
            pending.remove(unit["length_in"])
            continue
        best_bar = None
        best_leftover = math.inf
        for bar in bars:
            if unit["length_in"] > bar["remaining"] + EPS:
                continue
            leftover = bar["remaining"] - unit["length_in"]
            if leftover < best_leftover - EPS:
                best_leftover = leftover
                best_bar = bar
        if best_bar is None:
            best_bar = open_bar(unit)
        if best_bar is None:
            unplaced.append({**unit, "reason": "stock_exhausted"})
        else:
            _place_on_bar(best_bar, unit, kerf)
        pending.remove(unit["length_in"])
    return bars, unplaced


def _bar_cost(stock):
    if stock["cost_per_bar"] is not None:
        return stock["cost_per_bar"]
    if stock["cost_per_ft"] is not None:
        return stock["cost_per_ft"] * stock["length_in"] / 12.0
    return None


def _ranking_cost(stock):
    """Purchase outlay used for strategy ranking; on-hand material costs nothing."""
    if stock["stock_kind"] == "on_hand":
        return 0.0
    return _bar_cost(stock)


def _rank_solution(bars, unplaced_count, cost_priority):
    """Solution ranking, always fewest unplaced members first.

    When every stock entry in the group has a known purchase basis
    (``cost_priority``), lowest cost decides next — buying cheaper beats
    buying shorter. Otherwise least PURCHASED stock length decides (on-hand
    consumption is free) with any known cost as a later tie-break. Fewest
    purchased bars, then least total length, settle remaining ties.
    """
    purchased = [
        bar for bar in bars if bar["stock"]["stock_kind"] == "purchasable"
    ]
    purchased_length = round(
        sum(bar["stock"]["length_in"] for bar in purchased), 6
    )
    costs = [_ranking_cost(bar["stock"]) for bar in bars]
    cost_rank = round(sum(costs), 2) if None not in costs else math.inf
    total_length = round(sum(bar["stock"]["length_in"] for bar in bars), 6)
    if cost_priority:
        primary, secondary = cost_rank, purchased_length
    else:
        primary, secondary = purchased_length, cost_rank
    return (unplaced_count, primary, secondary, len(purchased), total_length)


class _SearchBudgetExceeded(Exception):
    pass


def _exact_solve_group(units, group_stock, kerf, best_rank, cost_priority):
    """Branch-and-bound over complete bar assignments for a small group.

    Seeded with the portfolio's rank for pruning, bounded by a fixed node
    budget so runtime stays deterministic. Returns (bars, unplaced, rank)
    only when a complete assignment strictly beats ``best_rank``; otherwise
    None and the caller keeps the portfolio result.
    """
    placeable = []
    unplaced_units = []
    for unit in units:
        if any(
            unit["length_in"] <= stock["usable_in"] + EPS
            for stock in group_stock
        ):
            placeable.append(unit)
        else:
            unplaced_units.append({**unit, "reason": "no_compatible_stock_fit"})
    if not placeable or len(placeable) > EXACT_SEARCH_MAX_UNITS:
        return None
    stocks = sorted(group_stock, key=lambda stock: stock["stock_id"])
    used = {stock["stock_id"]: 0 for stock in stocks}
    bars_state = []  # mutable [stock, remaining, cuts] triples
    unplaced_count = len(unplaced_units)
    state = {"nodes": 0, "best": None, "best_rank": best_rank}

    def primary_bound():
        """Monotone lower bound on the rank's primary component."""
        if cost_priority:
            costs = [_ranking_cost(triple[0]) for triple in bars_state]
            return (
                round(sum(costs), 2) if None not in costs else math.inf
            )
        return round(
            sum(
                triple[0]["length_in"]
                for triple in bars_state
                if triple[0]["stock_kind"] == "purchasable"
            ),
            6,
        )

    def descend(index):
        state["nodes"] += 1
        if state["nodes"] > EXACT_SEARCH_NODE_BUDGET:
            raise _SearchBudgetExceeded
        if (
            state["best_rank"] is not None
            and primary_bound() > state["best_rank"][1]
        ):
            return
        if index == len(placeable):
            solution = [
                {"stock": triple[0], "cuts": list(triple[2]), "remaining": 0.0}
                for triple in bars_state
            ]
            rank = _rank_solution(solution, unplaced_count, cost_priority)
            if state["best_rank"] is None or rank < state["best_rank"]:
                state["best_rank"] = rank
                state["best"] = [
                    (triple[0], list(triple[2])) for triple in bars_state
                ]
            return
        unit = placeable[index]
        length = unit["length_in"]
        seen = set()
        for triple in bars_state:
            slot = (triple[0]["stock_id"], round(triple[1], 6))
            if slot in seen:
                continue
            seen.add(slot)
            if length <= triple[1] + EPS:
                previous = triple[1]
                triple[2].append(unit)
                triple[1] = max(previous - length - kerf, 0.0)
                descend(index + 1)
                triple[1] = previous
                triple[2].pop()
        for stock in stocks:
            if used[stock["stock_id"]] >= stock["qty"]:
                continue
            if length > stock["usable_in"] + EPS:
                continue
            used[stock["stock_id"]] += 1
            bars_state.append(
                [stock, max(stock["usable_in"] - length - kerf, 0.0), [unit]]
            )
            descend(index + 1)
            bars_state.pop()
            used[stock["stock_id"]] -= 1

    try:
        descend(0)
    except _SearchBudgetExceeded:
        return None
    if state["best"] is None:
        return None
    bars = []
    for stock, cuts in state["best"]:
        bar = {"stock": stock, "cuts": [], "remaining": stock["usable_in"]}
        for unit in cuts:
            _place_on_bar(bar, unit, kerf)
        bars.append(bar)
    return bars, unplaced_units, state["best_rank"]


def _solve_group(units, group_stock, kerf):
    """Deterministic strategy portfolio, refined by a bounded exact search.

    Portfolio candidates: the mixed-stock greedy plus each
    single-stock-length restriction, ranked per ``_rank_solution`` with the
    strategy name as the final tie-break. Small groups then run a
    branch-and-bound exact search seeded with the portfolio rank; its result
    replaces the portfolio's only when strictly better, so the outcome is
    never worse than the greedy portfolio.
    """
    strategies = [("mixed", group_stock)]
    for stock in group_stock:
        strategies.append((f"single:{stock['stock_id']}", [stock]))
    cost_priority = all(
        _ranking_cost(stock) is not None for stock in group_stock
    )
    best = None
    best_rank = None
    for name, stocks in strategies:
        bars, unplaced = _greedy_pack(units, stocks, kerf, group_stock)
        rank = (
            *_rank_solution(bars, sum(1 for _ in unplaced), cost_priority),
            name,
        )
        if best_rank is None or rank < best_rank:
            best_rank = rank
            best = (bars, unplaced)
    if best is None:
        return [], []
    exact = _exact_solve_group(
        units, group_stock, kerf, best_rank[:5], cost_priority
    )
    if exact is not None:
        exact_bars, exact_unplaced, _ = exact
        return exact_bars, exact_unplaced
    return best


def run_job(job):
    normalized, stock_types, validation_findings = normalize_job(job)
    settings = normalized["settings"]
    kerf = settings["kerf_in"]
    normalized_hash = sha256_bytes(canonical_json_bytes(normalized))
    blockers = [
        finding
        for finding in validation_findings
        if finding["severity"] == "error"
    ]
    if blockers:
        return _summarize(
            normalized, [], [], validation_findings, normalized_hash
        )

    units = []
    for member in normalized["members"]:
        member_instances = instance_ids(member["item_id"], member["quantity"])
        member_placements = placement_ids(member["item_id"], member["quantity"])
        for index in range(member["quantity"]):
            units.append(
                {
                    **member,
                    "instance_id": member_instances[index],
                    "placement_id": member_placements[index],
                }
            )
    units.sort(key=lambda unit: (-unit["length_in"], unit["instance_id"]))

    units_by_group = defaultdict(list)
    for unit in units:
        units_by_group[_group_key(unit)].append(unit)
    stock_by_group = defaultdict(list)
    for stock in stock_types:
        stock_by_group[_group_key(stock)].append(stock)

    bars = []
    unplaced_units = []
    for key in sorted(units_by_group, key=repr):
        group_bars, group_unplaced = _solve_group(
            units_by_group[key], stock_by_group.get(key, []), kerf
        )
        bars.extend(group_bars)
        unplaced_units.extend(group_unplaced)

    used_bars = [bar for bar in bars if bar["cuts"]]
    for index, bar in enumerate(used_bars, 1):
        bar["index"] = index
    return _summarize(
        normalized,
        used_bars,
        _aggregate_unplaced(unplaced_units),
        validation_findings,
        normalized_hash,
    )


def _aggregate_unplaced(units):
    grouped = {}
    for unit in units:
        key = (unit["item_id"], unit["reason"])
        row = grouped.setdefault(
            key,
            {
                "item_id": unit["item_id"],
                "label": unit["label"],
                "designation": unit["designation"],
                "grade": unit["grade"],
                "length_in": unit["length_in"],
                "quantity": 0,
                "reason": unit["reason"],
            },
        )
        row["quantity"] += 1
    return sorted(grouped.values(), key=lambda row: (row["item_id"], row["reason"]))


# --------------------------------------------------------------------------
# Independent verification
# --------------------------------------------------------------------------
def verify_cutlist_bars(bar_reports, *, kerf, expected_instances):
    """Re-check published bars against the declared fit model and coverage."""
    findings = []
    seen_instances = set()
    for bar in bar_reports:
        cuts = bar["cuts"]
        lengths = [cut["length_in"] for cut in cuts]
        minimum_consumed = sum(lengths) + kerf * max(len(lengths) - 1, 0)
        if minimum_consumed > bar["usable_length_in"] + 1e-6:
            findings.append(
                _validation_finding(
                    "BAR_OVERCOMMITTED",
                    f"$.bar_reports[{bar['index'] - 1}]",
                    (
                        f"Bar {bar['index']} cuts plus kerf exceed its usable "
                        "length."
                    ),
                )
            )
        for cut_index, cut in enumerate(cuts):
            if (cut["designation"], cut["grade"]) != (
                bar["designation"],
                bar["grade"],
            ):
                findings.append(
                    _validation_finding(
                        "BAR_MATERIAL_MISMATCH",
                        f"$.bar_reports[{bar['index'] - 1}].cuts[{cut_index}]",
                        "Cut designation or grade does not match its bar.",
                    )
                )
            if cut["instance_id"] in seen_instances:
                findings.append(
                    _validation_finding(
                        "DUPLICATE_PLACEMENT",
                        f"$.bar_reports[{bar['index'] - 1}].cuts[{cut_index}]",
                        f"Instance {cut['instance_id']} is cut more than once.",
                    )
                )
            seen_instances.add(cut["instance_id"])
    missing = expected_instances - seen_instances
    extra = seen_instances - expected_instances
    for instance_id in sorted(missing):
        findings.append(
            _validation_finding(
                "INSTANCE_UNACCOUNTED",
                "$.bar_reports",
                f"Instance {instance_id} is neither cut nor reported unplaced.",
            )
        )
    for instance_id in sorted(extra):
        findings.append(
            _validation_finding(
                "INSTANCE_UNEXPECTED",
                "$.bar_reports",
                f"Instance {instance_id} does not belong to this job.",
            )
        )
    return findings


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------
def _summarize(normalized, used_bars, unplaced, validation_findings, normalized_hash):
    settings = normalized["settings"]
    kerf = settings["kerf_in"]
    min_drop = settings["min_drop_in"]
    estimate_input_hash = normalized.get("estimate_input_hash") or normalized_hash

    bar_reports = []
    total_stock_length = 0.0
    total_cut_length = 0.0
    total_weight_known = True
    total_cut_weight = 0.0
    total_cost = 0.0
    all_costs_known = bool(used_bars)
    for bar in used_bars:
        stock = bar["stock"]
        cuts = []
        cut_length = 0.0
        bar_weight_known = True
        bar_cut_weight = 0.0
        for cut_index, unit in enumerate(bar["cuts"], 1):
            weight = (
                unit["unit_weight_plf"] * unit["length_in"] / 12.0
                if unit["unit_weight_plf"] is not None
                else None
            )
            if weight is None:
                bar_weight_known = False
            else:
                bar_cut_weight += weight
            cuts.append(
                {
                    "sequence": cut_index,
                    "item_id": unit["item_id"],
                    "source_id": unit["source_id"],
                    "instance_id": unit["instance_id"],
                    "placement_id": unit["placement_id"],
                    "label": unit["label"],
                    "designation": unit["designation"],
                    "grade": unit["grade"],
                    "length_in": unit["length_in"],
                    "weight_lbs": None if weight is None else round(weight, 1),
                    "weight_basis": unit["weight_basis"],
                }
            )
            cut_length += unit["length_in"]
        kerf_total = kerf * len(cuts)
        used_length = min(cut_length + kerf_total, stock["usable_in"])
        drop = max(stock["usable_in"] - used_length, 0.0)
        if stock["stock_kind"] == "on_hand":
            bar_cost = None
            cost_basis = "on_hand"
        elif stock["cost_per_bar"] is not None:
            bar_cost = stock["cost_per_bar"]
            cost_basis = "per_bar"
        elif stock["cost_per_ft"] is not None:
            bar_cost = stock["cost_per_ft"] * stock["length_in"] / 12.0
            cost_basis = "per_foot"
        else:
            bar_cost = None
            cost_basis = None
            all_costs_known = False
        if bar_cost is not None:
            total_cost += bar_cost
        report = {
            "index": bar["index"],
            "stock": stock["name"],
            "stock_id": stock["stock_id"],
            "stock_kind": stock["stock_kind"],
            "designation": stock["designation"],
            "grade": stock["grade"],
            "bar_length_in": stock["length_in"],
            "usable_length_in": stock["usable_in"],
            "end_trim_in": settings["end_trim_in"],
            "cuts": cuts,
            "num_cuts": len(cuts),
            "cut_length_in": round(cut_length, 3),
            "kerf_total_in": round(kerf_total, 3),
            "drop_in": round(drop, 3),
            "drop_class": (
                "reusable_candidate" if drop >= min_drop - EPS else "offcut"
            ),
            "utilization_pct": round(
                100 * cut_length / stock["length_in"], 1
            )
            if stock["length_in"]
            else 0.0,
            "cut_weight_lbs": (
                round(bar_cut_weight, 1) if bar_weight_known else None
            ),
            "bar_cost": None if bar_cost is None else round(bar_cost, 2),
            "cost_basis": cost_basis,
        }
        bar_reports.append(report)
        total_stock_length += stock["length_in"]
        total_cut_length += cut_length
        if bar_weight_known:
            total_cut_weight += bar_cut_weight
        else:
            total_weight_known = False

    expected_instances = set()
    for member in normalized["members"]:
        expected_instances.update(
            instance_ids(member["item_id"], member["quantity"])
        )
    placed_elsewhere = {
        cut["instance_id"]
        for report in bar_reports
        for cut in report["cuts"]
    }
    for row in unplaced:
        prefix = f"{row['item_id']}:instance:"
        matching = sorted(
            instance
            for instance in expected_instances
            if instance.startswith(prefix)
        )
        removable = [
            instance for instance in matching if instance not in placed_elsewhere
        ][-row["quantity"]:]
        expected_instances -= set(removable)

    verification_ran = not any(
        finding["severity"] == "error" for finding in validation_findings
    )
    verification_findings = (
        verify_cutlist_bars(
            bar_reports, kerf=kerf, expected_instances=expected_instances
        )
        if verification_ran
        else []
    )

    drops = [
        {
            "bar_index": report["index"],
            "stock_id": report["stock_id"],
            "designation": report["designation"],
            "grade": report["grade"],
            "length_in": report["drop_in"],
            "status": "candidate_unverified",
        }
        for report in bar_reports
        if report["drop_class"] == "reusable_candidate" and report["drop_in"] > EPS
    ]
    drops.sort(key=lambda drop: (-drop["length_in"], drop["bar_index"]))

    purchase_rows = defaultdict(
        lambda: {"bars": 0, "length_in": 0.0, "cost_known": True, "cost": 0.0}
    )
    for report in bar_reports:
        row = purchase_rows[report["stock_id"]]
        row["bars"] += 1
        row["length_in"] += report["bar_length_in"]
        row["stock_name"] = report["stock"]
        row["stock_kind"] = report["stock_kind"]
        row["designation"] = report["designation"]
        row["grade"] = report["grade"]
        row["bar_length_in"] = report["bar_length_in"]
        if report["bar_cost"] is None:
            row["cost_known"] = False
        else:
            row["cost"] += report["bar_cost"]
    purchase_summary = [
        {
            "stock_id": stock_id,
            "stock_name": row["stock_name"],
            "stock_kind": row["stock_kind"],
            "designation": row["designation"],
            "grade": row["grade"],
            "bar_length_in": row["bar_length_in"],
            "bars_needed": row["bars"],
            "total_length_ft": round(row["length_in"] / 12.0, 2),
            "total_cost": round(row["cost"], 2) if row["cost_known"] else None,
        }
        for stock_id, row in sorted(purchase_rows.items())
    ]

    if unplaced:
        cost_status, cost_total = "incomplete_unplaced", None
    elif all_costs_known:
        cost_status, cost_total = "known", round(total_cost, 2)
    else:
        cost_status, cost_total = "not_provided", None

    metrics = {
        "utilization_pct": {
            "value": round(
                100 * total_cut_length / total_stock_length
                if total_stock_length
                else 0,
                1,
            ),
            "approximation": "exact",
        },
        "total_kerf_in": round(
            sum(report["kerf_total_in"] for report in bar_reports), 3
        ),
    }
    configuration_hash = sha256_bytes(
        canonical_json_bytes(
            {
                "algorithm_version": CUTLIST_ALGORITHM_VERSION,
                "settings": settings,
                "fit_contract": "length-plus-kerf-saturating-v1",
            }
        )
    )
    result = {
        "schema_version": CUTLIST_RESULT_VERSION,
        "algorithm_version": CUTLIST_ALGORITHM_VERSION,
        "normalized_input_hash": normalized_hash,
        "estimate_input_hash": estimate_input_hash,
        "configuration_hash": configuration_hash,
        "outcome": "blocked",
        "package_status": "draft",
        "meta": {
            "job_name": normalized["job_name"],
            "customer": normalized["customer"],
            "project_id": normalized["project_id"],
            "revision_id": normalized["revision_id"],
            "kerf_in": kerf,
            "end_trim_in": settings["end_trim_in"],
            "min_drop_in": min_drop,
            "unit_system": normalized["unit_system"],
        },
        "fit_contract": {
            "usable_length": "bar_length_minus_two_end_trims",
            "piece_fits_when": "length_within_remaining",
            "consumption_per_piece": "length_plus_one_kerf_saturating",
        },
        "bars_used": len(bar_reports),
        "metrics": metrics,
        "total_stock_length_ft": round(total_stock_length / 12.0, 2),
        "total_cut_length_ft": round(total_cut_length / 12.0, 2),
        "total_cut_weight_lbs": (
            round(total_cut_weight, 1) if total_weight_known and bar_reports else None
        ),
        "weight_status": "known" if total_weight_known else "incomplete",
        "cost": {"status": cost_status, "total": cost_total},
        "total_material_cost": cost_total,
        "cost_known": cost_status == "known",
        "bar_reports": bar_reports,
        "purchase_summary": purchase_summary,
        "drops": drops,
        "unplaced": unplaced,
        "validation_findings": validation_findings,
        "verification": {
            "status": (
                "not_run"
                if not verification_ran
                else ("verified" if not verification_findings else "failed")
            ),
            "findings": verification_findings,
        },
    }
    result["rfq_linear"] = rfq_linear_block(result)
    outcome, package_status, _ = stage_decision(result)
    result["outcome"] = outcome
    result["package_status"] = package_status
    return result


def stage_decision(res):
    """Map the independently verified result onto the shared stage contract."""
    findings = list(res.get("validation_findings", []))
    findings.extend(
        {**finding, "severity": "error"}
        for finding in res.get("verification", {}).get("findings", [])
    )
    if res["unplaced"]:
        findings.append(
            {
                "code": "UNPLACED_MEMBERS",
                "severity": "error",
                "path": "$.unplaced",
                "message": (
                    f"{sum(row['quantity'] for row in res['unplaced'])} "
                    "required member(s) remain unplaced."
                ),
            }
        )
    if any(finding["severity"] == "error" for finding in findings):
        outcome = "blocked"
        package_status = "cutlist_partial" if res["unplaced"] else "draft"
    else:
        outcome = "ready"
        package_status = "cutlist_verified"
    return outcome, package_status, findings


def _fmt(value):
    """Decimal-exact display formatting; never rounds shop-relevant digits."""
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


# --------------------------------------------------------------------------
# RFQ hand-off block  (feeds steel-rfq linear stock rows)
# --------------------------------------------------------------------------
def rfq_linear_block(res):
    """Build the versioned cut-list-to-RFQ handoff grouped by stock."""
    rows = []
    for purchase in res["purchase_summary"]:
        matching = [
            report
            for report in res["bar_reports"]
            if report["stock_id"] == purchase["stock_id"]
        ]
        cuts = sum(report["num_cuts"] for report in matching)
        group_bar_length = sum(report["bar_length_in"] for report in matching)
        group_cut_length = sum(report["cut_length_in"] for report in matching)
        group_utilization = (
            round(100 * group_cut_length / group_bar_length, 1)
            if group_bar_length
            else 0.0
        )
        drop_candidates = [
            drop
            for drop in res["drops"]
            if drop["stock_id"] == purchase["stock_id"]
        ][:3]
        drop_text = (
            "; ".join(_fmt(drop["length_in"]) for drop in drop_candidates) or "none"
        )
        rows.append(
            {
                "stock_id": purchase["stock_id"],
                "stock_name": purchase["stock_name"],
                "stock_kind": purchase["stock_kind"],
                "designation": purchase["designation"],
                "grade": purchase["grade"],
                "bar_length_in": purchase["bar_length_in"],
                "bars_needed": purchase["bars_needed"],
                "total_length_ft": purchase["total_length_ft"],
                "utilization_pct": group_utilization,
                "cutting_plan": (
                    f"{purchase['bars_needed']} x "
                    f"{_fmt(purchase['bar_length_in'])} in bar(s) - {cuts} cuts"
                ),
                "drop_notes": (
                    "Drop candidates (not certified reusable): "
                    f"{drop_text} in"
                ),
                "drop_candidates": drop_candidates,
                "total_cost": purchase["total_cost"] if not res["unplaced"] else None,
            }
        )
    return {
        "schema_version": "1.0.0",
        "source_cutlist_result_version": CUTLIST_RESULT_VERSION,
        "project_id": res["meta"]["project_id"],
        "revision_id": res["meta"]["revision_id"],
        "estimate_input_hash": res["estimate_input_hash"],
        "rows": rows,
    }


# --------------------------------------------------------------------------
# Text report
# --------------------------------------------------------------------------
def render_text(res):
    meta = res["meta"]
    lines = ["=" * 64, f"  CUT LIST — {meta['job_name']}"]
    if meta.get("customer"):
        lines.append(f"  Customer: {meta['customer']}")
    lines.append("=" * 64)
    lines.append(
        f"  Kerf {meta['kerf_in']}\"  |  End trim {meta['end_trim_in']}\"/end  |  "
        f"Reusable drop >= {meta['min_drop_in']}\""
    )
    lines.append("")
    lines.append(f"  Bars used .............. {res['bars_used']}")
    utilization = res["metrics"]["utilization_pct"]
    lines.append(f"  Length utilization ..... {utilization['value']}%")
    lines.append(f"  Stock length ........... {res['total_stock_length_ft']} ft")
    lines.append(f"  Cut length ............. {res['total_cut_length_ft']} ft")
    if res["total_cut_weight_lbs"] is not None:
        lines.append(f"  Cut weight ............. {res['total_cut_weight_lbs']} lb")
    else:
        lines.append("  Cut weight ............. incomplete (missing unit weights)")
    if res["cost_known"]:
        lines.append(f"  Material cost (bars) ... ${res['total_material_cost']:,.2f}")
    else:
        lines.append("  Material cost .......... (add cost_per_ft or cost_per_bar to stock)")
    lines.append("")
    lines.append("  " + "-" * 60)
    for report in res["bar_reports"]:
        lines.append(
            f"  BAR {report['index']} — {report['stock']}  "
            f"({_fmt(report['bar_length_in'])} in {report['designation']} {report['grade']})"
        )
        for cut in report["cuts"]:
            lines.append(
                f"    {cut['sequence']:>2}. {cut['label']:<22} {_fmt(cut['length_in'])} in"
            )
        lines.append(
            f"    Cuts {report['num_cuts']}  |  Kerf {report['kerf_total_in']} in  |  "
            f"Drop {report['drop_in']} in ({report['drop_class']})  |  "
            f"Utilization {report['utilization_pct']}%"
        )
        if report["bar_cost"] is not None:
            lines.append(f"    Cost:    ${report['bar_cost']:,.2f}")
        lines.append("")
    if res["purchase_summary"]:
        lines.append("  PURCHASE SUMMARY:")
        for row in res["purchase_summary"]:
            cost_text = (
                f"  ${row['total_cost']:,.2f}" if row["total_cost"] is not None else ""
            )
            on_hand_text = "  (on hand)" if row["stock_kind"] == "on_hand" else ""
            lines.append(
                f"    {row['bars_needed']} x {_fmt(row['bar_length_in'])} in "
                f"{row['designation']} {row['grade']} "
                f"({row['total_length_ft']} ft){cost_text}{on_hand_text}"
            )
        lines.append("")
    if res["drops"]:
        lines.append("  DROP CANDIDATES (not certified reusable):")
        for drop in res["drops"]:
            lines.append(
                f"    Bar {drop['bar_index']}: {_fmt(drop['length_in'])} in "
                f"{drop['designation']} {drop['grade']}"
            )
        lines.append("")
    if res["unplaced"]:
        lines.append("  " + "!" * 60)
        lines.append("  DID NOT FIT (need more/longer stock):")
        for row in res["unplaced"]:
            lines.append(
                f"    - {row['label']} x{row['quantity']} "
                f"({_fmt(row['length_in'])} in {row['designation']}; {row['reason']})"
            )
        lines.append("")
    lines.append("=" * 64)
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Cutting list CSV  (only for verified, fully placed runs)
# --------------------------------------------------------------------------
def render_cutting_list_csv(res):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "Bar",
            "Stock",
            "Designation",
            "Grade",
            "Bar_Length_in",
            "Seq",
            "Mark",
            "Cut_Length_in",
            "Item_ID",
            "Instance_ID",
        ]
    )
    for report in res["bar_reports"]:
        for cut in report["cuts"]:
            writer.writerow(
                [
                    report["index"],
                    report["stock"],
                    report["designation"],
                    report["grade"],
                    _fmt(report["bar_length_in"]),
                    cut["sequence"],
                    cut["label"],
                    _fmt(cut["length_in"]),
                    cut["item_id"],
                    cut["instance_id"],
                ]
            )
    return buffer.getvalue()


# --------------------------------------------------------------------------
# Visual layout  (PNG + combined PDF)
# --------------------------------------------------------------------------
def render_layout(res, outdir, pdf_name="layout.pdf", png_name="bars.png"):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    end_trim = res["meta"]["end_trim_in"]
    kerf = res["meta"]["kerf_in"]
    pdf_path = os.path.join(outdir, pdf_name)
    png_path = os.path.join(outdir, png_name)
    reports = res["bar_reports"]

    with PdfPages(pdf_path) as pdf:
        fig_height = max(2.5, 0.6 * len(reports) + 1.5)
        fig, ax = plt.subplots(figsize=(11, fig_height))
        max_length = max(
            (report["bar_length_in"] for report in reports), default=1.0
        )
        for row, report in enumerate(reports):
            y = len(reports) - row - 1
            bar_length = report["bar_length_in"]
            ax.add_patch(
                mpatches.Rectangle(
                    (0, y + 0.1), bar_length, 0.8, fill=False, lw=1.5, ec="#222"
                )
            )
            cursor = end_trim
            for cut in report["cuts"]:
                ax.add_patch(
                    mpatches.Rectangle(
                        (cursor, y + 0.1),
                        cut["length_in"],
                        0.8,
                        facecolor="#a9c8e8",
                        edgecolor="#1a3b5c",
                        lw=1.0,
                        alpha=0.9,
                    )
                )
                ax.text(
                    cursor + cut["length_in"] / 2,
                    y + 0.5,
                    f"{cut['label']}\n{_fmt(cut['length_in'])}\"",
                    ha="center",
                    va="center",
                    fontsize=6,
                    color="#0c2233",
                )
                cursor += cut["length_in"] + kerf
            if report["drop_in"] > EPS:
                drop_face = (
                    "#bde6bd"
                    if report["drop_class"] == "reusable_candidate"
                    else "#e8e8e8"
                )
                ax.add_patch(
                    mpatches.Rectangle(
                        (bar_length - end_trim - report["drop_in"], y + 0.1),
                        report["drop_in"],
                        0.8,
                        facecolor=drop_face,
                        edgecolor="#666",
                        lw=0.5,
                        alpha=0.7,
                    )
                )
            ax.text(
                -0.01 * max_length,
                y + 0.5,
                f"BAR {report['index']}",
                ha="right",
                va="center",
                fontsize=8,
                fontweight="bold",
            )
        ax.set_xlim(-0.12 * max_length, max_length * 1.02)
        ax.set_ylim(-0.2, len(reports) + 0.2)
        ax.set_yticks([])
        ax.set_xlabel("inches")
        ax.set_title(
            f"CUT LIST — {res['meta']['job_name']}   "
            f"({res['bars_used']} bars, "
            f"{res['metrics']['utilization_pct']['value']}% utilization)",
            fontsize=12,
            fontweight="bold",
        )
        ax.grid(True, axis="x", lw=0.3, color="#eee")
        fig.savefig(png_path, dpi=110, bbox_inches="tight")
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        fig = plt.figure(figsize=(11, 8.5))
        fig.text(0.5, 0.94, "CUT LIST SUMMARY", ha="center", fontsize=18, fontweight="bold")
        fig.text(
            0.06, 0.88, render_text(res), family="monospace", fontsize=7.0, va="top"
        )
        pdf.savefig(fig)
        plt.close(fig)

    return pdf_path, png_path


def missing_render_dependencies():
    """Return optional render modules unavailable to this interpreter."""
    return missing_optional_modules(("matplotlib", "numpy"))


# --------------------------------------------------------------------------
# Publication
# --------------------------------------------------------------------------
def publish_cutlist_run(job, args):
    """Run a cut-list job and publish one isolated, manifested artifact set."""
    result = run_job(job)
    missing_dependencies = [] if args.no_render else missing_render_dependencies()
    if missing_dependencies:
        outcome = "dependency_missing"
        package_status = "draft"
        findings = [
            {
                "code": "RENDER_DEPENDENCY_MISSING",
                "severity": "error",
                "message": (
                    "Rendering requires the missing module(s): "
                    + ", ".join(missing_dependencies)
                ),
            }
        ]
    else:
        outcome, package_status, findings = stage_decision(result)
    result["outcome"] = outcome
    result["run_outcome"] = outcome
    result["package_status"] = package_status
    report = render_text(result)

    configuration = {
        "algorithm_version": CUTLIST_ALGORITHM_VERSION,
        "engine_configuration_hash": result["configuration_hash"],
        "render": not args.no_render,
    }
    publication_configuration_hash = sha256_bytes(canonical_json_bytes(configuration))
    qa_report = {
        "schema_version": "1.0.0",
        "stage": "steel-cutlist",
        "run_outcome": outcome,
        "package_status": package_status,
        "findings": findings,
    }
    with RunPublisher(
        args.out,
        stage="steel-cutlist",
        run_outcome=outcome,
        package_status=package_status,
        input_hash=result["normalized_input_hash"],
        configuration_hash=publication_configuration_hash,
        schema_versions={
            "run_manifest": "1.0.0",
            "cutlist_result": CUTLIST_RESULT_VERSION,
            "rfq_linear": "1.0.0",
        },
        tool_versions={
            "pi_steel": package_version(__file__),
            "cutlist_algorithm": CUTLIST_ALGORITHM_VERSION,
        },
        explicit_dates={},
        warnings=[
            finding["message"]
            for finding in findings
            if finding["severity"] in {"error", "warning"}
        ],
        approximations=[],
        run_id=args.run_id,
    ) as publisher:
        publisher.write_qa_report(qa_report)
        publisher.write_bytes(
            "report.txt",
            report.encode("utf-8"),
            readiness="diagnostic",
            media_type="text/plain",
        )
        publisher.write_json("result.json", result, readiness="diagnostic")
        if outcome == "ready":
            publisher.write_json(
                "rfq_linear.json", result["rfq_linear"], readiness="diagnostic"
            )
            publisher.write_bytes(
                "cutting_list.csv",
                render_cutting_list_csv(result).encode("utf-8"),
                readiness="geometry_verified",
                media_type="text/csv",
            )
        if (
            not args.no_render
            and not missing_dependencies
            and result["bar_reports"]
        ):
            publisher.register_artifact(
                "layout.pdf", readiness="reference_only", media_type="application/pdf"
            )
            publisher.register_artifact(
                "bars.png", readiness="reference_only", media_type="image/png"
            )
            render_layout(result, publisher.staging_path)
        final_path = publisher.publish()

    return result, qa_report, report, final_path


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main(argv=None):
    parser = StageArgumentParser(description="Steel linear cut-list engine")
    parser.configure_failure_diagnostics(
        stage="steel-cutlist",
        entry_file=__file__,
        input_option="--job",
    )
    parser.add_argument("--job", required=True)
    parser.add_argument(
        "--out",
        default="outputs",
        help="Publication root; each invocation writes an isolated runs/<run-id>/",
    )
    parser.add_argument("--no-render", action="store_true", help="Skip PDF/PNG")
    parser.add_argument("--run-id", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    try:
        with open(args.job, encoding="utf-8") as handle:
            job = json.load(handle)
        result, qa_report, report, final_path = publish_cutlist_run(job, args)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        diagnostic_path = publish_failure_diagnostic(
            args.out,
            stage="steel-cutlist",
            input_path=args.job,
            error=exc,
            tool_version=package_version(__file__),
            run_id=args.run_id,
        )
        suffix = (
            f"; diagnostic published: {diagnostic_path}"
            if diagnostic_path is not None
            else "; diagnostic publication unavailable"
        )
        print(f"Cut-list failed: {exc}{suffix}", file=sys.stderr)
        return 1
    print(report)
    print(f"\nPublished {qa_report['run_outcome']} run: {final_path}")
    return outcome_exit_code(qa_report["run_outcome"])


if __name__ == "__main__":
    raise SystemExit(main())
