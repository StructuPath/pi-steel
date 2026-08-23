import importlib.util
import sys
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "skills" / "_shared"
sys.path.insert(0, str(SHARED))
CUTLIST_SCRIPT = ROOT / "skills" / "steel-cutlist" / "scripts" / "cutlist.py"
SPEC = importlib.util.spec_from_file_location("pi_steel_cutlist_engine", CUTLIST_SCRIPT)
cutlist = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cutlist
SPEC.loader.exec_module(cutlist)

from pi_steel import canonical_json_bytes, sha256_bytes  # noqa: E402


def base_job():
    return {
        "job_name": "SYNTHETIC-CUTLIST-ENGINE",
        "project_id": "SYNTHETIC-PRJ",
        "revision_id": "SYNTHETIC-REV",
        "unit_system": "imperial",
        "settings": {"kerf_in": 0.125, "end_trim_in": 0.25, "min_drop_in": 24},
        "members": [
            {
                "source_id": "SYNTHETIC-M1",
                "name": "SYNTHETIC-B1",
                "designation": "W12X26",
                "grade": "A992",
                "length_in": 342,
                "qty": 4,
            },
            {
                "source_id": "SYNTHETIC-M2",
                "name": "SYNTHETIC-B2",
                "designation": "W12X26",
                "grade": "A992",
                "length_ft": "12'-6",
                "qty": 6,
            },
        ],
        "stock": [
            {
                "stock_id": "SYNTHETIC-STK-40",
                "designation": "W12X26",
                "grade": "A992",
                "length_ft": 40,
                "unlimited": True,
                "cost_per_ft": 31.2,
            },
            {
                "stock_id": "SYNTHETIC-STK-50",
                "designation": "W12X26",
                "grade": "A992",
                "length_ft": 50,
                "unlimited": True,
                "cost_per_ft": 39.0,
            },
        ],
    }


def test_exact_fit_consumes_bar_without_trailing_kerf_rejection():
    job = {
        **base_job(),
        "members": [
            {
                "source_id": "SYNTHETIC-EXACT",
                "name": "SYNTHETIC-EXACT",
                "designation": "W12X26",
                "grade": "A992",
                "length_in": 479.5,
                "qty": 1,
            }
        ],
        "stock": [
            {
                "stock_id": "SYNTHETIC-STK-EXACT",
                "designation": "W12X26",
                "grade": "A992",
                "length_in": 480,
                "qty": 1,
            }
        ],
    }
    result = cutlist.run_job(job)
    assert result["outcome"] == "ready"
    assert result["unplaced"] == []
    report = result["bar_reports"][0]
    assert report["usable_length_in"] == 479.5
    assert report["drop_in"] == 0
    assert result["fit_contract"]["consumption_per_piece"] == (
        "length_plus_one_kerf_saturating"
    )


def test_feet_inches_string_parses_and_kerf_accounting():
    result = cutlist.run_job(base_job())
    lengths = sorted(
        {cut["length_in"] for report in result["bar_reports"] for cut in report["cuts"]}
    )
    assert lengths == [150, 342]
    for report in result["bar_reports"]:
        assert report["kerf_total_in"] == round(0.125 * report["num_cuts"], 3)
        consumed = report["cut_length_in"] + report["kerf_total_in"]
        assert consumed <= report["usable_length_in"] + report["num_cuts"] * 0.125


def test_portfolio_prefers_cheaper_single_length_at_equal_total_length():
    result = cutlist.run_job(base_job())
    assert result["outcome"] == "ready"
    assert result["unplaced"] == []
    summary = result["purchase_summary"]
    assert len(summary) == 1
    assert summary[0]["stock_id"] == "SYNTHETIC-STK-40"
    assert summary[0]["bars_needed"] == 6
    assert result["total_material_cost"] == 7488.0


