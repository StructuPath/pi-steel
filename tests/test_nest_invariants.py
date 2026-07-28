import importlib.util
import sys
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "skills" / "_shared"
sys.path.insert(0, str(SHARED))
NEST_SCRIPT = ROOT / "skills" / "steel-nest" / "scripts" / "nest.py"
SPEC = importlib.util.spec_from_file_location("pi_steel_nest_invariants", NEST_SCRIPT)
nest = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = nest
SPEC.loader.exec_module(nest)

from pi_steel.geometry_verify import verify_nest_placements


def two_part_job():
    return {
        "job_name": "SYNTHETIC-INVARIANTS",
        "material": "carbon_steel",
        "grade": "A36",
        "unit_system": "imperial",
        "settings": {
            "kerf_in": 0.05,
            "part_gap_in": 0.2,
            "edge_margin_in": 0.5,
            "thickness_in": 0.5,
        },
        "stock": [
            {
                "stock_id": "SYNTHETIC-STOCK-INVARIANT",
                "name": "Synthetic Plate",
                "width": 24,
                "height": 12,
                "thickness": 0.5,
                "qty": 1,
            }
        ],
        "parts": [
            {
                "source_id": "SYNTHETIC-SRC-A",
                "name": "SYNTHETIC-A",
                "width": 8,
                "height": 4,
                "qty": 1,
                "shape": "rect",
            },
            {
                "source_id": "SYNTHETIC-SRC-B",
                "name": "SYNTHETIC-B",
                "width": 7,
                "height": 3,
                "qty": 1,
                "shape": "rect",
            },
        ],
    }


def test_generated_placements_pass_independent_pure_verifier():
    result = nest.run_job(two_part_job())
    assert result["verification"] == {"status": "verified", "findings": []}
    assert verify_nest_placements(
        result["plate_reports"],
        edge_margin=result["meta"]["edge_margin_in"],
        inter_part_clearance=(
            result["meta"]["kerf_in"] + result["meta"]["part_gap_in"]
        ),
    ) == []


def test_verifier_rejects_overlap_bounds_clearance_and_material_mismatch():
    result = nest.run_job(two_part_job())
    plates = deepcopy(result["plate_reports"])
    first, second = plates[0]["placements"]
    second["x"], second["y"] = first["x"], first["y"]
    second["grade"] = "A572"
    first["x"] = -1
    codes = {
        finding["code"]
        for finding in verify_nest_placements(
            plates,
            edge_margin=result["meta"]["edge_margin_in"],
            inter_part_clearance=0.25,
        )
    }
    assert {"placement_out_of_bounds", "placement_overlap", "material_mismatch"} <= codes
