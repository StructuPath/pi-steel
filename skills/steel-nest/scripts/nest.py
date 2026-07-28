#!/usr/bin/env python3
"""
Steel plate nesting engine  (rectangular / bounding-box)
=========================================================
A self-contained nesting + estimating tool for a fabrication shop.

Reliable:
  * Nests parts onto stock plates with a MaxRects bin-packing algorithm
    (rotation, kerf + gap spacing, edge margin, multiple plate sizes,
    greedy multi-plate fill). Rectangular parts nest exactly.
  * Rectangular parts can carry HOLES (round) and rectangular CUTOUTS --
    subtracted from weight/cost, rotated with the part, drawn in the layout,
    and emitted as cut geometry only after the complete job passes its gate.
  * Separate packing utilization and net material yield, part/plate weight,
    optional reconciled cost, and unverified remnant candidates.
  * Labeled layout (PNG per plate + combined PDF).
  * DXF outputs:
      - reference_nest.dxf    all plates side-by-side (reference only)
      - reference_plate_N.dxf one reference-only file per used plate
      - burn_plate_N.dxf      ONE FILE PER SHEET for the burn table when
                              every part is rectangular, every required part
                              fits, and supported holes stay inside the part.

Deliberately NOT done:
  * True-shape nesting of irregular parts (they nest by BOUNDING BOX,
    clearly flagged). Supply a part `area` for exact weight on those.
  * Machine-ready G-code / NC with kerf comp, pierce points and lead-ins
    for a specific controller. The burn-table DXF is an import file; the
    machine's own CAM/post applies those (that is where they belong).

Usage:
  python3 nest.py --job job.json --out published/

The output root receives isolated runs/<run-id>/ directories plus a
latest-run.json pointer. Exit 0 is ready, 2 requires review, and 3 is blocked.
"""

import argparse
import importlib.util
import json
import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


SHARED_ROOT = Path(__file__).resolve().parents[2] / "_shared"
if str(SHARED_ROOT) not in sys.path:
    sys.path.insert(0, str(SHARED_ROOT))
from bootstrap import bootstrap_shared  # noqa: E402

bootstrap_shared(__file__)
from pi_steel import (  # noqa: E402
    NEST_RESULT_VERSION,
    RunPublisher,
    canonical_json_bytes,
    item_id_for,
    outcome_exit_code,
    placement_ids,
    sha256_bytes,
)
from pi_steel.contracts import content_hash, fallback_source_id, instance_ids  # noqa: E402
from pi_steel.geometry_verify import (  # noqa: E402
    SUPPORTED_SHAPES,
    finite_positive,
    hole_within_bounds,
    verify_nest_placements,
)

STEEL_DENSITY = 0.2836  # lb/in^3, A36 mild steel
NEST_ALGORITHM_VERSION = "maxrects-bssf-u3"


class StageArgumentParser(argparse.ArgumentParser):
    """Use the shared stage contract's exit 1 for command usage errors."""

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


# --------------------------------------------------------------------------
# Geometry primitives
# --------------------------------------------------------------------------
@dataclass
class FreeRect:
    x: float
    y: float
    w: float
    h: float


@dataclass
class Placement:
    part_id: str
    source_id: str
    item_id: str
    instance_id: str
    placement_id: str
    stock_id: str
    label: str
    x: float                 # placed lower-left, usable (post-margin) coords
    y: float
    w: float                 # placed footprint (post-rotation)
    h: float
    rotated: bool
    shape: str               # "rect" | "irregular"
    ow: float                # original (unrotated) part width
    oh: float                # original (unrotated) part height
    holes: list = field(default_factory=list)   # in original part coords
    base_area: float = 0.0   # gross area (bbox for rect, declared area for irregular)
    holes_area: float = 0.0  # total area removed by holes/cutouts
    material: str = ""
    grade: str = ""
    thickness: float = 0.0


class MaxRectsBin:
    """One stock plate packed with MaxRects (Best-Short-Side-Fit)."""

    EPS = 1e-9

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.free = [FreeRect(0.0, 0.0, width, height)]
        self.placements = []

    def insert(self, w, h, allow_rotate=True):
        best = self._find(w, h, allow_rotate)
        if best is None:
            return None
        x, y, pw, ph, rotated = best
        self._place_and_split(x, y, pw, ph)
        return best

    def _find(self, w, h, allow_rotate):
        best_short = math.inf
        best_long = math.inf
        best = None
        candidates = [(w, h, False)]
        if allow_rotate:
            candidates.append((h, w, True))
        for fr in self.free:
            for cw, ch, rot in candidates:
                if fr.w + self.EPS >= cw and fr.h + self.EPS >= ch:
                    lh = abs(fr.w - cw)
                    lv = abs(fr.h - ch)
                    short = min(lh, lv)
                    long_ = max(lh, lv)
                    if (short < best_short - self.EPS or
                            (abs(short - best_short) <= self.EPS and long_ < best_long)):
                        best_short, best_long = short, long_
                        best = (fr.x, fr.y, cw, ch, rot)
        return best

    def _place_and_split(self, x, y, w, h):
        placed = FreeRect(x, y, w, h)
        new_free = []
        for fr in self.free:
            if self._overlaps(fr, placed):
                new_free.extend(self._split(fr, placed))
            else:
                new_free.append(fr)
        self.free = new_free
        self._prune()

    @classmethod
    def _overlaps(cls, a, b):
        return not (b.x >= a.x + a.w - cls.EPS or b.x + b.w <= a.x + cls.EPS or
                    b.y >= a.y + a.h - cls.EPS or b.y + b.h <= a.y + cls.EPS)

    @classmethod
    def _split(cls, fr, placed):
        out = []
        if placed.x > fr.x + cls.EPS:
            out.append(FreeRect(fr.x, fr.y, placed.x - fr.x, fr.h))
        if placed.x + placed.w < fr.x + fr.w - cls.EPS:
            out.append(FreeRect(placed.x + placed.w, fr.y,
                                fr.x + fr.w - (placed.x + placed.w), fr.h))
        if placed.y > fr.y + cls.EPS:
            out.append(FreeRect(fr.x, fr.y, fr.w, placed.y - fr.y))
        if placed.y + placed.h < fr.y + fr.h - cls.EPS:
            out.append(FreeRect(fr.x, placed.y + placed.h, fr.w,
                                fr.y + fr.h - (placed.y + placed.h)))
        return out

    def _prune(self):
        n = len(self.free)
        dead = [False] * n
        for i in range(n):
            if dead[i]:
                continue
            for j in range(n):
                if i == j or dead[j]:
                    continue
                if self._contains(self.free[j], self.free[i]):
                    dead[i] = True
                    break
        self.free = [f for k, f in enumerate(self.free)
                     if not dead[k] and f.w > 1e-6 and f.h > 1e-6]

    @classmethod
    def _contains(cls, outer, inner):
        return (inner.x >= outer.x - cls.EPS and inner.y >= outer.y - cls.EPS and
                inner.x + inner.w <= outer.x + outer.w + cls.EPS and
                inner.y + inner.h <= outer.y + outer.h + cls.EPS)