def test_incompatible_groups_never_mix_and_missing_stock_blocks():
    job = base_job()
    job["members"].append(
        {
            "source_id": "SYNTHETIC-M3",
            "name": "SYNTHETIC-ANGLE",
            "designation": "L4X4X1/4",
            "grade": "A36",
            "length_in": 100,
            "qty": 2,
        }
    )
    result = cutlist.run_job(job)
    assert result["outcome"] == "blocked"
    assert result["package_status"] == "cutlist_partial"
    unplaced = {row["designation"]: row for row in result["unplaced"]}
    assert unplaced["L4X4X1/4"]["reason"] == "no_compatible_stock_fit"
    assert unplaced["L4X4X1/4"]["quantity"] == 2
    for report in result["bar_reports"]:
        for cut in report["cuts"]:
            assert (cut["designation"], cut["grade"]) == (
                report["designation"],
                report["grade"],
            )


def test_finite_stock_exhaustion_reports_reason_and_partial_status():
    job = base_job()
    job["stock"] = [
        {
            "stock_id": "SYNTHETIC-STK-FINITE",
            "designation": "W12X26",
            "grade": "A992",
            "length_ft": 40,
            "qty": 1,
        }
    ]
    result = cutlist.run_job(job)
    assert result["outcome"] == "blocked"
    assert result["package_status"] == "cutlist_partial"
    assert all(row["reason"] == "stock_exhausted" for row in result["unplaced"])
    assert result["cost"]["status"] == "incomplete_unplaced"
    assert result["total_material_cost"] is None


def test_ambiguous_length_basis_is_an_error_finding():
    job = base_job()
    job["members"][0]["length_ft"] = 28.5
    both = cutlist.run_job(job)
    assert any(
        finding["code"] == "ambiguous_length_basis"
        for finding in both["validation_findings"]
    )
    assert both["outcome"] == "blocked"

    job = base_job()
    del job["members"][0]["length_in"]
    neither = cutlist.run_job(job)
    assert any(
        finding["code"] == "ambiguous_length_basis"
        for finding in neither["validation_findings"]
    )


def test_aisc_weight_lookup_and_unknown_weight_warning():
    known = cutlist.run_job(base_job())
    cut = known["bar_reports"][0]["cuts"][0]
    assert cut["weight_basis"] == "aisc_database"
    assert known["weight_status"] == "known"
    expected = round(26.0 * cut["length_in"] / 12.0, 1)
    assert cut["weight_lbs"] == expected

    job = base_job()
    job["members"][0]["designation"] = "W12X999"
    job["stock"].append(
        {
            "stock_id": "SYNTHETIC-STK-UNKNOWN",
            "designation": "W12X999",
            "grade": "A992",
            "length_ft": 40,
            "unlimited": True,
        }
    )
    unknown = cutlist.run_job(job)
    assert any(
        finding["code"] == "unknown_unit_weight"
        and finding["severity"] == "warning"
        for finding in unknown["validation_findings"]
    )
    assert unknown["weight_status"] == "incomplete"
    assert unknown["total_cut_weight_lbs"] is None
    assert unknown["outcome"] == "ready"


def test_declared_unit_weight_overrides_database():
    job = base_job()
    job["members"][0]["unit_weight_plf"] = 30.0
    result = cutlist.run_job(job)
    declared = [
        cut
        for report in result["bar_reports"]
        for cut in report["cuts"]
        if cut["weight_basis"] == "declared"
    ]
    assert declared
    assert declared[0]["weight_lbs"] == round(30.0 * declared[0]["length_in"] / 12.0, 1)


def test_conflicting_cost_basis_is_an_error():
    job = base_job()
    job["stock"][0]["cost_per_bar"] = 1000
    result = cutlist.run_job(job)
    assert any(
        finding["code"] == "conflicting_cost_basis"
        for finding in result["validation_findings"]
    )
    assert result["outcome"] == "blocked"


