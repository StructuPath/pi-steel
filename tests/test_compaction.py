"""True-shape compaction: scan-to-first-contact pass, independent verifier,
and the discard-on-failure gate (v0.5 plan U2/U3)."""

import copy
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "skills" / "_shared"))

from pi_steel.geometry_verify import (  # noqa: E402
    placed_profile,
    polygon_min_distance,
    validate_outline,
    verify_true_shape_placements,
)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


nest = _load("nest_compaction", REPO / "skills" / "steel-nest" / "scripts" / "nest.py")


# The L-gusset and the Z-strap interlock: the Z's top slab slides over the
# L's arm while its offset bottom block clears the L's bottom slab by the
# 0.25-in clearance, so the Z's bounding box legally overlaps the L's.
L_OUTLINE = [[0, 0], [8, 0], [8, 3], [3, 3], [3, 6], [0, 6]]
Z_OUTLINE = [[0, 3.5], [4.75, 3.5], [4.75, 0], [7.75, 0], [7.75, 6], [0, 6]]

# Concave neighbor for the alternating-clearance fixture: a pocket opening
# right at y in [1.75, 3.5] with a tooth hanging from the pocket ceiling at
# x in [1.3, 1.7], y in [3.1, 3.5]. A 0.5 x 1 slider entering at y = 2 sees
# clear offsets, then the tooth (0.1-in gap, under the 0.25-in clearance),
# then a clear interval deep in the pocket it must never tunnel into.
NOTCH_OUTLINE = [
    [0, 0], [4, 0], [4, 1.75], [0.25, 1.75], [0.25, 3.5], [1.3, 3.5],
    [1.3, 3.1], [1.7, 3.1], [1.7, 3.5], [4, 3.5], [4, 5], [0, 5],
]

CLEARANCE = 0.25
STEP = nest.COMPACTION_STEP_IN


def interlock_job():
    return {
        "job_name": "TSC-INTERLOCK",
        "material": "carbon_steel",
        "grade": "A36",
        "unit_system": "imperial",
        "settings": {
            "kerf_in": 0.0,
            "part_gap_in": 0.25,
            "edge_margin_in": 0.5,
            "thickness_in": 0.5,
            "density_lb_in3": 0.2836,
        },
        "stock": [
            {
                "stock_id": "TSC-STOCK",
                "name": "Synthetic Plate",
                "width": 18.25,
                "height": 7,
                "thickness": 0.5,
                "qty": 1,
            }
        ],
        "parts": [
            {
                "source_id": "TSC-SRC-L",
                "name": "TSC-L",
                "width": 8,
                "height": 6,
                "qty": 1,
                "shape": "irregular",
                "outline": copy.deepcopy(L_OUTLINE),
                "rotatable": False,
            },
            {
                "source_id": "TSC-SRC-Z",
                "name": "TSC-Z",
                "width": 7.75,
                "height": 6,
                "qty": 1,
                "shape": "irregular",
                "outline": copy.deepcopy(Z_OUTLINE),
                "rotatable": False,
            },
        ],
    }


def _placement(**kwargs):
    defaults = {
        "part_id": kwargs.get("label", "part"),
        "source_id": "src",
        "item_id": kwargs.get("label", "part"),
        "instance_id": kwargs.get("label", "part") + "#1",
        "placement_id": kwargs.get("label", "part") + "#1",
        "stock_id": "stock",
        "label": "part",
        "x": 0.0,
        "y": 0.0,
        "w": 1.0,
        "h": 1.0,
        "rotated": False,
        "shape": "rect",
        "ow": kwargs.get("w", 1.0),
        "oh": kwargs.get("h", 1.0),
        "holes": [],
        "outline": [],
        "base_area": 0.0,
        "holes_area": 0.0,
        "material": "carbon_steel",
        "grade": "A36",
        "thickness": 0.5,
    }
    defaults.update(kwargs)
    return nest.Placement(**defaults)