# --------------------------------------------------------------------------
# Holes
# --------------------------------------------------------------------------
def hole_area(hole):
    """Area removed by a single hole/cutout (in^2)."""
    if hole.get("dia") is not None:
        return math.pi * (float(hole["dia"]) / 2.0) ** 2
    if hole.get("w") is not None and hole.get("h") is not None:   # rect cutout
        return float(hole["w"]) * float(hole["h"])
    return 0.0


def hole_local(pc, hole):
    """
    Hole center in the PLACED part's local frame (0..pw, 0..ph),
    accounting for a 90-degree rotation. `pc` is a placement dict.
    """
    hx, hy = float(hole["x"]), float(hole["y"])
    if pc["rotated"]:
        # 90deg CCW: (x,y) -> (oh - y, x) inside placed box (oh wide, ow tall)
        return pc["oh"] - hy, hx
    return hx, hy


# --------------------------------------------------------------------------
# Job runner
# --------------------------------------------------------------------------
def _legacy_hole_to_canonical(hole):
    if hole.get("dia") is not None:
        return {
            "kind": "round",
            "diameter": hole.get("dia"),
            "x": hole.get("x"),
            "y": hole.get("y"),
        }
    return {
        "kind": "rect",
        "width": hole.get("w"),
        "height": hole.get("h"),
        "x": hole.get("x"),
        "y": hole.get("y"),
    }


def _validation_finding(code, path, message, severity="error"):
    return {
        "code": code,
        "severity": severity,
        "path": path,
        "message": message,
    }