def test_drop_classification_threshold():
    result = cutlist.run_job(base_job())
    for report in result["bar_reports"]:
        expected = (
            "reusable_candidate" if report["drop_in"] >= 24 else "offcut"
        )
        assert report["drop_class"] == expected
    for drop in result["drops"]:
        assert drop["length_in"] >= 24
        assert drop["status"] == "candidate_unverified"


def test_determinism_same_input_same_result_hash():
    first = cutlist.run_job(deepcopy(base_job()))
    second = cutlist.run_job(deepcopy(base_job()))
    assert sha256_bytes(canonical_json_bytes(first)) == sha256_bytes(
        canonical_json_bytes(second)
    )


def test_every_instance_is_cut_exactly_once_or_reported_unplaced():
    job = base_job()
    job["stock"] = [
        {
            "stock_id": "SYNTHETIC-STK-FINITE",
            "designation": "W12X26",
            "grade": "A992",
            "length_ft": 40,
            "qty": 3,
        }
    ]
    result = cutlist.run_job(job)
    cut_instances = [
        cut["instance_id"]
        for report in result["bar_reports"]
        for cut in report["cuts"]
    ]
    assert len(cut_instances) == len(set(cut_instances))
    total = len(cut_instances) + sum(row["quantity"] for row in result["unplaced"])
    assert total == 10
    assert result["verification"]["status"] == "verified"


def test_independent_verifier_catches_tampered_bars():
    result = cutlist.run_job(base_job())
    reports = deepcopy(result["bar_reports"])
    reports[0]["cuts"].append({**reports[0]["cuts"][0]})
    expected = {
        cut["instance_id"]
        for report in result["bar_reports"]
        for cut in report["cuts"]
    }
    findings = cutlist.verify_cutlist_bars(
        reports, kerf=0.125, expected_instances=expected
    )
    codes = {finding["code"] for finding in findings}
    assert "DUPLICATE_PLACEMENT" in codes
    assert "BAR_OVERCOMMITTED" in codes

    tampered = deepcopy(result["bar_reports"])
    tampered[0]["cuts"][0]["grade"] = "A36"
    findings = cutlist.verify_cutlist_bars(
        tampered, kerf=0.125, expected_instances=expected
    )
    assert any(
        finding["code"] == "BAR_MATERIAL_MISMATCH" for finding in findings
    )

    missing = deepcopy(result["bar_reports"])
    removed = missing[0]["cuts"].pop()
    findings = cutlist.verify_cutlist_bars(
        missing, kerf=0.125, expected_instances=expected
    )
    assert any(
        finding["code"] == "INSTANCE_UNACCOUNTED"
        and removed["instance_id"] in finding["message"]
        for finding in findings
    )


def test_unusable_stock_length_is_an_error():
    job = base_job()
    job["settings"]["end_trim_in"] = 300
    result = cutlist.run_job(job)
    assert any(
        finding["code"] == "unusable_stock_length"
        for finding in result["validation_findings"]
    )
    assert result["outcome"] == "blocked"


def test_designation_normalization_matches_across_case_and_spaces():
    job = base_job()
    job["members"][0]["designation"] = "w12 x 26"
    result = cutlist.run_job(job)
    assert result["unplaced"] == []
    assert result["outcome"] == "ready"


def test_rfq_linear_block_carries_identity_and_rows():
    result = cutlist.run_job(base_job())
    handoff = result["rfq_linear"]
    assert handoff["schema_version"] == "1.0.0"
    assert handoff["project_id"] == "SYNTHETIC-PRJ"
    assert handoff["estimate_input_hash"] == result["estimate_input_hash"]
    assert len(handoff["rows"]) == len(result["purchase_summary"])
    row = handoff["rows"][0]
    assert row["bars_needed"] == 6
    assert "cutting_plan" in row and "drop_notes" in row


def test_negative_quantity_blocks_without_crashing():
    job = base_job()
    job["members"][0]["qty"] = -3
    result = cutlist.run_job(job)
    assert result["outcome"] == "blocked"
    assert any(
        finding["code"] == "invalid_quantity"
        for finding in result["validation_findings"]
    )
    assert result["verification"]["status"] == "not_run"