def _by_label(result, label):
    for plate in result["plate_reports"]:
        for placement in plate["placements"]:
            if placement["label"] == label:
                return placement
    raise AssertionError(f"placement {label} not found")


# ---------------------------------------------------------------------------
# The mandatory concave fixture: scan stops at first contact, never tunnels
# ---------------------------------------------------------------------------

def test_notch_fixture_outline_is_valid():
    assert validate_outline(NOTCH_OUTLINE, 4, 5) == []


def test_scan_stops_at_first_contact_before_the_tooth():
    neighbor = _placement(
        label="notch", shape="irregular", outline=copy.deepcopy(NOTCH_OUTLINE),
        x=0.0, y=0.0, w=4.0, h=5.0, ow=4.0, oh=5.0,
    )
    slider = _placement(label="slider", x=5.0, y=2.0, w=0.5, h=1.0)
    recovered, passes = nest.compact_placements([neighbor, slider], CLEARANCE)

    # First violating offset: hypot(x - 1.7, 0.1) < 0.25 at x < 1.92913, so
    # the slider halts one step earlier, at 5.0 - 98/32 = 1.9375. The pocket
    # holds a deeper clear interval around x = 0.5 that a bisection over
    # "clear vs blocked" would tunnel into; the fixed-step scan must not.
    assert slider.x == 1.9375
    assert slider.y == 2.0
    assert neighbor.x == 0.0 and neighbor.y == 0.0
    assert recovered == 5.0 - 1.9375
    assert passes == 2  # one moving pass, one clean convergence pass

    # The deep clear interval really is clear (the trap exists): the slider
    # placed there passes true-shape verification, so only the scan order
    # keeps it out.
    parked = dict(vars(slider), x=0.5)
    assert (
        polygon_min_distance(placed_profile(parked), placed_profile(vars(neighbor)))
        >= CLEARANCE
    )


def test_scan_respects_the_exact_clearance_contact():
    # A slider directly above a slab stops exactly at the kerf-plus-gap
    # distance: contact at the clearance is legal, one step closer is not.
    slab = _placement(label="slab", x=0.0, y=0.0, w=4.0, h=2.0)
    slider = _placement(label="slider", x=1.0, y=3.0, w=1.0, h=1.0)
    nest.compact_placements([slab, slider], CLEARANCE)
    assert slider.y == 2.25
    assert slider.x == 0.0


# ---------------------------------------------------------------------------
# End-to-end: interlocking profiles recover plate, gated by the verifier
# ---------------------------------------------------------------------------

def test_interlocking_outlines_compact_and_verify():
    result = nest.run_job(interlock_job())
    assert result["outcome"] == "review_required"
    assert result["verification"]["status"] == "verified"

    plate = result["plate_reports"][0]
    compaction = plate["compaction"]
    assert compaction["ran"] is True
    assert compaction["accepted"] is True
    assert compaction["recovered_in"] == 4.75
    assert compaction["passes"] >= 1

    l_part = _by_label(result, "TSC-L")
    z_part = _by_label(result, "TSC-Z")
    assert (l_part["x"], l_part["y"]) == (0.0, 0.0)
    # The Z slid from 8.25 until its bottom block reached the clearance off
    # the L's bottom slab: 3.5 + 4.75 = 8 + 0.25.
    assert (z_part["x"], z_part["y"]) == (3.5, 0.0)
    # Bounding boxes now overlap -- the recovery is real, not box shuffling.
    assert z_part["x"] < l_part["x"] + l_part["w"]

    # Burn posture is unchanged by compaction (R3).
    assert result["geometry_readiness"] == "reference_only"
    assert result["burn_dxf_eligible"] is False