def normalize_job(job):
    """Normalize and validate the legacy direct-use JSON before any placement."""
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

    kerf = number(settings.get("kerf_in", 0.06), "$.settings.kerf_in", nonnegative=True)
    gap = number(settings.get("part_gap_in", 0.25), "$.settings.part_gap_in", nonnegative=True)
    margin = number(
        settings.get("edge_margin_in", 0.5),
        "$.settings.edge_margin_in",
        nonnegative=True,
    )
    density = number(
        settings.get("density_lb_in3", STEEL_DENSITY),
        "$.settings.density_lb_in3",
        positive=True,
    )
    unit_system = job.get("unit_system")
    if unit_system is None:
        findings.append(
            _validation_finding(
                "missing_unit_basis",
                "$.unit_system",
                "The direct nesting engine requires an explicit imperial unit basis.",
            )
        )
    elif unit_system != "imperial":
        findings.append(
            _validation_finding(
                "unsupported_unit_system",
                "$.unit_system",
                "The direct nesting engine currently requires imperial inches.",
            )
        )

    project_id = job.get("project_id") or job.get("job_name") or "LEGACY-NEST"
    revision_id = job.get("revision_id", "LEGACY-REVISION")
    default_material = job.get("material")
    default_grade = job.get("grade")
    default_thickness = settings.get("thickness_in")
    parts = []
    for index, part in enumerate(job.get("parts", [])):
        path = f"$.parts[{index}]"
        width = number(part.get("width"), f"{path}.width", positive=True)
        height = number(part.get("height"), f"{path}.height", positive=True)
        thickness = number(
            part.get("thickness", default_thickness),
            f"{path}.thickness",
            positive=True,
        )
        try:
            quantity = int(part.get("qty", 1))
            quantity_valid = quantity > 0 and quantity == float(part.get("qty", 1))
        except (TypeError, ValueError):
            quantity, quantity_valid = 0, False
        if not quantity_valid:
            findings.append(
                _validation_finding(
                    "invalid_quantity", f"{path}.qty", "Quantity must be a positive integer."
                )
            )
        shape = part.get("shape", "rect")
        if shape not in SUPPORTED_SHAPES:
            findings.append(
                _validation_finding(
                    "unsupported_shape",
                    f"{path}.shape",
                    "Supported shapes are rect and irregular.",
                )
            )
        material = part.get("material", default_material)
        grade = part.get("grade", default_grade)
        if not material or not grade or not finite_positive(thickness):
            findings.append(
                _validation_finding(
                    "missing_material_basis",
                    path,
                    "Material, grade, and thickness must be explicit before placement.",
                )
            )
        holes = part.get("holes", []) or []
        holes_area = 0.0
        if finite_positive(width) and finite_positive(height):
            for hole_index, hole in enumerate(holes):
                if not hole_within_bounds(
                    _legacy_hole_to_canonical(hole), width, height
                ):
                    findings.append(
                        _validation_finding(
                            "invalid_hole_geometry",
                            f"{path}.holes[{hole_index}]",
                            "Hole is unsupported or extends outside the part.",
                        )
                    )
                try:
                    holes_area += hole_area(hole)
                except (TypeError, ValueError):
                    pass
        base_area = width * height if finite_positive(width) and finite_positive(height) else 0
        approximation = "exact"
        if shape == "irregular":
            if part.get("area") is None:
                approximation = "bounding_box_estimate"
                findings.append(
                    _validation_finding(
                        "missing_irregular_area",
                        f"{path}.area",
                        "Irregular net area is approximated by its bounding box.",
                        severity="warning",
                    )
                )
            else:
                declared_area = number(part.get("area"), f"{path}.area", positive=True)
                if math.isfinite(declared_area) and declared_area > base_area + 1e-9:
                    findings.append(
                        _validation_finding(
                            "invalid_irregular_area",
                            f"{path}.area",
                            "Declared irregular area cannot exceed its bounding box.",
                        )
                    )
                base_area = declared_area
                approximation = "declared_area"
        if base_area - holes_area <= 0:
            findings.append(
                _validation_finding(
                    "nonpositive_net_area",
                    path,
                    "Part net area after holes must be greater than zero.",
                )
            )
        explicit_source = part.get("source_id")
        source_id = explicit_source or fallback_source_id(
            revision_id,
            {
                key: part.get(key)
                for key in (
                    "name",
                    "material",
                    "grade",
                    "thickness",
                    "width",
                    "height",
                    "shape",
                )
            },
        )
        item_id = part.get("item_id") or item_id_for(
            project_id, revision_id, source_id
        )
        parts.append(
            {
                "source_id": source_id,
                "item_id": item_id,
                "label": part.get("name", source_id),
                "w": width,
                "h": height,
                "quantity": quantity,
                "rotatable": bool(part.get("rotatable", True)),
                "shape": shape,
                "holes": holes,
                "base_area": base_area,
                "holes_area": holes_area,
                "net_area_approximation": approximation,
                "material": material,
                "grade": grade,
                "thickness": thickness,
            }
        )

    stock_types = []
    for index, stock in enumerate(job.get("stock", [])):
        path = f"$.stock[{index}]"
        width = number(stock.get("width"), f"{path}.width", positive=True)
        height = number(stock.get("height"), f"{path}.height", positive=True)
        thickness = number(
            stock.get("thickness", default_thickness),
            f"{path}.thickness",
            positive=True,
        )
        material = stock.get("material", default_material)
        grade = stock.get("grade", default_grade)
        if not material or not grade or not finite_positive(thickness):
            findings.append(
                _validation_finding(
                    "missing_material_basis",
                    path,
                    "Stock material, grade, and thickness must be explicit.",
                )
            )
        unlimited = bool(stock.get("unlimited", False))
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
        per_pound = stock.get("cost_per_lb")
        per_sheet = stock.get("cost_per_sheet")
        if per_pound is not None and per_sheet is not None:
            findings.append(
                _validation_finding(
                    "conflicting_cost_basis",
                    path,
                    "Use either cost_per_lb or cost_per_sheet for one stock entry, not both.",
                )
            )
        for field, value in (
            ("cost_per_lb", per_pound),
            ("cost_per_sheet", per_sheet),
        ):
            if value is not None:
                parsed_cost = number(value, f"{path}.{field}", nonnegative=True)
                if field == "cost_per_lb":
                    per_pound = parsed_cost
                else:
                    per_sheet = parsed_cost
        stock_id = stock.get("stock_id") or (
            "stock:"
            + content_hash(
                {
                    "name": stock.get("name", "Plate"),
                    "material": material,
                    "grade": grade,
                    "thickness": thickness,
                    "width": width,
                    "height": height,
                }
            )[:24]
        )
        stock_types.append(
            {
                "stock_id": stock_id,
                "name": stock.get("name", "Plate"),
                "material": material,
                "grade": grade,
                "W": width,
                "H": height,
                "thickness": thickness,
                "qty": quantity,
                "cost_per_lb": per_pound,
                "cost_per_sheet": per_sheet,
                "used": 0,
            }
        )
    for collection_name, values, identity_field in (
        ("parts", parts, "item_id"),
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
    parts.sort(key=lambda part: part["item_id"])
    stock_types.sort(key=lambda stock: stock["stock_id"])
    if not parts:
        findings.append(
            _validation_finding("missing_parts", "$.parts", "At least one part is required.")
        )
    if not stock_types:
        findings.append(
            _validation_finding("missing_stock", "$.stock", "At least one stock entry is required.")
        )
    normalized = {
        "job_name": job.get("job_name", "Nesting job"),
        "customer": job.get("customer", ""),
        "unit_system": unit_system or "unspecified",
        "settings": {
            "kerf_in": kerf,
            "part_gap_in": gap,
            "edge_margin_in": margin,
            "density_lb_in3": density,
        },
        "parts": parts,
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


def _material_key(value):
    return value.get("material"), value.get("grade"), value.get("thickness")


def _aggregate_unplaced(units):
    grouped = {}
    for unit in units:
        key = (unit["item_id"], unit["reason"])
        row = grouped.setdefault(
            key,
            {
                "item_id": unit["item_id"],
                "label": unit["label"],
                "quantity": 0,
                "size": f'{_fmt(unit["w"])} x {_fmt(unit["h"])}',
                "reason": unit["reason"],
            },
        )
        row["quantity"] += 1
    return sorted(grouped.values(), key=lambda row: (row["item_id"], row["reason"]))


def run_job(job):
    normalized, stock_types, validation_findings = normalize_job(job)
    settings = normalized["settings"]
    kerf = settings["kerf_in"]
    gap = settings["part_gap_in"]
    margin = settings["edge_margin_in"]
    density = settings["density_lb_in3"]
    spacing = kerf + gap
    normalized_hash = sha256_bytes(canonical_json_bytes(normalized))
    blockers = [
        finding
        for finding in validation_findings
        if finding["severity"] == "error"
    ]
    if blockers:
        return _summarize(
            normalized,
            [],
            [],
            density,
            margin,
            kerf,
            gap,
            validation_findings,
            normalized_hash,
        )

    units = []
    for part in normalized["parts"]:
        item_instances = instance_ids(part["item_id"], part["quantity"])
        item_placements = placement_ids(part["item_id"], part["quantity"])
        for index in range(part["quantity"]):
            units.append(
                {
                    **part,
                    "part_id": part["item_id"],
                    "instance_id": item_instances[index],
                    "placement_id": item_placements[index],
                }
            )
    units.sort(key=lambda unit: (-unit["w"] * unit["h"], unit["instance_id"]))
    plates = []

    def compatible(stock, unit):
        return _material_key(stock) == _material_key(unit)

    def can_fit(stock, unit):
        usable_width = stock["W"] - 2 * margin
        usable_height = stock["H"] - 2 * margin
        direct = unit["w"] <= usable_width + 1e-9 and unit["h"] <= usable_height + 1e-9
        rotated = (
            unit["rotatable"]
            and unit["h"] <= usable_width + 1e-9
            and unit["w"] <= usable_height + 1e-9
        )
        return compatible(stock, unit) and (direct or rotated)

    def open_plate(unit):
        for stock in stock_types:
            if stock["used"] >= stock["qty"] or not can_fit(stock, unit):
                continue
            usable_width = stock["W"] - 2 * margin
            usable_height = stock["H"] - 2 * margin
            stock["used"] += 1
            plate = {
                "stock": stock,
                "bin": MaxRectsBin(usable_width + spacing, usable_height + spacing),
                "placements": [],
            }
            plates.append(plate)
            return plate
        return None

    def commit(plate, unit, placement):
        x, y, packed_width, packed_height, rotated = placement
        plate["placements"].append(
            Placement(
                part_id=unit["part_id"],
                source_id=unit["source_id"],
                item_id=unit["item_id"],
                instance_id=unit["instance_id"],
                placement_id=unit["placement_id"],
                stock_id=plate["stock"]["stock_id"],
                label=unit["label"],
                x=x,
                y=y,
                w=packed_width - spacing,
                h=packed_height - spacing,
                rotated=rotated,
                shape=unit["shape"],
                ow=unit["w"],
                oh=unit["h"],
                holes=unit["holes"],
                base_area=unit["base_area"],
                holes_area=unit["holes_area"],
                material=unit["material"],
                grade=unit["grade"],
                thickness=unit["thickness"],
            )
        )

    unplaced_units = []
    for unit in units:
        compatible_stock = [
            stock for stock in stock_types if can_fit(stock, unit)
        ]
        if not compatible_stock:
            unplaced_units.append({**unit, "reason": "no_compatible_stock_fit"})
            continue
        packed_width, packed_height = unit["w"] + spacing, unit["h"] + spacing
        placed = False
        for plate in plates:
            if not compatible(plate["stock"], unit):
                continue
            placement = plate["bin"].insert(
                packed_width, packed_height, unit["rotatable"]
            )
            if placement:
                commit(plate, unit, placement)
                placed = True
                break
        if not placed:
            plate = open_plate(unit)
            if plate is not None:
                placement = plate["bin"].insert(
                    packed_width, packed_height, unit["rotatable"]
                )
                if placement:
                    commit(plate, unit, placement)
                    placed = True
        if not placed:
            unplaced_units.append({**unit, "reason": "stock_exhausted"})

    used_plates = [plate for plate in plates if plate["placements"]]
    for index, plate in enumerate(used_plates, 1):
        plate["index"] = index
    return _summarize(
        normalized,
        used_plates,
        _aggregate_unplaced(unplaced_units),
        density,
        margin,
        kerf,
        gap,
        validation_findings,
        normalized_hash,
    )


def _metric(value, approximation):
    return {"value": round(value, 1), "approximation": approximation}


def _remnant_candidates(plate, margin, spacing):
    stock = plate["stock"]
    usable_width = stock["W"] - 2 * margin
    usable_height = stock["H"] - 2 * margin
    candidates = []
    for free in plate["bin"].free:
        width = max(0.0, min(free.w, usable_width - free.x))
        height = max(0.0, min(free.h, usable_height - free.y))
        if width > spacing and height > spacing:
            candidates.append(
                {
                    "width": round(width, 2),
                    "height": round(height, 2),
                    "area": round(width * height, 2),
                    "status": "candidate_unverified",
                }
            )
    return sorted(
        candidates, key=lambda candidate: candidate["area"], reverse=True
    )[:3]


def _summarize(
    normalized,
    used_plates,
    unplaced,
    density,
    margin,
    kerf,
    gap,
    validation_findings,
    normalized_hash,
):
    plate_reports = []
    total_plate_area = total_packing_area = total_net_area = 0.0
    total_plate_weight = total_part_weight = 0.0
    total_cost = 0.0
    all_used_costs_known = bool(used_plates)
    part_net_cost = {}
    has_irregular = any(part["shape"] == "irregular" for part in normalized["parts"])
    net_approximations = {
        part["net_area_approximation"] for part in normalized["parts"]
    }

    for plate in used_plates:
        stock = plate["stock"]
        width, height, thickness = stock["W"], stock["H"], stock["thickness"]
        plate_area = width * height
        plate_weight = plate_area * thickness * density
        packing_area = net_area_total = part_weight = 0.0
        holes = 0
        parts_on = {}
        for placement in plate["placements"]:
            packing_area += placement.w * placement.h
            net_area = max(0.0, placement.base_area - placement.holes_area)
            net_area_total += net_area
            weight = net_area * thickness * density
            part_weight += weight
            holes += len(placement.holes)
            parts_on[placement.label] = parts_on.get(placement.label, 0) + 1
            if stock["cost_per_lb"] is not None:
                part_net_cost[placement.label] = (
                    part_net_cost.get(placement.label, 0.0)
                    + weight * stock["cost_per_lb"]
                )

        if stock["cost_per_sheet"] is not None:
            plate_cost = stock["cost_per_sheet"]
            cost_basis = "per_sheet"
        elif stock["cost_per_lb"] is not None:
            plate_cost = plate_weight * stock["cost_per_lb"]
            cost_basis = "per_pound"
        else:
            plate_cost = None
            cost_basis = None
            all_used_costs_known = False
        if plate_cost is not None:
            total_cost += plate_cost
        packing_approximation = "bounding_box" if any(
            placement.shape == "irregular" for placement in plate["placements"]
        ) else "exact"
        plate_net_statuses = {
            next(
                part["net_area_approximation"]
                for part in normalized["parts"]
                if part["item_id"] == placement.item_id
            )
            for placement in plate["placements"]
        }
        net_approximation = (
            "exact"
            if plate_net_statuses == {"exact"}
            else (
                "bounding_box_estimate"
                if "bounding_box_estimate" in plate_net_statuses
                else "declared_area"
            )
        )
        report = {
            "index": plate["index"],
            "stock": stock["name"],
            "stock_id": stock["stock_id"],
            "material": stock["material"],
            "grade": stock["grade"],
            "size": f"{_fmt(width)} x {_fmt(height)} x {_fmt(thickness)}",
            "W": width,
            "H": height,
            "thickness": thickness,
            "parts": parts_on,
            "num_parts": len(plate["placements"]),
            "num_holes": holes,
            "packing_utilization_pct": _metric(
                100 * packing_area / plate_area, packing_approximation
            ),
            "net_material_yield_pct": _metric(
                100 * net_area_total / plate_area, net_approximation
            ),
            "plate_weight_lb": round(plate_weight, 1),
            "part_weight_lb": round(part_weight, 1),
            "scrap_weight_lb": round(plate_weight - part_weight, 1),
            "plate_cost": None if plate_cost is None else round(plate_cost, 2),
            "cost_basis": cost_basis,
            "remnant_candidates": _remnant_candidates(plate, margin, kerf + gap),
            "placements": [vars(placement) for placement in plate["placements"]],
        }
        plate_reports.append(report)
        total_plate_area += plate_area
        total_packing_area += packing_area
        total_net_area += net_area_total
        total_plate_weight += plate_weight
        total_part_weight += part_weight

    if unplaced:
        cost_status, cost_total = "incomplete_unplaced", None
    elif all_used_costs_known:
        cost_status, cost_total = "known", round(total_cost, 2)
    else:
        cost_status, cost_total = "not_provided", None
    packing_status = "bounding_box" if has_irregular else "exact"
    net_status = (
        "bounding_box_estimate"
        if "bounding_box_estimate" in net_approximations
        else ("declared_area" if "declared_area" in net_approximations else "exact")
    )
    metrics = {
        "packing_utilization_pct": _metric(
            100 * total_packing_area / total_plate_area if total_plate_area else 0,
            packing_status,
        ),
        "net_material_yield_pct": _metric(
            100 * total_net_area / total_plate_area if total_plate_area else 0,
            net_status,
        ),
    }
    verification_findings = verify_nest_placements(
        plate_reports,
        edge_margin=margin,
        inter_part_clearance=kerf + gap,
    )
    invalid_holes = [
        finding["message"]
        for finding in validation_findings
        if finding["code"] == "invalid_hole_geometry"
    ]
    blockers = [
        finding
        for finding in validation_findings
        if finding["severity"] == "error"
    ]
    burn_warnings = []
    if has_irregular:
        burn_warnings.append(
            "Irregular parts use approximate bounding boxes; burn DXFs are suppressed."
        )
    if unplaced:
        burn_warnings.append(
            f"{sum(row['quantity'] for row in unplaced)} required part(s) did not fit; "
            "burn DXFs are suppressed."
        )
    burn_warnings.extend(invalid_holes)
    burn_warnings.extend(finding["message"] for finding in verification_findings)
    burn_warnings.extend(
        finding["message"] for finding in blockers if finding["code"] != "invalid_hole_geometry"
    )
    if blockers or unplaced or verification_findings:
        geometry_readiness = "diagnostic"
    elif has_irregular:
        geometry_readiness = "reference_only"
    else:
        geometry_readiness = "geometry_verified"

    groups = []
    group_keys = sorted(
        {_material_key(part) for part in normalized["parts"]}, key=repr
    )
    for material, grade, thickness in group_keys:
        placements = [
            placement
            for plate in plate_reports
            for placement in plate["placements"]
            if (
                placement["material"],
                placement["grade"],
                placement["thickness"],
            )
            == (material, grade, thickness)
        ]
        groups.append(
            {
                "group_id": "nest-group:"
                + content_hash(
                    {
                        "material": material,
                        "grade": grade,
                        "thickness": thickness,
                    }
                )[:20],
                "material": material,
                "grade": grade,
                "thickness": thickness,
                "placements": placements,
            }
        )
    configuration_hash = sha256_bytes(
        canonical_json_bytes(
            {
                "algorithm_version": NEST_ALGORITHM_VERSION,
                "settings": normalized["settings"],
                "clearance_contract": "edge-margin-and-inter-part-v1",
            }
        )
    )
    result = {
        "schema_version": NEST_RESULT_VERSION,
        "algorithm_version": NEST_ALGORITHM_VERSION,
        "normalized_input_hash": normalized_hash,
        "estimate_input_hash": normalized_hash,
        "configuration_hash": configuration_hash,
        "outcome": "blocked",
        "package_status": "draft",
        "meta": {
            "job_name": normalized["job_name"],
            "customer": normalized["customer"],
            "kerf_in": kerf,
            "part_gap_in": gap,
            "edge_margin_in": margin,
            "density_lb_in3": density,
            "unit_system": normalized["unit_system"],
        },
        "clearance_contract": {
            "edge_margin_ownership": "plate_to_part",
            "inter_part_clearance_ownership": "kerf_plus_gap",
            "trailing_clearance_required_at_plate_edge": False,
        },
        "groups": groups,
        "plates_used": len(plate_reports),
        "metrics": metrics,
        "total_plate_weight_lb": round(total_plate_weight, 1),
        "total_part_weight_lb": round(total_part_weight, 1),
        "total_scrap_weight_lb": round(total_plate_weight - total_part_weight, 1),
        "cost": {"status": cost_status, "total": cost_total},
        "total_material_cost": cost_total,
        "cost_known": cost_status == "known",
        "total_holes": sum(report["num_holes"] for report in plate_reports),
        "part_net_cost": {
            key: round(value, 2) for key, value in part_net_cost.items()
        },
        "plate_reports": plate_reports,
        "unplaced": unplaced,
        "has_irregular": has_irregular,
        "invalid_hole_warnings": invalid_holes,
        "validation_findings": validation_findings,
        "verification": {
            "status": "verified" if not verification_findings else "failed",
            "findings": verification_findings,
        },
        "geometry_readiness": geometry_readiness,
        "burn_dxf_eligible": not burn_warnings,
        "burn_dxf_warnings": burn_warnings,
    }
    result["rfq_nesting"] = rfq_nesting_block(result)
    outcome, package_status, _ = stage_decision(result)
    result["outcome"] = outcome
    result["package_status"] = package_status
    return result


def _fmt(v):
    return f"{v:g}"


# --------------------------------------------------------------------------
# RFQ hand-off block  (feeds steel-rfq "Nesting / Drop Reference" table)
# --------------------------------------------------------------------------
def rfq_nesting_block(res):
    """Build the versioned nest-to-RFQ handoff without merging stock variants."""
    from collections import defaultdict
    groups = defaultdict(list)
    for pr in res["plate_reports"]:
        groups[
            (
                pr["stock_id"],
                pr["material"],
                pr["grade"],
                pr["thickness"],
                pr["W"],
                pr["H"],
            )
        ].append(pr)

    blocks = []
    for key, prs in sorted(groups.items(), key=lambda item: repr(item[0])):
        stock_id, material, grade, thickness, width, height = key
        sheets = len(prs)
        packing_area = sum(
            pr["packing_utilization_pct"]["value"] / 100 * pr["W"] * pr["H"]
            for pr in prs
        )
        total_area = sum(pr["W"] * pr["H"] for pr in prs)
        utilization = round(100 * packing_area / total_area, 1) if total_area else 0.0
        parts = sum(pr["num_parts"] for pr in prs)
        candidates = sorted(
            [
                candidate
                for pr in prs
                for candidate in pr["remnant_candidates"]
            ],
            key=lambda candidate: candidate["area"],
            reverse=True,
        )[:3]
        candidate_text = (
            "; ".join(
                f"{_fmt(candidate['width'])}x{_fmt(candidate['height'])}"
                for candidate in candidates
            )
            or "none"
        )
        costs_known = all(pr["plate_cost"] is not None for pr in prs)
        cost = sum(pr["plate_cost"] for pr in prs if pr["plate_cost"] is not None)
        blocks.append({
            "stock_id": stock_id,
            "stock_name": prs[0]["stock"],
            "material": material,
            "grade": grade,
            "thickness": thickness,
            "sheets_needed": sheets,
            "sheet_size": f"{_fmt(width)}x{_fmt(height)}",
            "packing_utilization_pct": utilization,
            "nesting_plan": (
                f"{sheets} x {_fmt(width)}x{_fmt(height)} sheet(s) - "
                f"{utilization}% packing utilization, {parts} parts"
            ),
            "drop_notes": (
                f"Remnant candidates (not certified reusable): {candidate_text} in"
            ),
            "remnant_candidates": candidates,
            "total_cost": round(cost, 2) if costs_known and not res["unplaced"] else None,
        })
    return {
        "schema_version": "1.0.0",
        "source_nest_result_version": NEST_RESULT_VERSION,
        "rows": blocks,
    }


# --------------------------------------------------------------------------
# Text report
# --------------------------------------------------------------------------
def render_text(res):
    m = res["meta"]
    L = ["=" * 64, f"  NEST REPORT — {m['job_name']}"]
    if m.get("customer"):
        L.append(f"  Customer: {m['customer']}")
    L.append("=" * 64)
    L.append(f"  Kerf {m['kerf_in']}\"  |  Part gap {m['part_gap_in']}\"  |  "
             f"Edge margin {m['edge_margin_in']}\"  |  {m['density_lb_in3']} lb/in^3")
    L.append("")
    L.append(f"  Plates used ............ {res['plates_used']}")
    packing = res["metrics"]["packing_utilization_pct"]
    net_yield = res["metrics"]["net_material_yield_pct"]
    L.append(
        f"  Packing utilization ... {packing['value']}% "
        f"({packing['approximation']})"
    )
    L.append(
        f"  Net material yield .... {net_yield['value']}% "
        f"({net_yield['approximation']})"
    )
    L.append(f"  Holes / cutouts ........ {res['total_holes']}")
    L.append(f"  Total plate weight ..... {res['total_plate_weight_lb']} lb")
    L.append(f"  Net part weight ........ {res['total_part_weight_lb']} lb  (holes removed)")
    L.append(f"  Scrap weight ........... {res['total_scrap_weight_lb']} lb")
    if res["cost_known"]:
        L.append(f"  Material cost (plates) . ${res['total_material_cost']:,.2f}")
    else:
        L.append("  Material cost .......... (add cost_per_lb or cost_per_sheet to stock)")
    L.append("")
    L.append("  " + "-" * 60)
    for pr in res["plate_reports"]:
        parts_str = ", ".join(f"{lbl} x{n}" for lbl, n in pr["parts"].items())
        L.append(f"  PLATE {pr['index']} — {pr['stock']}  ({pr['size']} in)")
        L.append(f"    Parts:   {parts_str}")
        L.append(f"    Holes:   {pr['num_holes']}")
        L.append(
            f"    Packing: {pr['packing_utilization_pct']['value']}%   "
            f"Net yield {pr['net_material_yield_pct']['value']}%   "
            f"Part wt {pr['part_weight_lb']} lb / plate "
            f"{pr['plate_weight_lb']} lb   Scrap {pr['scrap_weight_lb']} lb"
        )
        if pr["plate_cost"] is not None:
            L.append(f"    Cost:    ${pr['plate_cost']:,.2f}")
        if pr["remnant_candidates"]:
            candidate = pr["remnant_candidates"][0]
            L.append(
                "    Largest remnant candidate (not certified): "
                f"{_fmt(candidate['width'])} x {_fmt(candidate['height'])} in"
            )
        L.append("")
    if res["part_net_cost"]:
        L.append("  Net material cost per part (metal in part, before markup):")
        for lbl, c in res["part_net_cost"].items():
            L.append(f"    {lbl:<22} ${c:,.2f}")
        L.append("")
    if res["unplaced"]:
        L.append("  " + "!" * 60)
        L.append("  DID NOT FIT (need more/larger stock):")
        for u in res["unplaced"]:
            L.append(
                f"    - {u['label']} x{u['quantity']} "
                f"({u['size']} in; {u['reason']})"
            )
        L.append("")
    if res["has_irregular"]:
        L.append("  NOTE: irregular parts are nested by BOUNDING BOX. Supply a")
        L.append("  true `area` per irregular part for exact weight/cost.")
    if res["burn_dxf_warnings"]:
        L.append("")
        L.append("  BURN DXF SUPPRESSED:")
        for warning in res["burn_dxf_warnings"]:
            L.append(f"    - {warning}")
        L.append("  Reference layouts are estimating aids, not cutting instructions.")
    L.append("=" * 64)
    return "\n".join(L)


# --------------------------------------------------------------------------
# Visual layout  (PNG per plate + combined PDF), holes drawn
# --------------------------------------------------------------------------
def render_layout(res, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.backends.backend_pdf import PdfPages

    margin = res["meta"]["edge_margin_in"]
    pdf_path = os.path.join(outdir, "layout.pdf")
    png_paths = []

    with PdfPages(pdf_path) as pdf:
        for pr in res["plate_reports"]:
            W, H = pr["W"], pr["H"]
            fig, ax = plt.subplots(figsize=(11, max(4.0, 11 * H / W)))
            ax.add_patch(mpatches.Rectangle((0, 0), W, H, fill=False, lw=2.0, ec="#222"))
            ax.add_patch(mpatches.Rectangle((margin, margin), W - 2 * margin, H - 2 * margin,
                                            fill=False, lw=0.8, ec="#bbb", ls="--"))
            for pc in pr["placements"]:
                x, y = pc["x"] + margin, pc["y"] + margin
                w, h = pc["w"], pc["h"]
                irregular = pc["shape"] == "irregular"
                face = "#f4c9a0" if irregular else "#a9c8e8"
                ax.add_patch(mpatches.Rectangle((x, y), w, h, facecolor=face,
                                                edgecolor="#1a3b5c", lw=1.2,
                                                hatch="///" if irregular else None, alpha=0.9))
                for hole in pc.get("holes", []):
                    lx, ly = hole_local(pc, hole)
                    cx, cy = x + lx, y + ly
                    if hole.get("dia") is not None:
                        ax.add_patch(mpatches.Circle((cx, cy), float(hole["dia"]) / 2.0,
                                                     facecolor="white", edgecolor="#8a1c1c", lw=1.0))
                    elif hole.get("w") is not None:
                        hw, hh = float(hole["w"]), float(hole["h"])
                        if pc["rotated"]:
                            hw, hh = hh, hw
                        ax.add_patch(mpatches.Rectangle((cx - hw / 2, cy - hh / 2), hw, hh,
                                                        facecolor="white", edgecolor="#8a1c1c", lw=1.0))
                lbl = pc["label"] + ("*" if irregular else "") + ("  ⟳" if pc["rotated"] else "")
                ax.text(x + w / 2, y + h / 2, lbl, ha="center", va="center",
                        fontsize=7, color="#0c2233")
            ax.set_xlim(-1, W + 1)
            ax.set_ylim(-1, H + 1)
            ax.set_aspect("equal")
            ax.set_title(f"PLATE {pr['index']} — {pr['stock']}  ({pr['size']} in)   "
                         f"Packing {pr['packing_utilization_pct']['value']}%   "
                         f"Holes {pr['num_holes']}",
                         fontsize=12, fontweight="bold")
            ax.set_xlabel("inches")
            ax.grid(True, lw=0.3, color="#eee")
            png = os.path.join(outdir, f"plate_{pr['index']}.png")
            fig.savefig(png, dpi=110, bbox_inches="tight")
            png_paths.append(png)
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)

        fig = plt.figure(figsize=(11, 8.5))
        fig.text(0.5, 0.94, "NEST SUMMARY", ha="center", fontsize=18, fontweight="bold")
        fig.text(0.06, 0.88, render_text(res), family="monospace", fontsize=8.0, va="top")
        pdf.savefig(fig)
        plt.close(fig)

    return pdf_path, png_paths


# --------------------------------------------------------------------------
# DXF: clearly separated reference and geometry-verified burn files
# --------------------------------------------------------------------------
def _draw_part_dxf(msp, pc, x0, y0, profile_layer, holes_layer, notes_layer, label=True):
    import ezdxf
    x, y = x0 + pc["x"], y0 + pc["y"]
    w, h = pc["w"], pc["h"]
    msp.add_lwpolyline(
        [(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
        close=True,
        dxfattribs={"layer": profile_layer},
    )
    for hole in pc.get("holes", []):
        lx, ly = hole_local(pc, hole)
        cx, cy = x + lx, y + ly
        if hole.get("dia") is not None:
            msp.add_circle((cx, cy), float(hole["dia"]) / 2.0, dxfattribs={"layer": holes_layer})
        elif hole.get("w") is not None:
            hw, hh = float(hole["w"]), float(hole["h"])
            if pc["rotated"]:
                hw, hh = hh, hw
            msp.add_lwpolyline(
                [
                    (cx - hw / 2, cy - hh / 2),
                    (cx + hw / 2, cy - hh / 2),
                    (cx + hw / 2, cy + hh / 2),
                    (cx - hw / 2, cy + hh / 2),
                ],
                close=True,
                dxfattribs={"layer": holes_layer},
            )
    if label and notes_layer:
        msp.add_text(pc["label"], height=min(1.0, max(0.25, min(w, h) * 0.18)),
                     dxfattribs={"layer": notes_layer}).set_placement(
            (x + w / 2, y + h / 2), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)


def render_dxf_overview(res, outdir):
    """Write one explicitly reference-only overview with bounding-box outlines."""
    import ezdxf
    margin = res["meta"]["edge_margin_in"]
    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.IN
    msp = doc.modelspace()
    for lyr, col in [("PLATE", 5), ("BOUNDS", 2), ("HOLES", 1), ("NOTES", 7)]:
        if lyr not in doc.layers:
            doc.layers.add(lyr, color=col)
    x_off = 0.0
    for pr in res["plate_reports"]:
        W, H = pr["W"], pr["H"]
        msp.add_lwpolyline(
            [(x_off, 0), (x_off + W, 0), (x_off + W, H), (x_off, H)],
            close=True,
            dxfattribs={"layer": "PLATE"},
        )
        for pc in pr["placements"]:
            _draw_part_dxf(
                msp, pc, x_off + margin, margin, "BOUNDS", "HOLES", "NOTES"
            )
        x_off += W + 10.0
    path = os.path.join(outdir, "reference_nest.dxf")
    doc.saveas(path)
    return path


def render_reference_plate_dxfs(res, outdir):
    """Write one clearly named reference-only DXF per used plate."""
    import ezdxf

    margin = res["meta"]["edge_margin_in"]
    paths = []
    for pr in res["plate_reports"]:
        doc = ezdxf.new("R2010")
        doc.units = ezdxf.units.IN
        msp = doc.modelspace()
        for layer, color in [
            ("PLATE", 5),
            ("BOUNDS", 2),
            ("HOLES", 1),
            ("NOTES", 7),
        ]:
            doc.layers.add(layer, color=color)
        width, height = pr["W"], pr["H"]
        msp.add_lwpolyline(
            [(0, 0), (width, 0), (width, height), (0, height)],
            close=True,
            dxfattribs={"layer": "PLATE"},
        )
        for placement in pr["placements"]:
            _draw_part_dxf(
                msp, placement, margin, margin, "BOUNDS", "HOLES", "NOTES"
            )
        path = os.path.join(outdir, f"reference_plate_{pr['index']}.dxf")
        doc.saveas(path)
        paths.append(path)
    return paths


def render_burn_dxfs(res, outdir):
    """Write cut-geometry-only DXFs for a fully verified rectangular nest."""
    if not res.get("burn_dxf_eligible", False):
        return []

    import ezdxf
    margin = res["meta"]["edge_margin_in"]
    paths = []
    for pr in res["plate_reports"]:
        doc = ezdxf.new("R2010")
        doc.units = ezdxf.units.IN
        msp = doc.modelspace()
        for lyr, col in [("PROFILE", 3), ("HOLES", 1)]:
            doc.layers.add(lyr, color=col)
        for pc in pr["placements"]:
            _draw_part_dxf(
                msp, pc, margin, margin, "PROFILE", "HOLES", None, label=False
            )
        path = os.path.join(outdir, f"burn_plate_{pr['index']}.dxf")
        doc.saveas(path)
        paths.append(path)
    return paths


def stage_decision(res, geometry_verified_only=False):
    """Map the independently verified result onto the shared stage contract."""
    findings = list(res.get("validation_findings", []))
    findings.extend(
        {**finding, "severity": "error"}
        for finding in res.get("verification", {}).get("findings", [])
    )
    if res["unplaced"]:
        findings.append({
            "code": "UNPLACED_PARTS",
            "severity": "error",
            "path": "$.unplaced",
            "message": (
                f"{sum(row['quantity'] for row in res['unplaced'])} "
                "required part(s) remain unplaced."
            ),
        })

    if any(finding["severity"] == "error" for finding in findings):
        outcome = "blocked"
        package_status = "nested_partial" if res["unplaced"] else "draft"
    elif res["has_irregular"]:
        outcome = "review_required"
        package_status = "review_required"
        findings.append({
            "code": "APPROXIMATE_PROFILE_GEOMETRY",
            "severity": "warning",
            "path": "$.groups",
            "message": (
                "Irregular profiles are represented by bounding boxes in "
                "reference-only artifacts."
            ),
        })
    else:
        outcome = "ready"
        package_status = "nest_verified"

    if geometry_verified_only and outcome != "ready":
        findings.append({
            "code": "GEOMETRY_VERIFIED_REQUIRED",
            "severity": "error",
            "path": "$.geometry_readiness",
            "message": "The requested geometry-verified output is unavailable.",
        })

    return outcome, package_status, findings


def package_version():
    package_path = Path(__file__).resolve().parents[3] / "package.json"
    try:
        return json.loads(package_path.read_text(encoding="utf-8"))["version"]
    except (OSError, KeyError, json.JSONDecodeError):
        return "unknown"


def missing_render_dependencies():
    """Return optional render modules unavailable to this interpreter."""
    modules = ("ezdxf", "matplotlib", "numpy")
    return [name for name in modules if importlib.util.find_spec(name) is None]


def publish_nest_run(job, args):
    """Run a legacy nest job and publish one isolated, manifested artifact set."""
    result = run_job(job)
    missing_dependencies = [] if args.no_render else missing_render_dependencies()
    if missing_dependencies:
        outcome = "dependency_missing"
        package_status = "draft"
        findings = [{
            "code": "RENDER_DEPENDENCY_MISSING",
            "severity": "error",
            "message": (
                "Rendering requires the missing module(s): "
                + ", ".join(missing_dependencies)
            ),
        }]
    else:
        outcome, package_status, findings = stage_decision(
            result, args.geometry_verified_only
        )
    result["outcome"] = outcome
    result["run_outcome"] = outcome
    result["package_status"] = package_status
    report = render_text(result)

    configuration = {
        "algorithm_version": NEST_ALGORITHM_VERSION,
        "engine_configuration_hash": result["configuration_hash"],
        "geometry_verified_only": args.geometry_verified_only,
        "render": not args.no_render,
    }
    publication_configuration_hash = sha256_bytes(
        canonical_json_bytes(configuration)
    )
    approximations = []
    if result["has_irregular"]:
        approximations.append({
            "code": "BOUNDING_BOX_NESTING",
            "message": "One or more irregular profiles use bounding-box placement.",
        })
    qa_report = {
        "schema_version": "1.0.0",
        "stage": "steel-nest",
        "run_outcome": outcome,
        "package_status": package_status,
        "geometry_readiness": result["geometry_readiness"],
        "geometry_verified_only_requested": args.geometry_verified_only,
        "findings": findings,
    }

    with RunPublisher(
        args.out,
        stage="steel-nest",
        run_outcome=outcome,
        package_status=package_status,
        input_hash=result["normalized_input_hash"],
        configuration_hash=publication_configuration_hash,
        schema_versions={
            "run_manifest": "1.0.0",
            "nest_result": NEST_RESULT_VERSION,
            "rfq_nesting": "1.0.0",
        },
        tool_versions={
            "pi_steel": package_version(),
            "nest_algorithm": NEST_ALGORITHM_VERSION,
        },
        explicit_dates={},
        warnings=result["burn_dxf_warnings"]
        + [finding["message"] for finding in findings if finding["severity"] == "error"],
        approximations=approximations,
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
        if outcome in {"ready", "review_required"}:
            publisher.write_json(
                "rfq_nesting.json", result["rfq_nesting"], readiness="diagnostic"
            )

        if not args.no_render and not missing_dependencies:
            publisher.register_artifact(
                "layout.pdf", readiness="reference_only", media_type="application/pdf"
            )
            for plate in result["plate_reports"]:
                publisher.register_artifact(
                    f"plate_{plate['index']}.png",
                    readiness="reference_only",
                    media_type="image/png",
                )
            render_layout(result, publisher.staging_path)

            if result["plate_reports"]:
                publisher.register_artifact(
                    "reference_nest.dxf",
                    readiness="reference_only",
                    media_type="image/vnd.dxf",
                )
                for plate in result["plate_reports"]:
                    publisher.register_artifact(
                        f"reference_plate_{plate['index']}.dxf",
                        readiness="reference_only",
                        media_type="image/vnd.dxf",
                    )
                render_dxf_overview(result, publisher.staging_path)
                render_reference_plate_dxfs(result, publisher.staging_path)

            if outcome == "ready":
                for plate in result["plate_reports"]:
                    publisher.register_artifact(
                        f"burn_plate_{plate['index']}.dxf",
                        readiness="geometry_verified",
                        media_type="image/vnd.dxf",
                    )
                render_burn_dxfs(result, publisher.staging_path)

        final_path = publisher.publish()

    return result, qa_report, report, final_path


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main(argv=None):
    ap = StageArgumentParser(description="Steel plate nesting engine")
    ap.add_argument("--job", required=True)
    ap.add_argument(
        "--out",
        default="out",
        help="Publication root; each invocation writes an isolated runs/<run-id>/",
    )
    ap.add_argument("--no-render", action="store_true", help="Skip PDF/PNG/DXF")
    ap.add_argument(
        "--geometry-verified-only",
        action="store_true",
        help="Require geometry-verified output; unresolved jobs still publish QA",
    )
    ap.add_argument("--run-id", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    with open(args.job, encoding="utf-8") as f:
        job = json.load(f)
    result, qa_report, report, final_path = publish_nest_run(job, args)
    print(report)
    print(f"\nPublished {qa_report['run_outcome']} run: {final_path}")
    if result["burn_dxf_warnings"]:
        print("Burn DXFs suppressed:")
        for warning in result["burn_dxf_warnings"]:
            print(f"  - {warning}")
    return outcome_exit_code(qa_report["run_outcome"])


if __name__ == "__main__":
    raise SystemExit(main())