def test_blocked_runs_report_verification_not_run():
    job = base_job()
    del job["members"][0]["grade"]
    job["grade"] = None
    result = cutlist.run_job(job)
    assert result["outcome"] == "blocked"
    assert result["verification"]["status"] == "not_run"

    ready = cutlist.run_job(base_job())
    assert ready["verification"]["status"] == "verified"


def test_rfq_linear_rows_carry_per_group_utilization():
    job = base_job()
    job["members"].append(
        {
            "source_id": "SYNTHETIC-M-HSS",
            "name": "SYNTHETIC-HSS",
            "designation": "HSS6X6X1/2",
            "grade": "A500B",
            "length_in": 200,
            "qty": 1,
            "unit_weight_plf": 35.24,
        }
    )
    job["stock"].append(
        {
            "stock_id": "SYNTHETIC-STK-HSS",
            "designation": "HSS6X6X1/2",
            "grade": "A500B",
            "length_ft": 40,
            "unlimited": True,
        }
    )
    result = cutlist.run_job(job)
    rows = {row["stock_id"]: row for row in result["rfq_linear"]["rows"]}
    for stock_id, row in rows.items():
        matching = [
            report
            for report in result["bar_reports"]
            if report["stock_id"] == stock_id
        ]
        expected = round(
            100
            * sum(report["cut_length_in"] for report in matching)
            / sum(report["bar_length_in"] for report in matching),
            1,
        )
        assert row["utilization_pct"] == expected
    assert len({row["utilization_pct"] for row in rows.values()}) > 1


def test_cutting_list_preserves_sixteenth_inch_precision():
    job = base_job()
    job["members"] = [
        {
            "source_id": "SYNTHETIC-M-PRECISE",
            "name": "SYNTHETIC-PRECISE",
            "designation": "W12X26",
            "grade": "A992",
            "length_in": 342.0625,
            "qty": 1,
        }
    ]
    result = cutlist.run_job(job)
    csv_text = cutlist.render_cutting_list_csv(result)
    assert "342.0625" in csv_text


def test_on_hand_stick_covering_members_eliminates_purchasing():
    job = base_job()
    job["members"] = [
        {
            "source_id": "SYNTHETIC-M-SHORT",
            "name": "SYNTHETIC-SHORT",
            "designation": "W12X26",
            "grade": "A992",
            "length_in": 144,
            "qty": 2,
        }
    ]
    job["stock"].append(
        {
            "stock_id": "SYNTHETIC-ONHAND-30",
            "stock_kind": "on_hand",
            "designation": "W12X26",
            "grade": "A992",
            "length_ft": 30,
            "qty": 1,
        }
    )
    result = cutlist.run_job(job)
    assert result["outcome"] == "ready"
    assert result["bars_used"] == 1
    report = result["bar_reports"][0]
    assert report["stock_kind"] == "on_hand"
    assert report["cost_basis"] == "on_hand"
    assert report["bar_cost"] is None
    summary = result["purchase_summary"][0]
    assert summary["stock_kind"] == "on_hand"
    assert result["cost"]["status"] == "known"
    assert result["total_material_cost"] == 0.0
    assert result["rfq_linear"]["rows"][0]["stock_kind"] == "on_hand"


def test_on_hand_stock_rejects_unlimited_and_cost_basis():
    job = base_job()
    job["stock"].append(
        {
            "stock_id": "SYNTHETIC-ONHAND-BAD",
            "stock_kind": "on_hand",
            "designation": "W12X26",
            "grade": "A992",
            "length_ft": 30,
            "unlimited": True,
            "cost_per_ft": 10.0,
        }
    )
    result = cutlist.run_job(job)
    codes = {finding["code"] for finding in result["validation_findings"]}
    assert "unlimited_on_hand_stock" in codes
    assert "cost_basis_on_hand_stock" in codes
    assert result["outcome"] == "blocked"


