import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CALCULATE_WEIGHT = (
    ROOT / "skills" / "steel-takeoff" / "scripts" / "calculate-weight.sh"
)
VALIDATE_BOM = (
    ROOT / "skills" / "steel-takeoff" / "scripts" / "validate-bom.py"
)
HEADER = (
    "Source_ID,Mark,Qty,Size,Grade,Length_ft,Unit_Wt_plf,"
    "Total_Wt_lbs,Connections,Notes,Source_Sheet,Source_Detail,Intent\n"
)


def run_validate(path: Path, *, json_output: bool = True):
    command = [sys.executable, VALIDATE_BOM, path]
    if json_output:
        command.append("--json")
    return subprocess.run(command, capture_output=True, text=True)


def write_bom(tmp_path: Path, row: str) -> Path:
    path = tmp_path / "synthetic-bom.csv"
    path.write_text(HEADER + row + "\n", encoding="utf-8")
    return path


def test_calculate_weight_reports_exact_synthetic_totals_without_pricing(
    tmp_path,
):
    bom = tmp_path / "synthetic-weight.csv"
    bom.write_text(
        "Source_ID,Mark,Qty,Size,Grade,Length_ft,Unit_Wt_plf\n"
        "SYNTHETIC-W1,SYNTHETIC-W1,2,W14X30,A992,10,30\n"
        "SYNTHETIC-H1,SYNTHETIC-H1,1,HSS4X4X1/4,,5'-6\",20\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", CALCULATE_WEIGHT, bom],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Member Weight:" in result.stdout
    assert "710 lb" in result.stdout
    assert "Connection Allow (12%):" in result.stdout
    assert "85 lb" in result.stdout
    assert "Misc Steel Allow (5%):" in result.stdout
    assert "36 lb" in result.stdout
    assert "GRAND TOTAL:" in result.stdout
    assert "831 lb" in result.stdout
    assert "UNSPECIFIED" in result.stdout
    assert "No price was calculated." in result.stdout
    assert "$" not in result.stdout
    assert "cost sensitivity" not in result.stdout.lower()
    assert "estimated cost" not in result.stdout.lower()


def test_validate_bom_missing_file_returns_text_error_and_exit_one(tmp_path):
    result = run_validate(tmp_path / "missing-synthetic.csv")

    assert result.returncode == 1
    assert result.stdout == ""
    assert "ERROR: File not found:" in result.stderr


def test_validate_bom_malformed_quantity_returns_parse_error_and_exit_one(
    tmp_path,
):
    path = write_bom(
        tmp_path,
        "SYNTHETIC-SRC-1,SYNTHETIC-M1,not-a-number,W14X30,A992,10,30,"
        "300,None,Synthetic,SYNTHETIC-SHEET,SYNTHETIC-DETAIL,fabricated_part",
    )

    result = run_validate(path)

    assert result.returncode == 1
    assert result.stdout == ""
    assert "ERROR: Could not parse BOM:" in result.stderr


@pytest.mark.parametrize(
    ("row", "expected_code", "expected_status", "expected_exit"),
    [
        (
            "SYNTHETIC-SRC-1,SYNTHETIC-M1,0,W14X30,A992,10,30,0,None,"
            "Synthetic,SYNTHETIC-SHEET,SYNTHETIC-DETAIL,fabricated_part",
            "invalid_quantity",
            "invalid",
            1,
        ),
        (
            "SYNTHETIC-SRC-1,SYNTHETIC-M1,1,W99X99,A992,10,99,990,None,"
            "Synthetic,SYNTHETIC-SHEET,SYNTHETIC-DETAIL,fabricated_part",
            "unverified_designation",
            "review_required",
            0,
        ),
        (
            "SYNTHETIC-SRC-1,SYNTHETIC-M1,1,W14X30,A992,10,31,310,None,"
            "Synthetic,SYNTHETIC-SHEET,SYNTHETIC-DETAIL,fabricated_part",
            "unit_weight_mismatch",
            "review_required",
            0,
        ),
        (
            "SYNTHETIC-SRC-1,SYNTHETIC-M1,1,W14X30,A500,10,30,300,None,"
            "Synthetic,SYNTHETIC-SHEET,SYNTHETIC-DETAIL,fabricated_part",
            "unusual_grade",
            "review_required",
            0,
        ),
        (
            "SYNTHETIC-SRC-1,SYNTHETIC-M1,1,W14X30,A992,81,30,2430,None,"
            "Synthetic,SYNTHETIC-SHEET,SYNTHETIC-DETAIL,fabricated_part",
            "unusual_member_length",
            "review_required",
            0,
        ),
    ],
)
def test_validate_bom_json_reports_branch_status_and_exit_semantics(
    tmp_path,
    row,
    expected_code,
    expected_status,
    expected_exit,
):
    result = run_validate(write_bom(tmp_path, row))

    assert result.returncode == expected_exit, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == expected_status
    assert expected_code in {
        finding["code"] for finding in report["findings"]
    }
    assert len(report["input_hash"]) == 64


def test_validate_bom_json_valid_case_is_machine_readable_and_exits_zero(
    tmp_path,
):
    path = write_bom(
        tmp_path,
        "SYNTHETIC-SRC-1,SYNTHETIC-M1,1,W14X30,A992,10,30,300,None,"
        "Synthetic,SYNTHETIC-SHEET,SYNTHETIC-DETAIL,fabricated_part",
    )

    result = run_validate(path)

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "validated"
    assert report["line_count"] == 1
    assert report["total_weight_lbs"] == 300
    assert report["findings"] == []
