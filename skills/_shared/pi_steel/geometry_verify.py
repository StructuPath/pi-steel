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
