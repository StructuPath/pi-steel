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


def _finite_point(point: Any) -> bool:
    return (
        isinstance(point, (list, tuple))
        and len(point) == 2
        and all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            for value in point
        )
    )


def polygon_area(outline: list[Any]) -> float:
    """Absolute shoelace area of a closed polygon given as vertex pairs."""
    total = 0.0
    count = len(outline)
    for index in range(count):
        x1, y1 = outline[index]
        x2, y2 = outline[(index + 1) % count]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _orient(a, b, c):
    value = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    if value > 1e-12:
        return 1
    if value < -1e-12:
        return -1
    return 0


def _segments_properly_intersect(p1, p2, p3, p4) -> bool:
    """Whether open segments p1-p2 and p3-p4 cross (shared endpoints excluded)."""
    o1, o2 = _orient(p1, p2, p3), _orient(p1, p2, p4)
    o3, o4 = _orient(p3, p4, p1), _orient(p3, p4, p2)
    return o1 != o2 and o3 != o4 and 0 not in (o1, o2, o3, o4)


def _segments_touch(p1, p2, p3, p4) -> bool:
    """Any contact between closed segments: crossing, touch, or overlap."""
    o1, o2 = _orient(p1, p2, p3), _orient(p1, p2, p4)
    o3, o4 = _orient(p3, p4, p1), _orient(p3, p4, p2)
    if o1 != o2 and o3 != o4:
        return True
    return (
        (o1 == 0 and _point_on_segment(p3, p1, p2))
        or (o2 == 0 and _point_on_segment(p4, p1, p2))
        or (o3 == 0 and _point_on_segment(p1, p3, p4))
        or (o4 == 0 and _point_on_segment(p2, p3, p4))
    )


def polygon_is_simple(outline: list[Any]) -> bool:
    """Whether the ring never touches itself.

    Rejects repeated vertices (which also covers zero-length edges and
    spikes) and any contact between non-adjacent edges — proper crossings,
    endpoint touches, and collinear overlaps alike.
    """
    count = len(outline)
    if len({(point[0], point[1]) for point in outline}) != count:
        return False
    edges = [
        (outline[index], outline[(index + 1) % count]) for index in range(count)
    ]
    for first in range(count):
        for second in range(first + 1, count):
            if second == first + 1 or (first == 0 and second == count - 1):
                continue
            if _segments_touch(*edges[first], *edges[second]):
                return False
    return True


def point_in_polygon(point: Any, outline: list[Any]) -> bool:
    """Ray-casting containment; boundary points count as inside."""
    x, y = point
    inside = False
    count = len(outline)
    for index in range(count):
        x1, y1 = outline[index]
        x2, y2 = outline[(index + 1) % count]
        if _point_on_segment((x, y), (x1, y1), (x2, y2)):
            return True
        if (y1 > y) != (y2 > y):
            crossing = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing:
                inside = not inside
    return inside


def _point_on_segment(point, start, end) -> bool:
    px, py = point
    x1, y1 = start
    x2, y2 = end
    cross = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
    if abs(cross) > 1e-9:
        return False
    return (
        min(x1, x2) - 1e-9 <= px <= max(x1, x2) + 1e-9
        and min(y1, y2) - 1e-9 <= py <= max(y1, y2) + 1e-9
    )


def _point_segment_distance(point, start, end) -> float:
    px, py = point
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_squared))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def validate_outline(
    outline: Any, width: Any, height: Any
) -> list[str]:
    """Return human-readable problems with an irregular part outline.

    A valid outline is a simple polygon of at least three finite vertex
    pairs whose bounding box matches the declared width and height (the
    outline defines the part in its own local frame).
    """
    problems: list[str] = []
    if not isinstance(outline, list) or len(outline) < 3:
        return ["Outline requires at least three [x, y] vertex pairs."]
    if not all(_finite_point(point) for point in outline):
        return ["Outline vertices must be finite [x, y] pairs."]
    if not polygon_is_simple(outline):
        problems.append("Outline edges must not cross (simple polygon).")
    if polygon_area(outline) <= 1e-9:
        problems.append("Outline must enclose a positive area.")
    if finite_positive(width) and finite_positive(height):
        xs = [point[0] for point in outline]
        ys = [point[1] for point in outline]
        epsilon = 1e-6
        if (
            min(xs) < -epsilon
            or min(ys) < -epsilon
            or max(xs) > width + epsilon
            or max(ys) > height + epsilon
            or abs(min(xs)) > epsilon
            or abs(min(ys)) > epsilon
            or abs(max(xs) - width) > epsilon
            or abs(max(ys) - height) > epsilon
        ):
            problems.append(
                "Outline bounding box must span exactly 0..width and 0..height."
            )
    return problems


def hole_within_outline(hole: dict[str, Any], outline: list[Any]) -> bool:
    """Exact containment of a supported hole inside the part outline."""
    x, y = hole.get("x"), hole.get("y")
    if not all(
        isinstance(value, (int, float)) and math.isfinite(value)
        for value in (x, y)
    ):
        return False
    count = len(outline)
    edges = [
        (outline[index], outline[(index + 1) % count]) for index in range(count)
    ]
    if hole.get("kind") == "round":
        diameter = hole.get("diameter")
        if not finite_positive(diameter):
            return False
        radius = diameter / 2
        if not point_in_polygon((x, y), outline):
            return False
        return all(
            _point_segment_distance((x, y), start, end) >= radius - 1e-9
            for start, end in edges
        )
    if hole.get("kind") == "rect":
        hole_width, hole_height = hole.get("width"), hole.get("height")
        if not finite_positive(hole_width) or not finite_positive(hole_height):
            return False
        corners = [
            (x - hole_width / 2, y - hole_height / 2),
            (x + hole_width / 2, y - hole_height / 2),
            (x + hole_width / 2, y + hole_height / 2),
            (x - hole_width / 2, y + hole_height / 2),
        ]
        if not all(point_in_polygon(corner, outline) for corner in corners):
            return False
        rect_edges = [
            (corners[index], corners[(index + 1) % 4]) for index in range(4)
        ]
        return not any(
            _segments_properly_intersect(*rect_edge, *edge)
            for rect_edge in rect_edges
            for edge in edges
        )
    return False


def gross_area(geometry: dict[str, Any]) -> float:
    if geometry.get("shape") == "irregular":
        outline = geometry.get("outline")
        if isinstance(outline, list) and len(outline) >= 3 and all(
            _finite_point(point) for point in outline
        ):
            return polygon_area(outline)
        if geometry.get("area") is not None:
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
