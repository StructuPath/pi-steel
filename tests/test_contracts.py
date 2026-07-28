import copy
import json
import math
import sys
from pathlib import Path

import jsonschema
import pytest


ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "skills" / "_shared"
sys.path.insert(0, str(SHARED))

from pi_steel.contracts import (
    ESTIMATE_PACKAGE_VERSION,
    NEST_RESULT_VERSION,
    instance_ids,
    item_id_for,
    placement_ids,
)
from pi_steel.run_manifest import PACKAGE_STATUSES, RUN_OUTCOMES
from pi_steel.geometry_verify import group_plate_items
from pi_steel.parsing import adapt_legacy_bom_csv, adapt_legacy_nest
from pi_steel.validation import (
    acknowledge_finding,
    eligible_on_hand_stock,
    purchasable_items,
    stock_requiring_purchase,
    validate_estimate_package,
)


FIXTURES = ROOT / "tests" / "fixtures" / "contracts"


def valid_package():
    source_id = "SYNTHETIC-SRC-P1"
    return {
        "schema_version": ESTIMATE_PACKAGE_VERSION,
        "project": {
            "project_id": "SYNTHETIC-CONTRACT-001",
            "revision": {"revision_id": "SYNTHETIC-REV-A"},
        },
        "unit_system": "imperial",
        "items": [
            {
                "intent": "fabricated_part",
                "source_id": source_id,
                "item_id": item_id_for(
                    "SYNTHETIC-CONTRACT-001", "SYNTHETIC-REV-A", source_id
                ),
                "quantity": 2,
                "mark": "SYNTHETIC-P1",
                "material": "carbon_steel",
                "grade": "A36",
                "geometry": {
                    "shape": "rect",
                    "width": 8,
                    "height": 6,
                    "thickness": 0.5,
                    "holes": [{"kind": "round", "diameter": 1, "x": 2, "y": 2}],
                },
                "source_evidence": [
                    {
                        "source": "SYNTHETIC-DRAWING",
                        "locator": "SYNTHETIC-DETAIL-1",
                    }
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


def blocker_codes(result):
    return {f["code"] for f in result.findings if f["severity"] == "blocker"}


def warning_codes(result):
    return {f["code"] for f in result.findings if f["severity"] == "warning"}


def test_contract_schemas_are_draft_2020_12_and_accept_canonical_package():
    package = valid_package()
    estimate_schema = json.loads(
        (SHARED / "schemas" / "estimate-package.schema.json").read_text()
    )
    nest_schema = json.loads(
        (SHARED / "schemas" / "nest-result.schema.json").read_text()
    )
    assert estimate_schema["$schema"].endswith("/draft/2020-12/schema")
    assert nest_schema["$schema"].endswith("/draft/2020-12/schema")
    jsonschema.Draft202012Validator(estimate_schema).validate(package)
    assert nest_schema["properties"]["schema_version"]["const"] == NEST_RESULT_VERSION
    assert set(nest_schema["properties"]["outcome"]["enum"]) == set(RUN_OUTCOMES)
    assert set(nest_schema["properties"]["package_status"]["enum"]) == set(
        PACKAGE_STATUSES
    )


def test_legacy_bom_preserves_marks_grades_lengths_weights_and_explicit_ids():
    package = adapt_legacy_bom_csv(
        FIXTURES / "legacy-bom.csv",
        project_id="SYNTHETIC-CONTRACT-001",
        revision_id="SYNTHETIC-REV-A",
    )
    rows = package["items"]
    assert [row["mark"] for row in rows] == ["B1", "H1"]
    assert [row["grade"] for row in rows] == ["A992", "A500 GR.C"]
    assert [row["length_ft"] for row in rows] == [12.5, 8.5]
    assert [row["unit_weight_plf"] for row in rows] == [26.0, 27.48]
    assert [row["source_id"] for row in rows] == [
        "SYNTHETIC-SRC-B1",
        "SYNTHETIC-SRC-H1",
    ]


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (lambda p: p["items"][0].update(quantity=0), "invalid_quantity"),
        (
            lambda p: p["items"][0]["geometry"].update(width=math.inf),
            "nonfinite_dimension",
        ),
        (
            lambda p: p["items"][0]["geometry"].update(shape="ellipse"),
            "unsupported_shape",
        ),
        (
            lambda p: p["items"][0]["geometry"].update(
                holes=[{"kind": "round", "diameter": 4, "x": 0.5, "y": 0.5}]
            ),
            "hole_out_of_bounds",
        ),
        (
            lambda p: p["items"][0]["geometry"].update(
                width=1,
                height=1,
                holes=[{"kind": "round", "diameter": 2, "x": 0.5, "y": 0.5}],
            ),
            "nonpositive_net_area",
        ),
    ],
)
def test_field_specific_geometry_and_quantity_blockers(mutation, expected_code):
    package = valid_package()
    mutation(package)
    result = validate_estimate_package(package)
    assert expected_code in blocker_codes(result)
    assert all(f["path"] for f in result.findings)


def test_duplicate_source_and_item_ids_are_blockers():
    package = valid_package()
    package["items"].append(copy.deepcopy(package["items"][0]))
    codes = blocker_codes(validate_estimate_package(package))
    assert {"duplicate_source_id", "duplicate_item_id"} <= codes


def test_grouping_never_mixes_material_grade_or_thickness():
    package = valid_package()
    items = [package["items"][0]]
    for field, value in (("grade", "A572"), ("material", "stainless_steel")):
        changed = copy.deepcopy(items[0])
        changed["item_id"] += f"-{field}"
        changed[field] = value
        items.append(changed)
    changed = copy.deepcopy(items[0])
    changed["item_id"] += "-thickness"
    changed["geometry"]["thickness"] = 0.375
    items.append(changed)
    groups = group_plate_items(items)
    assert len(groups) == 4


def test_allowances_are_totals_only_and_never_purchased():
    package = valid_package()
    package["items"].append(
        {
            "intent": "allowance",
            "source_id": "SYNTHETIC-SRC-ALLOWANCE",
            "item_id": "item:synthetic-allowance",
            "quantity": 1,
            "description": "Synthetic connection allowance",
            "allowance_basis": {
                "kind": "percent",
                "value": 10,
                "applies_to": "fabricated_weight",
            },
        }
    )
    assert [item["intent"] for item in purchasable_items(package)] == [
        "fabricated_part"
    ]


def test_on_hand_stock_requires_traceable_confirmed_inventory():
    package = valid_package()
    stock = {
        "stock_kind": "on_hand",
        "inventory_id": "SYNTHETIC-INV-1",
        "material": "carbon_steel",
        "grade": "A36",
        "width": 48,
        "height": 24,
        "thickness": 0.5,
        "quantity": 1,
        "status": "available",
        "measured_at": "2026-07-28",
        "source": "SYNTHETIC-INVENTORY",
        "reviewer_confirmation": {
            "actor": "Example Reviewer",
            "timestamp": "2026-07-28T12:00:00Z",
            "estimate_hash": "",
        },
    }
    package["stock"] = [stock]
    assert eligible_on_hand_stock(package) == []
    stock["reviewer_confirmation"]["estimate_hash"] = validate_estimate_package(
        package
    ).input_hash
    assert eligible_on_hand_stock(package) == [stock]
    assert stock_requiring_purchase(package) == []
    del stock["inventory_id"]
    assert eligible_on_hand_stock(package) == []
    assert stock_requiring_purchase(package) == []


def test_missing_source_evidence_is_visible_warning_and_ack_is_hash_bound():
    package = valid_package()
    package["items"][0].pop("source_evidence")
    result = validate_estimate_package(package)
    assert "missing_source_evidence" in warning_codes(result)
    finding = next(f for f in result.findings if f["code"] == "missing_source_evidence")
    acknowledge_finding(
        package,
        finding,
        actor="Example Reviewer",
        timestamp="2026-07-28T12:00:00Z",
        disposition="accepted",
    )
    assert not any(
        f["code"] == "missing_source_evidence"
        for f in validate_estimate_package(package).active_findings
    )
    package["project"]["revision"]["revision_id"] = "SYNTHETIC-REV-B"
    assert "missing_source_evidence" in {
        f["code"] for f in validate_estimate_package(package).active_findings
    }


def test_legacy_nest_inherits_explicit_job_basis_but_never_invents_missing_basis():
    legacy = json.loads((FIXTURES / "legacy-nest.json").read_text())
    package = adapt_legacy_nest(
        legacy,
        project_id="SYNTHETIC-CONTRACT-001",
        revision_id="SYNTHETIC-REV-A",
    )
    part = package["items"][0]
    assert (part["material"], part["grade"], part["geometry"]["thickness"]) == (
        "carbon_steel",
        "A36",
        0.5,
    )
    legacy.pop("grade")
    missing = adapt_legacy_nest(
        legacy,
        project_id="SYNTHETIC-CONTRACT-001",
        revision_id="SYNTHETIC-REV-A",
    )
    result = validate_estimate_package(missing)
    assert result.status == "review_required"
    assert "missing_material_basis" in blocker_codes(result)


def test_unknown_version_gets_migration_diagnostic():
    package = valid_package()
    package["schema_version"] = "99.0.0"
    result = validate_estimate_package(package)
    assert result.status == "invalid"
    assert result.findings[0]["code"] == "unsupported_contract_version"
    assert "migrate" in result.findings[0]["message"].lower()


def test_identifiers_are_reorder_stable_and_quantity_expansion_is_predictable():
    source_ids = ["SYNTHETIC-SRC-A", "SYNTHETIC-SRC-B"]
    forward = [
        item_id_for("SYNTHETIC-PROJECT", "SYNTHETIC-REV-A", source)
        for source in source_ids
    ]
    reverse = [
        item_id_for("SYNTHETIC-PROJECT", "SYNTHETIC-REV-A", source)
        for source in reversed(source_ids)
    ]
    assert forward == list(reversed(reverse))
    assert item_id_for(
        "SYNTHETIC-PROJECT", "SYNTHETIC-REV-B", source_ids[0]
    ) == item_id_for(
        "SYNTHETIC-PROJECT", "SYNTHETIC-REV-A", source_ids[0]
    )
    assert instance_ids(forward[0], 2) == instance_ids(forward[0], 3)[:2]
    assert placement_ids(forward[0], 2) == placement_ids(forward[0], 3)[:2]


def test_acknowledgement_cannot_waive_a_blocking_validation_error():
    package = valid_package()
    package["items"][0]["quantity"] = 0
    result = validate_estimate_package(package)
    finding = next(f for f in result.findings if f["code"] == "invalid_quantity")
    acknowledge_finding(
        package,
        finding,
        actor="Example Reviewer",
        timestamp="2026-07-28T12:00:00Z",
        disposition="accepted",
    )

    assert "invalid_quantity" in blocker_codes(validate_estimate_package(package))


def test_missing_legacy_mark_uses_revision_scoped_id_and_duplicate_rows_do_not_merge(
    tmp_path,
):
    csv_path = tmp_path / "synthetic-unmarked.csv"
    csv_path.write_text(
        "Mark,Qty,Size,Grade,Length_ft,Unit_Wt_plf\n"
        ",1,W8X10,A992,4,10\n"
        ",1,W8X10,A992,4,10\n",
        encoding="utf-8",
    )
    package = adapt_legacy_bom_csv(
        csv_path,
        project_id="SYNTHETIC-CONTRACT-001",
        revision_id="SYNTHETIC-REV-A",
    )
    assert package["items"][0]["source_id"].startswith("legacy:SYNTHETIC-REV-A:")
    assert "unstable_source_identity" in warning_codes(
        validate_estimate_package(package)
    )
    assert "duplicate_source_id" in blocker_codes(validate_estimate_package(package))


def test_absent_costs_do_not_create_prices_and_explicit_cost_preserves_basis():
    package = valid_package()
    assert package["commercial_basis"]["costs"] == []
    package["commercial_basis"]["costs"].append(
        {
            "cost_id": "SYNTHETIC-COST-1",
            "amount": 1,
            "currency": "USD",
            "unit_basis": "per_pound",
            "effective_date": "2026-07-28",
            "source": "synthetic_test_input",
            "synthetic": True,
        }
    )
    result = validate_estimate_package(package)
    assert "invalid_cost_basis" not in blocker_codes(result)
