import json
import os
import subprocess
import sys
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
CUTLIST_SCRIPT = ROOT / "skills" / "steel-cutlist" / "scripts" / "cutlist.py"
CUTLIST_SCHEMA = ROOT / "skills" / "_shared" / "schemas" / "cutlist-result.schema.json"


def run_cli(tmp_path, job, run_id, extra_args=()):
    job_path = tmp_path / f"{run_id}.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    output = tmp_path / "published"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [
            sys.executable,
            CUTLIST_SCRIPT,
            "--job",
            job_path,
            "--out",
            output,
            "--run-id",
            run_id,
            "--no-render",
            *extra_args,
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    pointer = json.loads((output / "latest-run.json").read_text())
    run_path = output / pointer["run_directory"]
    return completed, run_path


def valid_job():
    return {
        "job_name": "SYNTHETIC-CUTLIST-CLI",
        "project_id": "SYNTHETIC-PRJ",
        "revision_id": "SYNTHETIC-REV",
        "unit_system": "imperial",
        "settings": {"kerf_in": 0.125, "end_trim_in": 0.25, "min_drop_in": 24},
        "members": [
            {
                "source_id": "SYNTHETIC-CLI-M1",
                "name": "SYNTHETIC-CLI-B1",
                "designation": "W12X26",
                "grade": "A992",
                "length_in": 200,
                "qty": 2,
            }
        ],
        "stock": [
            {
                "stock_id": "SYNTHETIC-CLI-STK",
                "designation": "W12X26",
                "grade": "A992",
                "length_ft": 40,
                "qty": 1,
                "cost_per_ft": 30.0,
            }
        ],
    }


def test_ready_run_publishes_verified_cutting_list_and_handoff(tmp_path):
    completed, run_path = run_cli(tmp_path, valid_job(), "synthetic-cutlist-ready")
    assert completed.returncode == 0, completed.stderr
    manifest = json.loads((run_path / "run-manifest.json").read_text())
    assert manifest["run_outcome"] == "ready"
    assert manifest["package_status"] == "cutlist_verified"
    artifacts = {entry["path"]: entry for entry in manifest["artifacts"]}
    assert artifacts["cutting_list.csv"]["readiness"] == "geometry_verified"
    assert "rfq_linear.json" in artifacts

    result = json.loads((run_path / "result.json").read_text())
    schema = json.loads(CUTLIST_SCHEMA.read_text())
    jsonschema.validate(result, schema)
    assert result["verification"]["status"] == "verified"
    assert result["bars_used"] == 1
    assert result["total_material_cost"] == 1200.0

    cutting_list = (run_path / "cutting_list.csv").read_text().splitlines()
    assert cutting_list[0].startswith("Bar,Stock,Designation")
    assert len(cutting_list) == 3

    handoff = json.loads((run_path / "rfq_linear.json").read_text())
    assert handoff["schema_version"] == "1.0.0"
    assert handoff["rows"][0]["bars_needed"] == 1


def test_blocked_run_suppresses_cutting_list_and_exits_3(tmp_path):
    job = valid_job()
    job["members"][0]["length_in"] = 500
    completed, run_path = run_cli(tmp_path, job, "synthetic-cutlist-blocked")
    assert completed.returncode == 3
    manifest = json.loads((run_path / "run-manifest.json").read_text())
    assert manifest["run_outcome"] == "blocked"
    assert manifest["package_status"] == "cutlist_partial"
    assert not (run_path / "cutting_list.csv").exists()
    assert not (run_path / "rfq_linear.json").exists()

    qa_report = json.loads((run_path / "qa-report.json").read_text())
    assert any(
        finding["code"] == "UNPLACED_MEMBERS" for finding in qa_report["findings"]
    )
    result = json.loads((run_path / "result.json").read_text())
    schema = json.loads(CUTLIST_SCHEMA.read_text())
    jsonschema.validate(result, schema)
    assert result["unplaced"][0]["reason"] == "no_compatible_stock_fit"


def test_unreadable_job_publishes_failure_diagnostic_and_exits_1(tmp_path):
    output = tmp_path / "published"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [
            sys.executable,
            CUTLIST_SCRIPT,
            "--job",
            tmp_path / "missing.json",
            "--out",
            output,
            "--run-id",
            "synthetic-cutlist-missing",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    pointer = json.loads((output / "latest-run.json").read_text())
    run_path = output / pointer["run_directory"]
    qa_report = json.loads((run_path / "qa-report.json").read_text())
    assert qa_report["run_outcome"] == "usage_or_internal_error"


def test_usage_error_exits_1_and_publishes_diagnostic(tmp_path):
    output = tmp_path / "published"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [
            sys.executable,
            CUTLIST_SCRIPT,
            "--out",
            output,
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    assert (output / "latest-run.json").exists()


def test_example_job_reference_runs_ready(tmp_path):
    example = json.loads(
        (
            ROOT
            / "skills"
            / "steel-cutlist"
            / "references"
            / "example_job.json"
        ).read_text()
    )
    completed, run_path = run_cli(tmp_path, example, "synthetic-cutlist-example")
    assert completed.returncode == 0, completed.stderr
    result = json.loads((run_path / "result.json").read_text())
    assert result["outcome"] == "ready"
    assert result["purchase_summary"]