def test_invalid_stock_kind_is_an_error():
    job = base_job()
    job["stock"][0]["stock_kind"] = "borrowed"
    result = cutlist.run_job(job)
    assert any(
        finding["code"] == "invalid_stock_kind"
        for finding in result["validation_findings"]
    )
    assert result["outcome"] == "blocked"


def test_string_unlimited_flag_is_rejected_not_coerced():
    job = base_job()
    job["stock"][0]["unlimited"] = "false"
    result = cutlist.run_job(job)
    assert any(
        finding["code"] == "invalid_unlimited_flag"
        for finding in result["validation_findings"]
    )
    assert result["outcome"] == "blocked"


def test_anonymous_on_hand_and_purchasable_rows_get_distinct_ids():
    job = base_job()
    job["stock"] = [
        {
            "designation": "W12X26",
            "grade": "A992",
            "length_ft": 40,
            "qty": 5,
        },
        {
            "stock_kind": "on_hand",
            "designation": "W12X26",
            "grade": "A992",
            "length_ft": 40,
            "qty": 1,
        },
    ]
    result = cutlist.run_job(job)
    assert not any(
        finding["code"] == "duplicate_stock_id"
        for finding in result["validation_findings"]
    )
    assert result["outcome"] == "ready"


def test_exact_search_beats_greedy_on_classic_bfd_failure():
    # Best-fit-decreasing packs [5,5], [4,4], [3,3,3], [3] onto four bars of
    # capacity 10; the exact search finds the optimal [5,5], [4,3,3], [4,3,3].
    job = {
        "job_name": "SYNTHETIC-EXACT",
        "project_id": "SYNTHETIC-PRJ",
        "revision_id": "SYNTHETIC-REV",
        "unit_system": "imperial",
        "settings": {"kerf_in": 0, "end_trim_in": 0, "min_drop_in": 1000},
        "members": [
            {
                "source_id": f"SYNTHETIC-E{length}",
                "name": f"SYNTHETIC-E{length}",
                "designation": "FB1X1",
                "grade": "A36",
                "length_in": length,
                "qty": qty,
                "unit_weight_plf": 3.4,
            }
            for length, qty in ((5, 2), (4, 2), (3, 4))
        ],
        "stock": [
            {
                "stock_id": "SYNTHETIC-STK-10",
                "designation": "FB1X1",
                "grade": "A36",
                "length_in": 10,
                "unlimited": True,
            }
        ],
    }
    result = cutlist.run_job(job)
    assert result["outcome"] == "ready"
    assert result["bars_used"] == 3
    assert result["verification"]["status"] == "verified"
    assert result["metrics"]["utilization_pct"]["value"] == 100.0


def test_exact_search_never_replaces_with_a_worse_solution():
    # The portfolio already finds the optimal single-length answer here; the
    # exact refinement must keep it (same purchase, same cost).
    result = cutlist.run_job(base_job())
    assert result["purchase_summary"][0]["stock_id"] == "SYNTHETIC-STK-40"
    assert result["total_material_cost"] == 7488.0


def test_large_groups_fall_back_to_portfolio_deterministically():
    job = base_job()
    job["members"] = [
        {
            "source_id": f"SYNTHETIC-L{index}",
            "name": f"SYNTHETIC-L{index}",
            "designation": "W12X26",
            "grade": "A992",
            "length_in": 100 + index,
            "qty": 2,
        }
        for index in range(10)
    ]
    first = cutlist.run_job(deepcopy(job))
    second = cutlist.run_job(deepcopy(job))
    assert first["outcome"] == "ready"
    assert sha256_bytes(canonical_json_bytes(first)) == sha256_bytes(
        canonical_json_bytes(second)
    )


