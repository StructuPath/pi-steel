import importlib.util
import random
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

import pi_steel.geometry_verify as geometry_verify
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


def _brute_force_overlap_paths(placements, clearance, epsilon=1e-9):
    paths = []
    for first_index, first in enumerate(placements):
        for second_index in range(first_index + 1, len(placements)):
            second = placements[second_index]
            if not (
                geometry_verify._finite_placement_values(first)
                and geometry_verify._finite_placement_values(second)
            ):
                continue
            if not geometry_verify._placements_separated(
                first, second, clearance, epsilon
            ):
                paths.append(
                    f"$.plate_reports[0].placements[{first_index},{second_index}]"
                )
    return paths


def test_sweep_line_overlap_results_match_all_pairs_reference():
    generator = random.Random(20260728)
    placements = [
        {
            "x": generator.uniform(0, 90),
            "y": generator.uniform(0, 40),
            "w": generator.uniform(0.25, 8),
            "h": generator.uniform(0.25, 8),
            "material": "carbon_steel",
            "grade": "A36",
            "thickness": 0.5,
        }
        for _ in range(150)
    ]
    plate = {
        "W": 100,
        "H": 50,
        "material": "carbon_steel",
        "grade": "A36",
        "thickness": 0.5,
        "placements": placements,
    }
    actual = [
        finding["path"]
        for finding in verify_nest_placements(
            [plate], edge_margin=0, inter_part_clearance=0.25
        )
        if finding["code"] == "placement_overlap"
    ]
    assert actual == _brute_force_overlap_paths(placements, 0.25)


def test_sweep_line_avoids_all_pairs_on_large_separated_layout(monkeypatch):
    placements = [
        {
            "x": index * 2.0,
            "y": 0.0,
            "w": 1.0,
            "h": 1.0,
            "material": "carbon_steel",
            "grade": "A36",
            "thickness": 0.5,
        }
        for index in range(4_000)
    ]
    plate = {
        "W": 8_001,
        "H": 2,
        "material": "carbon_steel",
        "grade": "A36",
        "thickness": 0.5,
        "placements": placements,
    }
    checks = 0
    original = geometry_verify._placements_separated

    def counted(*args, **kwargs):
        nonlocal checks
        checks += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(geometry_verify, "_placements_separated", counted)
    assert verify_nest_placements(
        [plate], edge_margin=0, inter_part_clearance=0.25
    ) == []
    assert checks < len(placements) * 4
