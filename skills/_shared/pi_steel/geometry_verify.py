"""Geometry checks shared by contract validation and nesting."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


SUPPORTED_SHAPES = frozenset({"rect", "irregular"})


def finite_positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def hole_area(hole: dict[str, Any]) -> float:
    if hole.get("kind") == "round":
        diameter = hole.get("diameter", 0)
        return math.pi * (diameter / 2) ** 2
    if hole.get("kind") == "rect":
        return hole.get("width", 0) * hole.get("height", 0)
    return 0


def hole_within_bounds(hole: dict[str, Any], width: float, height: float) -> bool:
    x, y = hole.get("x"), hole.get("y")
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in (x, y)):
        return False
    if hole.get("kind") == "round":
        diameter = hole.get("diameter")
        if not finite_positive(diameter):
            return False
        radius = diameter / 2
        return radius <= x <= width - radius and radius <= y <= height - radius
    if hole.get("kind") == "rect":
        hole_width, hole_height = hole.get("width"), hole.get("height")
        if not finite_positive(hole_width) or not finite_positive(hole_height):
            return False
        return (
            hole_width / 2 <= x <= width - hole_width / 2
            and hole_height / 2 <= y <= height - hole_height / 2
        )
    return False


def gross_area(geometry: dict[str, Any]) -> float:
    if geometry.get("shape") == "irregular" and geometry.get("area") is not None:
        return geometry["area"]
    return geometry.get("width", 0) * geometry.get("height", 0)


def net_area(geometry: dict[str, Any]) -> float:
    return gross_area(geometry) - sum(hole_area(hole) for hole in geometry.get("holes", []))


def plate_group_key(item: dict[str, Any]) -> tuple[Any, Any, Any]:
    geometry = item.get("geometry", {})
    return item.get("material"), item.get("grade"), geometry.get("thickness")


def group_plate_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Partition parts strictly by material, grade, and thickness."""
    groups: dict[tuple[Any, Any, Any], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        groups[plate_group_key(item)].append(item)
    return [
        {
            "material": key[0],
            "grade": key[1],
            "thickness": key[2],
            "items": grouped,
        }
        for key, grouped in sorted(groups.items(), key=lambda pair: repr(pair[0]))
    ]


def _finite_placement_values(placement: dict[str, Any]) -> bool:
    return all(
        isinstance(placement.get(field), (int, float))
        and math.isfinite(placement[field])
        for field in ("x", "y", "w", "h")
    )


def _placements_separated(
    first: dict[str, Any],
    second: dict[str, Any],
    clearance: float,
    epsilon: float,
) -> bool:
    return (
        first["x"] + first["w"] + clearance <= second["x"] + epsilon
        or second["x"] + second["w"] + clearance <= first["x"] + epsilon
        or first["y"] + first["h"] + clearance <= second["y"] + epsilon
        or second["y"] + second["h"] + clearance <= first["y"] + epsilon
    )


def _overlap_candidate_pairs(
    placements: list[dict[str, Any]],
    clearance: float,
    epsilon: float,
) -> list[tuple[int, int]]:
    """Return deterministic overlap pairs without scanning every valid pair."""
    numeric = {
        index for index, placement in enumerate(placements)
        if _finite_placement_values(placement)
    }
    sweepable = {
        index for index in numeric
        if placements[index]["w"] > 0 and placements[index]["h"] > 0
    }
    candidates: set[tuple[int, int]] = set()
    active: list[int] = []
    for current_index in sorted(
        sweepable, key=lambda index: (placements[index]["x"], index)
    ):
        current = placements[current_index]
        active = [
            index
            for index in active
            if (
                placements[index]["x"]
                + placements[index]["w"]
                + clearance
                > current["x"] + epsilon
            )
        ]
        for other_index in active:
            other = placements[other_index]
            if not (
                other["y"] + other["h"] + clearance <= current["y"] + epsilon
                or current["y"] + current["h"] + clearance
                <= other["y"] + epsilon
            ):
                candidates.add(
                    (min(other_index, current_index), max(other_index, current_index))
                )
        active.append(current_index)

    nonsweepable = numeric - sweepable
    for first_index in sorted(nonsweepable):
        for second_index in sorted(numeric):
            if first_index < second_index:
                candidates.add((first_index, second_index))
            elif second_index < first_index and second_index in sweepable:
                candidates.add((second_index, first_index))
    return sorted(candidates)


def verify_nest_placements(
    plate_reports: list[dict[str, Any]],
    *,
    edge_margin: float,
    inter_part_clearance: float,
) -> list[dict[str, Any]]:
    """Verify normalized placements without relying on a packing algorithm's state."""
    findings: list[dict[str, Any]] = []
    epsilon = 1e-9
    for plate_index, plate in enumerate(plate_reports):
        usable_width = plate.get("W", 0) - 2 * edge_margin
        usable_height = plate.get("H", 0) - 2 * edge_margin
        placements = plate.get("placements", [])
        plate_basis = (
            plate.get("material"),
            plate.get("grade"),
            plate.get("thickness"),
        )
        for placement_index, placement in enumerate(placements):
            path = f"$.plate_reports[{plate_index}].placements[{placement_index}]"
            values = (
                placement.get("x"),
                placement.get("y"),
                placement.get("w"),
                placement.get("h"),
            )
            if not all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                for value in values
            ):
                findings.append(
                    {
                        "code": "nonfinite_placement",
                        "path": path,
                        "message": "Placement coordinates and dimensions must be finite.",
                    }
                )
                continue
            x, y, width, height = values
            if (
                width <= 0
                or height <= 0
                or x < -epsilon
                or y < -epsilon
                or x + width > usable_width + epsilon
                or y + height > usable_height + epsilon
            ):
                findings.append(
                    {
                        "code": "placement_out_of_bounds",
                        "path": path,
                        "message": "Placement must remain inside the edge-margin boundary.",
                    }
                )
            placement_basis = (
                placement.get("material"),
                placement.get("grade"),
                placement.get("thickness"),
            )
            if placement_basis != plate_basis:
                findings.append(
                    {
                        "code": "material_mismatch",
                        "path": path,
                        "message": "Placement material, grade, and thickness must match its stock.",
                    }
                )

        for first_index, second_index in _overlap_candidate_pairs(
            placements, inter_part_clearance, epsilon
        ):
            first = placements[first_index]
            second = placements[second_index]
            if not _placements_separated(
                first, second, inter_part_clearance, epsilon
            ):
                findings.append(
                    {
                        "code": "placement_overlap",
                        "path": (
                            f"$.plate_reports[{plate_index}].placements"
                            f"[{first_index},{second_index}]"
                        ),
                        "message": (
                            "Placements overlap or violate the required "
                            "kerf-plus-gap clearance."
                        ),
                    }
                )
    return findings
