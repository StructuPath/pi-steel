"""Adapters from the supported legacy BOM and nesting inputs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .contracts import (
    ESTIMATE_PACKAGE_VERSION,
    content_hash,
    fallback_source_id,
    item_id_for,
)


def parse_length_ft(raw: str) -> float:
    value = raw.strip()
    if "'" not in value:
        return float(value)
    feet, _, inches = value.replace('"', "").partition("'")
    return float(feet.replace("-", "").strip()) + (
        float(inches.replace("-", "").strip()) / 12 if inches.strip() else 0
    )


def _package(
    *,
    project_id: str,
    revision_id: str,
    source_type: str,
    source_hash: str,
    items: list[dict[str, Any]],
    stock: list[dict[str, Any]] | None = None,
    unit_system: str = "imperial",
) -> dict[str, Any]:
    return {
        "schema_version": ESTIMATE_PACKAGE_VERSION,
        "project": {
            "project_id": project_id,
            "revision": {"revision_id": revision_id},
        },
        "unit_system": unit_system,
        "items": items,
        "stock": stock or [],
        "commercial_basis": {"currency": "USD", "costs": []},
        "review": {"status": "draft", "findings": [], "acknowledgements": []},
        "lineage": {
            "source_type": source_type,
            "source_hash": source_hash,
            "configuration_hash": content_hash({"adapter": source_type, "version": 1}),
        },
    }


def adapt_legacy_bom_csv(
    path: str | Path, *, project_id: str, revision_id: str
) -> dict[str, Any]:
    csv_path = Path(path)
    raw_bytes = csv_path.read_bytes()
    items: list[dict[str, Any]] = []
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            mark = row.get("Mark", "").strip()
            if mark.startswith("#") or not any((value or "").strip() for value in row.values()):
                continue
            explicit_source = row.get("Source_ID", "").strip()
            stable_identity = {
                key: (value or "").strip()
                for key, value in row.items()
                if key not in {"Total_Wt_lbs"}
            }
            source_id = explicit_source or (
                f"legacy:{revision_id}:mark:{mark}"
                if mark
                else fallback_source_id(revision_id, stable_identity)
            )
            item: dict[str, Any] = {
                "intent": row.get("Intent", "").strip() or "fabricated_part",
                "source_id": source_id,
                "item_id": item_id_for(project_id, revision_id, source_id),
                "quantity": int(row.get("Qty", "0").strip()),
                "mark": mark,
                "designation": row.get("Size", "").strip(),
                "grade": row.get("Grade", "").strip(),
                "length_ft": parse_length_ft(row.get("Length_ft", "0")),
                "unit_weight_plf": float(row.get("Unit_Wt_plf", "0").strip()),
                "connections": row.get("Connections", "").strip(),
                "notes": row.get("Notes", "").strip(),
            }
            total = row.get("Total_Wt_lbs", "").strip()
            if total:
                item["total_weight_lbs"] = float(total)
            sheet = row.get("Source_Sheet", "").strip()
            detail = row.get("Source_Detail", "").strip()
            if sheet or detail:
                item["source_evidence"] = [
                    {
                        "source": sheet or "legacy_bom",
                        "locator": detail or mark or source_id,
                    }
                ]
            if not explicit_source and not mark:
                item["identity_warning"] = True
            items.append(item)
    return _package(
        project_id=project_id,
        revision_id=revision_id,
        source_type="legacy_bom_csv",
        source_hash=content_hash({"bytes_hex": raw_bytes.hex()}),
        items=items,
    )


def adapt_legacy_nest(
    data: dict[str, Any] | str | Path, *, project_id: str, revision_id: str
) -> dict[str, Any]:
    if isinstance(data, (str, Path)):
        value = json.loads(Path(data).read_text(encoding="utf-8"))
    else:
        value = json.loads(json.dumps(data))
    material = value.get("material")
    grade = value.get("grade")
    unit_system = value.get("unit_system")
    thickness = value.get("thickness_in", value.get("settings", {}).get("thickness_in"))
    items = []
    for part in value.get("parts", []):
        explicit_source = part.get("source_id")
        identity = {
            key: part.get(key)
            for key in ("name", "width", "height", "shape", "area")
        }
        source_id = explicit_source or fallback_source_id(revision_id, identity)
        geometry = {
            "shape": part.get("shape", "rect"),
            "width": part.get("width"),
            "height": part.get("height"),
            "thickness": thickness,
            "holes": [
                (
                    {
                        "kind": "round",
                        "diameter": hole.get("dia"),
                        "x": hole.get("x"),
                        "y": hole.get("y"),
                    }
                    if "dia" in hole
                    else {
                        "kind": "rect",
                        "width": hole.get("w"),
                        "height": hole.get("h"),
                        "x": hole.get("x"),
                        "y": hole.get("y"),
                    }
                )
                for hole in part.get("holes", [])
            ],
            "rotatable": part.get("rotatable", True),
        }
        if "area" in part:
            geometry["area"] = part["area"]
        item = {
            "intent": "fabricated_part",
            "source_id": source_id,
            "item_id": item_id_for(project_id, revision_id, source_id),
            "quantity": part.get("qty", 0),
            "mark": part.get("name", ""),
            "geometry": geometry,
        }
        if material is not None:
            item["material"] = material
        if grade is not None:
            item["grade"] = grade
        if not explicit_source:
            item["identity_warning"] = True
        items.append(item)

    stock = []
    if material and grade and thickness is not None:
        for index, legacy_stock in enumerate(value.get("stock", []), start=1):
            stock.append(
                {
                    "stock_kind": "purchasable",
                    "inventory_id": f"legacy-stock:{revision_id}:{index:04d}",
                    "material": material,
                    "grade": grade,
                    "width": legacy_stock.get("width"),
                    "height": legacy_stock.get("height"),
                    "thickness": legacy_stock.get("thickness", thickness),
                    "quantity": legacy_stock.get(
                        "qty", 1 if legacy_stock.get("unlimited") else 0
                    ),
                    "status": "available",
                }
            )
    return _package(
        project_id=project_id,
        revision_id=revision_id,
        source_type="legacy_nest_json",
        source_hash=content_hash(value),
        items=items,
        stock=stock,
        unit_system=unit_system or "imperial",
    )
