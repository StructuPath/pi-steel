import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "skills" / "_shared"
sys.path.insert(0, str(SHARED))
NEST_SCRIPT = ROOT / "skills" / "steel-nest" / "scripts" / "nest.py"
SPEC = importlib.util.spec_from_file_location("pi_steel_nest_outline", NEST_SCRIPT)
nest = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = nest
SPEC.loader.exec_module(nest)

from pi_steel.geometry_verify import (  # noqa: E402
    hole_within_outline,
    point_in_polygon,
    polygon_area,
    polygon_is_simple,
    validate_outline,
)
from pi_steel.validation import validate_estimate_package  # noqa: E402


# L-shape: 8 x 6 bounding box with the upper-right 5 x 3 notch removed.
L_SHAPE = [[0, 0], [8, 0], [8, 3], [3, 3], [3, 6], [0, 6]]
BOWTIE = [[0, 0], [4, 4], [4, 0], [0, 4]]


def test_polygon_helpers_on_l_shape_and_bowtie():
    assert polygon_area(L_SHAPE) == 33.0
    assert polygon_is_simple(L_SHAPE)
    assert not polygon_is_simple(BOWTIE)
    assert point_in_polygon((1.5, 1.5), L_SHAPE)
    assert not point_in_polygon((6, 5), L_SHAPE)
    assert validate_outline(L_SHAPE, 8, 6) == []
    assert validate_outline(L_SHAPE, 10, 6) != []
    assert validate_outline([[0, 0], [1, 1]], 8, 6) != []


def test_hole_containment_uses_true_outline():
    inside = {"kind": "round", "diameter": 1, "x": 1.5, "y": 1.5}
    in_notch = {"kind": "round", "diameter": 1, "x": 6, "y": 5}
    touching_edge = {"kind": "round", "diameter": 2, "x": 3.5, "y": 2.5}
    assert hole_within_outline(inside, L_SHAPE)
    assert not hole_within_outline(in_notch, L_SHAPE)
    assert not hole_within_outline(touching_edge, L_SHAPE)
    rect_ok = {"kind": "rect", "width": 1, "height": 1, "x": 1.5, "y": 1.5}
    rect_crossing = {"kind": "rect", "width": 4, "height": 1, "x": 4, "y": 2.8}
    assert hole_within_outline(rect_ok, L_SHAPE)
    assert not hole_within_outline(rect_crossing, L_SHAPE)


def outline_job():
    return {
        "job_name": "SYNTHETIC-OUTLINE",
        "material": "carbon_steel",
        "grade": "A36",
        "unit_system": "imperial",
        "settings": {
            "kerf_in": 0.05,
            "part_gap_in": 0.2,
            "edge_margin_in": 0.5,
            "thickness_in": 0.5,
            "density_lb_in3": 0.2836,
        },
        "stock": [
            {
                "stock_id": "SYNTHETIC-STOCK-OUTLINE",
                "name": "Synthetic Plate",
                "width": 20,
                "height": 10,
                "thickness": 0.5,
                "qty": 1,
            }
        ],
        "parts": [
            {
                "source_id": "SYNTHETIC-SRC-L",
                "name": "SYNTHETIC-L",
                "width": 8,
                "height": 6,
                "qty": 1,
                "shape": "irregular",
                "outline": deepcopy(L_SHAPE),
            }
        ],
    }


def test_outline_part_gets_exact_area_and_review_required_outcome():
    result = nest.run_job(outline_job())
    assert result["outcome"] == "review_required"
    part = result["plate_reports"][0]["placements"][0]
    assert part["base_area"] == 33.0
    assert part["outline"] == L_SHAPE
    assert result["metrics"]["net_material_yield_pct"]["approximation"] == (
        "outline_exact"
    )
    # Exact net weight: 33 in^2 x 0.5 in x 0.2836 lb/in^3.
    assert result["total_part_weight_lb"] == round(33 * 0.5 * 0.2836, 1)
    assert result["burn_dxf_eligible"] is False


def test_hole_in_bbox_but_outside_outline_blocks():
    job = outline_job()
    job["parts"][0]["holes"] = [{"dia": 1, "x": 6, "y": 5}]
    result = nest.run_job(job)
    assert result["outcome"] == "blocked"
    assert any(
        finding["code"] == "invalid_hole_geometry"
        for finding in result["validation_findings"]
    )