def test_without_cost_basis_exact_search_minimizes_purchased_length():
    # With no prices, the objective is purchased length: the exact search
    # finds the 230 ft mixed plan (3 x 50 ft pairing 342+150, one 40 ft for
    # the last 342, one 40 ft for three 150s) that the greedy misses.
    job = base_job()
    for stock in job["stock"]:
        del stock["cost_per_ft"]
    result = cutlist.run_job(job)
    assert result["outcome"] == "ready"
    assert result["total_stock_length_ft"] == 230.0
    assert result["bars_used"] == 5
    assert result["verification"]["status"] == "verified"


def test_exact_search_finds_optimal_partial_plan_when_stock_is_finite():
    # One capacity-10 bar. Greedy places [5,5] and strands three pieces;
    # the exact search's skip branches find [4,3,3], stranding only two.
    job = {
        "job_name": "SYNTHETIC-EXACT-PARTIAL",
        "project_id": "SYNTHETIC-PRJ",
        "revision_id": "SYNTHETIC-REV",
        "unit_system": "imperial",
        "settings": {"kerf_in": 0, "end_trim_in": 0, "min_drop_in": 1000},
        "members": [
            {
                "source_id": f"SYNTHETIC-P{length}",
                "name": f"SYNTHETIC-P{length}",
                "designation": "FB1X1",
                "grade": "A36",
                "length_in": length,
                "qty": qty,
                "unit_weight_plf": 3.4,
            }
            for length, qty in ((5, 2), (4, 1), (3, 2))
        ],
        "stock": [
            {
                "stock_id": "SYNTHETIC-STK-ONE",
                "designation": "FB1X1",
                "grade": "A36",
                "length_in": 10,
                "qty": 1,
            }
        ],
    }
    result = cutlist.run_job(job)
    assert result["outcome"] == "blocked"
    assert result["package_status"] == "cutlist_partial"
    assert sum(row["quantity"] for row in result["unplaced"]) == 2
    assert all(row["reason"] == "stock_exhausted" for row in result["unplaced"])
    cuts = sorted(
        cut["length_in"]
        for report in result["bar_reports"]
        for cut in report["cuts"]
    )
    assert cuts == [3, 3, 4]
    assert result["verification"]["status"] == "verified"


def test_exact_partial_plan_prefers_stranding_one_large_over_two_small():
    # Two capacity-10 bars, pieces 8,6,4,4,4. Greedy packs [8] and [6,4],
    # stranding two 4s; the optimum packs [6,4] and [4,4], stranding only
    # the 8. (CodeRabbit review case on PR #7.)
    job = {
        "job_name": "SYNTHETIC-EXACT-PARTIAL-2",
        "project_id": "SYNTHETIC-PRJ",
        "revision_id": "SYNTHETIC-REV",
        "unit_system": "imperial",
        "settings": {"kerf_in": 0, "end_trim_in": 0, "min_drop_in": 1000},
        "members": [
            {
                "source_id": f"SYNTHETIC-Q{length}",
                "name": f"SYNTHETIC-Q{length}",
                "designation": "FB1X1",
                "grade": "A36",
                "length_in": length,
                "qty": qty,
                "unit_weight_plf": 3.4,
            }
            for length, qty in ((8, 1), (6, 1), (4, 3))
        ],
        "stock": [
            {
                "stock_id": "SYNTHETIC-STK-TWO",
                "designation": "FB1X1",
                "grade": "A36",
                "length_in": 10,
                "qty": 2,
            }
        ],
    }
    result = cutlist.run_job(job)
    assert result["outcome"] == "blocked"
    assert sum(row["quantity"] for row in result["unplaced"]) == 1
    assert result["unplaced"][0]["length_in"] == 8
    assert result["unplaced"][0]["reason"] == "stock_exhausted"
    cuts = sorted(
        cut["length_in"]
        for report in result["bar_reports"]
        for cut in report["cuts"]
    )
    assert cuts == [4, 4, 4, 6]
    assert result["verification"]["status"] == "verified"
