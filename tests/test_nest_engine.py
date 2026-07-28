import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
NEST_SCRIPT = ROOT / "skills" / "steel-nest" / "scripts" / "nest.py"
SPEC = importlib.util.spec_from_file_location("pi_steel_nest_engine", NEST_SCRIPT)
nest = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = nest
SPEC.loader.exec_module(nest)


def base_job():
    return {
        "job_name": "SYNTHETIC-ENGINE",
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
                "stock_id": "SYNTHETIC-STOCK-1",
                "name": "Synthetic Plate",
                "width": 11,
                "height": 7,
                "thickness": 0.5,
                "qty": 1,
            }
        ],
        "parts": [
            {
                "source_id": "SYNTHETIC-SRC-1",
                "name": "SYNTHETIC-PART-1",
                "width": 10,
                "height": 6,
                "qty": 1,
                "shape": "rect",
            }
        ],
    }


def test_characterizes_exact_fit_without_trailing_clearance_rejection():
    result = nest.run_job(base_job())
    placement = result["plate_reports"][0]["placements"][0]
    assert result["unplaced"] == []
    assert (placement["x"], placement["y"], placement["w"], placement["h"]) == (
        0,
        0,
        10,
        6,
    )
    assert result["clearance_contract"] == {
        "edge_margin_ownership": "plate_to_part",
        "inter_part_clearance_ownership": "kerf_plus_gap",
        "trailing_clearance_required_at_plate_edge": False,
    }


def test_rotated_fit_and_nonrotatable_oversize_quantity_aggregation():
    job = base_job()
    job["stock"][0].update(width=7, height=11)
    rotated = nest.run_job(job)
    assert rotated["plate_reports"][0]["placements"][0]["rotated"] is True

    job["parts"][0]["rotatable"] = False
    job["parts"][0]["qty"] = 3
    blocked = nest.run_job(job)
    assert blocked["plate_reports"] == []
    assert blocked["unplaced"] == [
        {
            "item_id": blocked["unplaced"][0]["item_id"],
            "label": "SYNTHETIC-PART-1",
            "quantity": 3,
            "size": "10 x 6",
            "reason": "no_compatible_stock_fit",
        }
    ]


def test_material_groups_and_same_name_stock_variants_remain_distinct():
    job = json.loads(
        (
            ROOT / "tests" / "fixtures" / "nest" / "grouped-engine.json"
        ).read_text()
    )
    result = nest.run_job(job)
    assert len(result["groups"]) == 2
    assert {
        (group["material"], group["grade"], group["thickness"])
        for group in result["groups"]
    } == {
        ("carbon_steel", "A36", 0.5),
        ("carbon_steel", "A572", 0.375),
    }
    assert len({plate["stock_id"] for plate in result["plate_reports"]}) == 2
    assert len(result["rfq_nesting"]["rows"]) == 2

    reordered = deepcopy(job)
    reordered["parts"].reverse()
    reordered["stock"].reverse()
    reordered_result = nest.run_job(reordered)
    assert reordered_result["normalized_input_hash"] == result["normalized_input_hash"]
    assert [
        placement["placement_id"]
        for plate in reordered_result["plate_reports"]
        for placement in plate["placements"]
    ] == [
        placement["placement_id"]
        for plate in result["plate_reports"]
        for placement in plate["placements"]
    ]


def test_finite_exhaustion_blocks_and_unlimited_stock_opens_only_when_compatible():
    job = base_job()
    job["parts"][0]["qty"] = 2
    job["stock"].append(
        {
            "stock_id": "SYNTHETIC-STOCK-INCOMPATIBLE",
            "name": "Synthetic Plate",
            "material": "carbon_steel",
            "grade": "A572",
            "width": 11,
            "height": 7,
            "thickness": 0.5,
            "unlimited": True,
        }
    )
    exhausted = nest.run_job(job)
    assert exhausted["unplaced"][0]["reason"] == "stock_exhausted"
    assert exhausted["unplaced"][0]["quantity"] == 1

    job["stock"][1]["grade"] = "A36"
    complete = nest.run_job(job)
    assert complete["unplaced"] == []
    assert complete["plates_used"] == 2


def test_cost_bases_reconcile_and_conflicts_block_before_placement():
    per_sheet = base_job()
    per_sheet["stock"][0].update(cost_per_sheet=100, synthetic_cost=True)
    sheet_result = nest.run_job(per_sheet)
    assert sheet_result["cost"]["status"] == "known"
    assert sheet_result["cost"]["total"] == 100

    per_pound = base_job()
    per_pound["stock"][0].update(cost_per_lb=1, synthetic_cost=True)
    pound_result = nest.run_job(per_pound)
    expected = 11 * 7 * 0.5 * 0.2836
    assert pound_result["cost"]["total"] == pytest.approx(expected, abs=0.01)

    conflict = deepcopy(per_sheet)
    conflict["stock"][0]["cost_per_lb"] = 1
    blocked = nest.run_job(conflict)
    assert blocked["plate_reports"] == []
    assert any(
        finding["code"] == "conflicting_cost_basis"
        for finding in blocked["validation_findings"]
    )


def test_unplaced_without_open_plate_never_reports_known_zero_cost():
    job = base_job()
    job["stock"][0]["qty"] = 0
    result = nest.run_job(job)
    assert result["unplaced"][0]["quantity"] == 1
    assert result["cost"]["status"] == "incomplete_unplaced"
    assert result["cost"]["total"] is None


def test_packing_and_net_yield_are_separate_and_labeled():
    job = base_job()
    job["stock"][0].update(width=20, height=20)
    job["parts"][0].update(
        shape="irregular",
        area=24,
        holes=[{"dia": 1, "x": 5, "y": 3}],
    )
    result = nest.run_job(job)
    metrics = result["metrics"]
    assert metrics["packing_utilization_pct"]["value"] == 15.0
    assert metrics["net_material_yield_pct"]["value"] < 6.0
    assert metrics["packing_utilization_pct"]["approximation"] == "bounding_box"
    assert metrics["net_material_yield_pct"]["approximation"] == "declared_area"
    assert "overall_yield_pct" not in result