def test_self_intersecting_or_mismatched_outline_blocks():
    job = outline_job()
    job["parts"][0]["outline"] = deepcopy(BOWTIE)
    job["parts"][0]["width"], job["parts"][0]["height"] = 4, 4
    bowtie = nest.run_job(job)
    assert bowtie["outcome"] == "blocked"
    assert any(
        finding["code"] == "invalid_outline"
        for finding in bowtie["validation_findings"]
    )

    job = outline_job()
    job["parts"][0]["area"] = 30
    mismatch = nest.run_job(job)
    assert mismatch["outcome"] == "blocked"
    assert any(
        finding["code"] == "outline_area_mismatch"
        for finding in mismatch["validation_findings"]
    )

    job = outline_job()
    job["parts"][0]["shape"] = "rect"
    on_rect = nest.run_job(job)
    assert on_rect["outcome"] == "blocked"
    assert any(
        finding["code"] == "outline_on_rect"
        for finding in on_rect["validation_findings"]
    )


def test_reference_renders_draw_true_outline(tmp_path):
    result = nest.run_job(outline_job())
    dxf_paths = nest.render_reference_plate_dxfs(result, tmp_path)
    assert dxf_paths
    import ezdxf

    document = ezdxf.readfile(dxf_paths[0])
    polylines = [
        entity
        for entity in document.modelspace()
        if entity.dxftype() == "LWPOLYLINE"
        and entity.dxf.layer == "BOUNDS"
    ]
    assert polylines
    assert len(polylines[0]) == len(L_SHAPE)

    pdf_path, png_paths = nest.render_layout(result, tmp_path)
    assert Path(pdf_path).exists()
    assert all(Path(path).exists() for path in png_paths)


def canonical_outline_package():
    return {
        "schema_version": "1.0.0",
        "project": {
            "project_id": "SYNTHETIC-OUTLINE-001",
            "revision": {"revision_id": "SYNTHETIC-REV-A"},
        },
        "unit_system": "imperial",
        "items": [
            {
                "intent": "fabricated_part",
                "source_id": "SYNTHETIC-SRC-L",
                "item_id": "item:synthetic-outline-l",
                "quantity": 1,
                "mark": "L1",
                "material": "carbon_steel",
                "grade": "A36",
                "geometry": {
                    "shape": "irregular",
                    "width": 8,
                    "height": 6,
                    "thickness": 0.5,
                    "outline": deepcopy(L_SHAPE),
                    "holes": [],
                    "rotatable": True,
                },
                "source_evidence": [
                    {"source": "SYNTHETIC-SOURCE", "locator": "L1"}
                ],
            }
        ],
        "stock": [],
        "commercial_basis": {"currency": "USD", "costs": []},
        "review": {"status": "draft", "findings": [], "acknowledgements": []},
        "lineage": {
            "source_type": "synthetic_test",
            "source_hash": "a" * 64,
            "configuration_hash": "b" * 64,
        },
    }


def test_canonical_validator_accepts_outline_without_declared_area():
    result = validate_estimate_package(canonical_outline_package())
    codes = {finding["code"] for finding in result.findings}
    assert "invalid_irregular_area" not in codes
    assert "invalid_outline" not in codes
    assert not result.blockers


def test_canonical_validator_rejects_notch_hole_and_bad_outline():
    package = canonical_outline_package()
    package["items"][0]["geometry"]["holes"] = [
        {"kind": "round", "diameter": 1, "x": 6, "y": 5}
    ]
    notch = validate_estimate_package(package)
    assert any(
        finding["code"] == "hole_outside_outline" for finding in notch.blockers
    )

    package = canonical_outline_package()
    package["items"][0]["geometry"]["outline"] = deepcopy(BOWTIE)
    package["items"][0]["geometry"]["width"] = 4
    package["items"][0]["geometry"]["height"] = 4
    bowtie = validate_estimate_package(package)
    assert any(
        finding["code"] == "invalid_outline" for finding in bowtie.blockers
    )

    package = canonical_outline_package()
    package["items"][0]["geometry"]["area"] = 30
    mismatch = validate_estimate_package(package)
    assert any(
        finding["code"] == "outline_area_mismatch"
        for finding in mismatch.blockers
    )