def test_compaction_is_deterministic():
    first = nest.run_job(interlock_job())
    second = nest.run_job(interlock_job())
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_remnants_rebuilt_from_compacted_layout():
    compacted = nest.run_job(interlock_job())
    boxed = nest.run_job(interlock_job(), compact_outlines=False)
    compacted_best = compacted["plate_reports"][0]["remnant_candidates"][0]
    boxed_best = boxed["plate_reports"][0]["remnant_candidates"][0]
    # Sliding the Z left frees a wider right-hand strip.
    assert compacted_best["area"] > boxed_best["area"]
    assert compacted_best["status"] == "candidate_unverified"
    # No remnant candidate may claim space the moved parts now occupy: the
    # widest strip starts right of the compacted Z bounding box.
    z_part = _by_label(compacted, "TSC-Z")
    assert compacted_best["width"] <= 17.25 - (z_part["x"] + z_part["w"] + CLEARANCE)


def test_flag_off_keeps_bounding_box_layout():
    result = nest.run_job(interlock_job(), compact_outlines=False)
    compaction = result["plate_reports"][0]["compaction"]
    assert compaction == {
        "ran": False, "accepted": False, "recovered_in": 0.0, "passes": 0,
    }
    z_part = _by_label(result, "TSC-Z")
    assert (z_part["x"], z_part["y"]) == (8.25, 0.0)
    assert result["meta"]["compact_outlines"] is False


def test_configuration_hash_tracks_compaction_but_input_hash_does_not():
    on = nest.run_job(interlock_job())
    off = nest.run_job(interlock_job(), compact_outlines=False)
    assert on["normalized_input_hash"] == off["normalized_input_hash"]
    assert on["configuration_hash"] != off["configuration_hash"]


def test_rect_only_plates_are_not_compacted():
    job = interlock_job()
    for part in job["parts"]:
        part.pop("outline")
        part["shape"] = "rect"
    result = nest.run_job(job)
    compaction = result["plate_reports"][0]["compaction"]
    assert compaction["ran"] is False
    assert result["outcome"] == "ready"
    metric = result["metrics"]["true_shape_utilization_pct"]
    assert metric["approximation"] == "exact"


def test_outline_less_irregular_part_disables_the_plate():
    job = interlock_job()
    job["parts"][1].pop("outline")
    job["parts"][1]["area"] = 33.9375
    result = nest.run_job(job)
    plate = result["plate_reports"][0]
    assert plate["compaction"]["ran"] is False
    assert "true_shape_utilization_pct" not in plate
    assert "true_shape_utilization_pct" not in result["metrics"]
    z_part = _by_label(result, "TSC-Z")
    assert z_part["x"] == 8.25


def test_true_shape_metric_reports_exact_outline_area():
    result = nest.run_job(interlock_job())
    plate = result["plate_reports"][0]
    metric = plate["true_shape_utilization_pct"]
    assert metric["approximation"] == "outline_exact"
    l_area = 8 * 6 - 5 * 3
    z_area = 7.75 * 6 - 4.75 * 3.5
    expected = 100 * (l_area + z_area) / (18.25 * 7)
    assert abs(metric["value"] - round(expected, 1)) < 0.05
    assert result["metrics"]["true_shape_utilization_pct"]["value"] == metric["value"]


# ---------------------------------------------------------------------------
# Independent verifier and the discard-on-failure gate
# ---------------------------------------------------------------------------

def test_verifier_rejects_profile_overlap_that_boxes_allow():
    l_placement = {
        "shape": "irregular", "outline": copy.deepcopy(L_OUTLINE),
        "rotated": False, "x": 0.0, "y": 0.0, "w": 8.0, "h": 6.0,
        "ow": 8.0, "oh": 6.0,
    }
    # Tucked into the notch with legal profile clearance: accepted.
    tucked = {
        "shape": "rect", "outline": [], "rotated": False,
        "x": 3.25, "y": 3.25, "w": 2.0, "h": 2.0, "ow": 2.0, "oh": 2.0,
    }
    assert verify_true_shape_placements(
        [l_placement, tucked],
        usable_width=16.0, usable_height=6.0, clearance=CLEARANCE,
    ) == []
    # One half inch lower the rect enters the L's bottom slab: rejected.
    overlapping = dict(tucked, y=2.75)
    findings = verify_true_shape_placements(
        [l_placement, overlapping],
        usable_width=16.0, usable_height=6.0, clearance=CLEARANCE,
    )
    assert [finding["code"] for finding in findings] == [
        "true_shape_clearance_violation"
    ]


