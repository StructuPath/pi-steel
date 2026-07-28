import importlib.util
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import openpyxl
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "steel-rfq" / "scripts" / "generate-rfq.py"
SPEC = importlib.util.spec_from_file_location("pi_steel_generate_rfq", SCRIPT)
rfq = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = rfq
SPEC.loader.exec_module(rfq)
FIXTURES = ROOT / "tests" / "fixtures" / "rfq"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def test_canonical_normalization_uses_typed_scope_and_explicit_replacements_only():
    package = load("estimate-package.json")
    normalized = rfq.normalize_canonical_package(package)
    ids = [item["item_id"] for item in normalized["items"]]
    assert "item:synthetic-p1" not in ids
    assert "item:synthetic-sheet1" in ids
    assert "item:synthetic-bo1" not in ids
    assert "item:synthetic-w1" in ids
    assert next(
        item for item in normalized["items"] if item["item_id"] == "item:synthetic-w1"
    )["description"].find("BY OTHERS") >= 0

    package["items"][2]["dimensions"].pop("replaces_item_ids")
    ids_without_relationship = [
        item["item_id"]
        for item in rfq.normalize_canonical_package(package)["items"]
    ]
    assert "item:synthetic-p1" in ids_without_relationship


def test_legacy_adapter_requires_exact_headers_and_maps_explicit_scope(tmp_path):
    path = tmp_path / "SYNTHETIC-legacy.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Steel Takeoff"
    sheet.append(
        [
            "Source_ID",
            "Item_ID",
            "Scope",
            "Description",
            "Material",
            "Grade",
            "Thickness",
            "Size",
            "Qty",
            "Currency",
            "Purchase Weight",
        ]
    )
    sheet.append(
        [
            "SYNTHETIC-SRC-1",
            "item:synthetic-legacy-1",
            "IN SCOPE",
            "Synthetic member",
            "carbon_steel",
            "A992",
            None,
            "W10X22",
            2,
            "USD",
            440,
        ]
    )
    sheet.append(
        [
            "SYNTHETIC-SRC-2",
            "item:synthetic-legacy-2",
            "BY OTHERS",
            "Synthetic excluded item",
            "carbon_steel",
            "A36",
            0.5,
            "PL 8x6",
            1,
            "USD",
            20,
        ]
    )
    sheet.append(
        [
            "SYNTHETIC-SRC-3",
            "item:synthetic-legacy-3",
            "IN SCOPE",
            "Synthetic zero quantity",
            "carbon_steel",
            "A572",
            0.375,
            "PL 6x4",
            0,
            "USD",
            0,
        ]
    )
    workbook.save(path)

    normalized = rfq.normalize_legacy_xlsx(path)
    assert [item["item_id"] for item in normalized["items"]] == [
        "item:synthetic-legacy-1"
    ]

    sheet.delete_cols(1)
    workbook.save(path)
    with pytest.raises(rfq.RfqInputError, match="exact headers"):
        rfq.normalize_legacy_xlsx(path)


def test_profile_resolution_precedence_and_term_hash_invalidation(
    tmp_path, monkeypatch
):
    explicit = tmp_path / "explicit.json"
    explicit.write_text((FIXTURES / "synthetic-profile.json").read_text())
    project = tmp_path / ".pi-steel"
    project.mkdir()
    (project / "company-profile.json").write_text(
        (FIXTURES / "synthetic-profile.json").read_text()
    )
    monkeypatch.setenv("PI_STEEL_CONFIG", str(explicit))
    profile, source = rfq.resolve_company_profile(tmp_path / "estimate.json")
    assert source == "environment"
    assert profile["company_name"] == "Example Fabricator"

    changed = deepcopy(profile)
    changed["terms_template"]["content"] += " changed"
    findings = rfq.validate_company_profile(changed, explicit)
    assert "terms_content_hash_mismatch" in {finding["code"] for finding in findings}


def test_cli_blocks_missing_profile_and_publishes_only_diagnostics(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("PI_STEEL_CONFIG", raising=False)
    environment = os.environ.copy()
    environment.pop("PI_STEEL_CONFIG", None)
    environment["XDG_CONFIG_HOME"] = str(tmp_path / "empty-config")
    output = tmp_path / "published"
    completed = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--input",
            FIXTURES / "estimate-package.json",
            "--out",
            output,
            "--issued-date",
            "2026-07-28",
            "--run-id",
            "SYNTHETIC-RFQ-BLOCKED",
            "--no-bake",
        ],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 3, completed.stdout + completed.stderr
    pointer = json.loads((output / "latest-run.json").read_text())
    run_path = output / pointer["run_directory"]
    assert (run_path / "qa-report.json").exists()
    assert not list(run_path.glob("*.xlsx"))
    assert json.loads((run_path / "run-manifest.json").read_text())[
        "run_outcome"
    ] == "blocked"


@pytest.mark.parametrize(
    ("nest_name", "expected_exit", "expected_outcome"),
    [
        (None, 0, "ready"),
        ("nest-handoff.json", 2, "review_required"),
    ],
)
def test_cli_ready_and_review_runs_publish_draft_workbooks(
    tmp_path, nest_name, expected_exit, expected_outcome
):
    environment = os.environ.copy()
    environment["PI_STEEL_CONFIG"] = str(FIXTURES / "synthetic-profile.json")
    output = tmp_path / f"published-{expected_outcome}"
    command = [
        sys.executable,
        SCRIPT,
        "--input",
        FIXTURES / "estimate-package.json",
        "--out",
        output,
        "--issued-date",
        "2026-07-28",
        "--run-id",
        f"SYNTHETIC-RFQ-{expected_outcome.upper()}",
        "--no-bake",
    ]
    if nest_name:
        command.extend(["--nest", FIXTURES / nest_name])
    completed = subprocess.run(
        command,
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == expected_exit, completed.stdout + completed.stderr
    pointer = json.loads((output / "latest-run.json").read_text())
    run_path = output / pointer["run_directory"]
    manifest = json.loads((run_path / "run-manifest.json").read_text())
    assert manifest["run_outcome"] == expected_outcome
    assert any(
        artifact["readiness"] == "draft"
        and artifact["path"].endswith(".xlsx")
        for artifact in manifest["artifacts"]
    )
    workbook = openpyxl.load_workbook(next(run_path.glob("*.xlsx")))
    assert workbook["RFQ Metadata"]["B2"].value == "DRAFT — NOT SENT OR AWARDED"