def test_pipeline_carries_outline_through_nest(tmp_path):
    sys.path.insert(0, str(ROOT / "tests"))
    from test_estimate_pipeline import load_package, run_pipeline  # noqa: E402

    package = load_package()
    for item in package["items"]:
        geometry = item.get("geometry")
        if geometry and item.get("mark") == "P2":
            geometry["shape"] = "irregular"
            width, height = geometry["width"], geometry["height"]
            geometry["outline"] = [
                [0, 0],
                [width, 0],
                [width, height / 2],
                [width / 2, height / 2],
                [width / 2, height],
                [0, height],
            ]
    completed, run_path = run_pipeline(
        tmp_path, package, "SYNTHETIC-PIPELINE-OUTLINE"
    )
    assert completed.returncode == 2, completed.stdout + completed.stderr
    nest_result = json.loads((run_path / "nest-result.json").read_text())
    assert nest_result["metrics"]["net_material_yield_pct"]["approximation"] in {
        "outline_exact",
        "declared_area",
    }
    outlines = [
        placement["outline"]
        for plate in nest_result["plate_reports"]
        for placement in plate["placements"]
        if placement["outline"]
    ]
    assert outlines


def test_self_touching_rings_are_rejected():
    # Reused boundary via a repeated vertex (CodeRabbit review case).
    reused = [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0], [2, 0]]
    assert not polygon_is_simple(reused)
    # A non-adjacent edge endpoint touching another edge, without any
    # repeated vertex: the (6,4)->(3,0) edge lands on the bottom edge.
    t_touch = [[0, 0], [6, 0], [6, 4], [3, 0], [0, 4]]
    assert not polygon_is_simple(t_touch)
    # Concave but genuinely simple rings still pass.
    concave = [[0, 0], [4, 0], [2, 2], [4, 4], [0, 4]]
    assert polygon_is_simple(concave)


def test_distinct_outlines_get_distinct_fallback_identities():
    import pi_steel.parsing as parsing

    mirrored = [[0, 0], [8, 0], [8, 6], [5, 6], [5, 3], [0, 3]]
    legacy = {
        "material": "carbon_steel",
        "grade": "A36",
        "unit_system": "imperial",
        "settings": {"thickness_in": 0.5},
        "stock": [{"width": 20, "height": 10, "qty": 2}],
        "parts": [
            {
                "name": "GUSSET",
                "width": 8,
                "height": 6,
                "qty": 1,
                "shape": "irregular",
                "outline": deepcopy(L_SHAPE),
            },
            {
                "name": "GUSSET",
                "width": 8,
                "height": 6,
                "qty": 1,
                "shape": "irregular",
                "outline": mirrored,
            },
        ],
    }
    package = parsing.adapt_legacy_nest(
        legacy, project_id="SYNTHETIC-PRJ", revision_id="SYNTHETIC-REV"
    )
    source_ids = [item["source_id"] for item in package["items"]]
    assert len(set(source_ids)) == 2

    direct = nest.run_job(
        {
            "job_name": "SYNTHETIC-DISTINCT",
            "material": "carbon_steel",
            "grade": "A36",
            "unit_system": "imperial",
            "settings": {"thickness_in": 0.5},
            "stock": [
                {
                    "stock_id": "SYNTHETIC-STOCK-D",
                    "width": 20,
                    "height": 10,
                    "thickness": 0.5,
                    "qty": 2,
                }
            ],
            "parts": deepcopy(legacy["parts"]),
        }
    )
    assert not any(
        finding["code"].startswith("duplicate_")
        for finding in direct["validation_findings"]
    )


def test_placement_outline_schema_rejects_degenerate_vertex_lists():
    import jsonschema

    schema = json.loads(
        (SHARED / "schemas" / "nest-result.schema.json").read_text()
    )
    validator = jsonschema.Draft202012Validator(
        {
            "$schema": schema["$schema"],
            "$ref": "#/$defs/outlineOnly",
            "$defs": {
                "outlineOnly": {
                    "type": "object",
                    "properties": {
                        "outline": schema["$defs"]["placement"]["properties"][
                            "outline"
                        ]
                    },
                }
            },
        }
    )
    assert validator.is_valid({"outline": []})
    assert validator.is_valid({"outline": [[0, 0], [1, 0], [1, 1]]})
    assert not validator.is_valid({"outline": [[0, 0]]})
    assert not validator.is_valid({"outline": [[0, 0], [1, 0]]})