def test_verifier_rebuilds_rotated_outlines():
    # A rotated L occupies (oh - y, x): the same notch tuck only verifies
    # when the verifier applies the placement rotation contract itself.
    rotated_l = {
        "shape": "irregular", "outline": copy.deepcopy(L_OUTLINE),
        "rotated": True, "x": 0.0, "y": 0.0, "w": 6.0, "h": 8.0,
        "ow": 8.0, "oh": 6.0,
    }
    # Rotated notch spans x in [0, 3], y in [3, 8] shifted: local corners
    # become (6 - y, x), so the open notch sits at x in [0, 3], y in [3, 8].
    tucked = {
        "shape": "rect", "outline": [], "rotated": False,
        "x": 0.0, "y": 3.25, "w": 2.0, "h": 2.0, "ow": 2.0, "oh": 2.0,
    }
    assert verify_true_shape_placements(
        [rotated_l, tucked],
        usable_width=12.0, usable_height=8.0, clearance=CLEARANCE,
    ) == []
    unrotated_claim = dict(rotated_l, rotated=False, w=8.0, h=6.0)
    findings = verify_true_shape_placements(
        [unrotated_claim, tucked],
        usable_width=12.0, usable_height=8.0, clearance=CLEARANCE,
    )
    assert findings, "same coordinates without rotation must collide"


def test_verifier_flags_out_of_bounds_profiles():
    placement = {
        "shape": "irregular", "outline": copy.deepcopy(L_OUTLINE),
        "rotated": False, "x": -0.5, "y": 0.0, "w": 8.0, "h": 6.0,
        "ow": 8.0, "oh": 6.0,
    }
    findings = verify_true_shape_placements(
        [placement], usable_width=16.0, usable_height=6.0, clearance=CLEARANCE,
    )
    assert [finding["code"] for finding in findings] == ["true_shape_out_of_bounds"]


def test_gate_discards_a_corrupt_compaction(monkeypatch):
    """Adversarial U3 case: a buggy compactor is rejected wholesale."""
    real = nest.compact_placements

    def corrupting(placements, clearance):
        recovered, passes = real(placements, clearance)
        for placement in placements:
            if placement.label == "TSC-Z":
                placement.x -= 1.0  # tunnel one inch into the L's clearance
                recovered += 1.0
        return recovered, passes

    monkeypatch.setattr(nest, "compact_placements", corrupting)
    result = nest.run_job(interlock_job())

    plate = result["plate_reports"][0]
    assert plate["compaction"]["ran"] is True
    assert plate["compaction"]["accepted"] is False
    assert plate["compaction"]["recovered_in"] == 0.0
    # Layout restored to the proven bounding-box packing.
    z_part = _by_label(result, "TSC-Z")
    assert (z_part["x"], z_part["y"]) == (8.25, 0.0)
    # The run proceeds exactly as the uncompacted run would (R2)...
    assert result["outcome"] == "review_required"
    assert result["verification"]["status"] == "verified"
    # ...with the rejection recorded as a non-blocking finding.
    warnings = [
        finding
        for finding in result["validation_findings"]
        if finding["code"] == "COMPACTION_REJECTED"
    ]
    assert len(warnings) == 1
    assert warnings[0]["severity"] == "warning"


# ---------------------------------------------------------------------------
# Compaction-aware refill: recovered plate becomes fewer sheets (v0.6)
# ---------------------------------------------------------------------------

def refill_job(stock_qty):
    job = interlock_job()
    job["job_name"] = "TSC-REFILL"
    job["stock"][0]["qty"] = stock_qty
    job["parts"].append(
        {
            "source_id": "TSC-SRC-FILL",
            "name": "TSC-FILL",
            "width": 4,
            "height": 6,
            "qty": 1,
            "rotatable": False,
        }
    )
    return job


