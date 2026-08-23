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
