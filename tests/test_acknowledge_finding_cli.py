import copy
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "skills" / "_shared"
sys.path.insert(0, str(SHARED))

from pi_steel.validation import validate_estimate_package


SCRIPT = (
    ROOT
    / "skills"
    / "steel-estimate"
    / "scripts"
    / "acknowledge-finding.py"
)
FIXTURE = ROOT / "tests" / "fixtures" / "pipeline" / "synthetic-estimate.json"


def package_with_warning():
    package = json.loads(FIXTURE.read_text(encoding="utf-8"))
    package["items"][0].pop("source_evidence")
    finding = next(
        finding
        for finding in validate_estimate_package(package).active_findings
        if finding["code"] == "missing_source_evidence"
    )
    return package, finding


def run_acknowledgement(
    input_path,
    output_path,
    finding_id,
    input_hash,
    *,
    disposition="accepted",
):
    return subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--input",
            input_path,
            "--output",
            output_path,
            "--finding-id",
            finding_id,
            "--input-hash",
            input_hash,
            "--actor",
            "Synthetic Reviewer",
            "--timestamp",
            "2026-07-28T12:00:00Z",
            "--disposition",
            disposition,
        ],
        capture_output=True,
        text=True,
    )


def test_acknowledgement_cli_records_explicit_decision_in_new_package(tmp_path):
    package, finding = package_with_warning()
    source = tmp_path / "synthetic-source.json"
    output = tmp_path / "synthetic-reviewed.json"
    source.write_text(json.dumps(package), encoding="utf-8")
    original = source.read_bytes()

    result = run_acknowledgement(
        source,
        output,
        finding["finding_id"],
        finding["relevant_hash"],
        disposition="accepted",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert source.read_bytes() == original
    response = json.loads(result.stdout)
    assert response == {
        "disposition": "accepted",
        "finding_id": finding["finding_id"],
        "input_hash": finding["relevant_hash"],
        "recorded": True,
    }
    reviewed = json.loads(output.read_text(encoding="utf-8"))
    assert reviewed["review"]["acknowledgements"] == [
        {
            "actor": "Synthetic Reviewer",
            "disposition": "accepted",
            "finding_id": finding["finding_id"],
            "input_hash": finding["relevant_hash"],
            "timestamp": "2026-07-28T12:00:00Z",
        }
    ]
    assert not any(
        active["finding_id"] == finding["finding_id"]
        for active in validate_estimate_package(reviewed).active_findings
    )


def test_rejected_decision_is_recorded_without_clearing_warning(tmp_path):
    package, finding = package_with_warning()
    source = tmp_path / "synthetic-source.json"
    output = tmp_path / "synthetic-reviewed.json"
    source.write_text(json.dumps(package), encoding="utf-8")

    result = run_acknowledgement(
        source,
        output,
        finding["finding_id"],
        finding["relevant_hash"],
        disposition="rejected",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    reviewed = json.loads(output.read_text(encoding="utf-8"))
    assert any(
        active["finding_id"] == finding["finding_id"]
        for active in validate_estimate_package(reviewed).active_findings
    )


def test_acknowledgement_cli_rejects_stale_finding_and_existing_output(
    tmp_path,
):
    package, finding = package_with_warning()
    stale = copy.deepcopy(package)
    stale["project"]["revision"]["revision_id"] = "SYNTHETIC-REV-CHANGED"
    source = tmp_path / "synthetic-source.json"
    source.write_text(json.dumps(stale), encoding="utf-8")
    output = tmp_path / "synthetic-reviewed.json"

    stale_result = run_acknowledgement(
        source, output, finding["finding_id"], finding["relevant_hash"]
    )

    assert stale_result.returncode == 1
    assert not output.exists()
    assert "--input-hash is stale" in stale_result.stderr

    package_source = tmp_path / "synthetic-current.json"
    package_source.write_text(json.dumps(package), encoding="utf-8")
    output.write_text("synthetic existing output", encoding="utf-8")
    existing_result = run_acknowledgement(
        package_source,
        output,
        finding["finding_id"],
        finding["relevant_hash"],
    )
    assert existing_result.returncode == 1
    assert output.read_text(encoding="utf-8") == "synthetic existing output"
    assert "output already exists" in existing_result.stderr