def test_refill_avoids_opening_a_second_sheet():
    boxed = nest.run_job(refill_job(2), compact_outlines=False)
    assert boxed["plates_used"] == 2

    compacted = nest.run_job(refill_job(2))
    assert compacted["plates_used"] == 1
    assert compacted["unplaced"] == []
    assert compacted["outcome"] == "review_required"
    assert compacted["verification"]["status"] == "verified"

    plate = compacted["plate_reports"][0]
    assert plate["compaction"]["accepted"] is True
    assert plate["compaction"]["recovered_in"] == 4.75
    # The filler landed in the strip the compacted Z freed, one clearance
    # off the Z's full-height right face at 3.5 + 7.75 + 0.25.
    fill = _by_label(compacted, "TSC-FILL")
    assert (fill["x"], fill["y"]) == (11.5, 0.0)


def test_refill_rescues_a_stranded_part():
    boxed = nest.run_job(refill_job(1), compact_outlines=False)
    assert boxed["outcome"] == "blocked"
    assert [row["reason"] for row in boxed["unplaced"]] == ["stock_exhausted"]

    compacted = nest.run_job(refill_job(1))
    assert compacted["unplaced"] == []
    assert compacted["outcome"] == "review_required"
    assert compacted["plates_used"] == 1


def test_refill_never_uses_more_plates_or_strands_more_parts():
    for job_factory in (lambda: refill_job(1), lambda: refill_job(2), interlock_job):
        on = nest.run_job(job_factory())
        off = nest.run_job(job_factory(), compact_outlines=False)
        assert on["plates_used"] <= off["plates_used"]
        assert (
            sum(row["quantity"] for row in on["unplaced"])
            <= sum(row["quantity"] for row in off["unplaced"])
        )


def test_refill_is_deterministic():
    first = nest.run_job(refill_job(2))
    second = nest.run_job(refill_job(2))
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_midpack_rejection_falls_back_to_bounding_box_flow(monkeypatch):
    real = nest.compact_placements

    def corrupting(placements, clearance):
        recovered, passes = real(placements, clearance)
        for placement in placements:
            if placement.label == "TSC-Z":
                placement.x -= 1.0
                recovered += 1.0
        return recovered, passes

    monkeypatch.setattr(nest, "compact_placements", corrupting)
    result = nest.run_job(refill_job(2))

    # The corrupt mid-pack attempt is rejected, the plate is disqualified,
    # and packing proceeds exactly as the bounding-box flow would have.
    assert result["plates_used"] == 2
    assert result["outcome"] == "review_required"
    assert result["verification"]["status"] == "verified"
    z_part = _by_label(result, "TSC-Z")
    assert (z_part["x"], z_part["y"]) == (8.25, 0.0)
    fill = _by_label(result, "TSC-FILL")
    assert (fill["x"], fill["y"]) == (0.0, 0.0)
    warnings = [
        finding
        for finding in result["validation_findings"]
        if finding["code"] == "COMPACTION_REJECTED"
    ]
    assert len(warnings) == 1
    assert all(
        plate["compaction"]["accepted"] is False
        for plate in result["plate_reports"]
    )


def test_accepted_plate_survives_result_level_verification():
    # verify_nest_placements dispatches accepted plates to the true-shape
    # verifier; corrupting a published placement must now fail verification.
    result = nest.run_job(interlock_job())
    tampered = copy.deepcopy(result["plate_reports"])
    for placement in tampered[0]["placements"]:
        if placement["label"] == "TSC-Z":
            placement["x"] -= 1.0
    from pi_steel.geometry_verify import verify_nest_placements

    clean = verify_nest_placements(
        result["plate_reports"], edge_margin=0.5, inter_part_clearance=CLEARANCE
    )
    assert clean == []
    findings = verify_nest_placements(
        tampered, edge_margin=0.5, inter_part_clearance=CLEARANCE
    )
    assert any(
        finding["code"] == "true_shape_clearance_violation" for finding in findings
    )
