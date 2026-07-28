import json
import os
import subprocess
import sys
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
NEST_SCRIPT = ROOT / "skills" / "steel-nest" / "scripts" / "nest.py"
NEST_SCHEMA = ROOT / "skills" / "_shared" / "schemas" / "nest-result.schema.json"


def run_cli(tmp_path, job, run_id):
    job_path = tmp_path / f"{run_id}.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    output = tmp_path / "published"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [
            sys.executable,
            NEST_SCRIPT,
            "--job",
            job_path,
            "--out",
            output,
            "--run-id",
            run_id,
            "--no-render",
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
        "job_name": "SYNTHETIC-CLI-CONTRACT",
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
                "stock_id": "SYNTHETIC-STOCK-CLI",
                "name": "Synthetic Plate",
                "width": 20,
                "height": 10,
                "thickness": 0.5,
                "qty": 1,
            }
        ],
        "parts": [
            {
                "source_id": "SYNTHETIC-SRC-CLI",
                "name": "SYNTHETIC-CLI-PART",
                "width": 6,
                "height": 4,
                "qty": 1,
                "shape": "rect",
            }
        ],
    }


def test_ready_cli_publishes_versioned_result_handoff_and_manifest(tmp_path):
    completed, run_path = run_cli(
        tmp_path, valid_job(), "SYNTHETIC-CLI-READY"
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads((run_path / "result.json").read_text())
    schema = json.loads(NEST_SCHEMA.read_text())
    jsonschema.Draft202012Validator(schema).validate(result)
    assert result["algorithm_version"] == nest_algorithm_version()
    assert len(result["normalized_input_hash"]) == 64
    handoff = json.loads((run_path / "rfq_nesting.json").read_text())
    assert handoff["schema_version"] == "1.0.0"
    assert handoff["rows"][0]["grade"] == "A36"
    manifest = json.loads((run_path / "run-manifest.json").read_text())
    assert manifest["schema_versions"]["nest_result"] == "1.0.0"


def nest_algorithm_version():
    text = NEST_SCRIPT.read_text()
    marker = 'NEST_ALGORITHM_VERSION = "'
    return text.split(marker, 1)[1].split('"', 1)[0]


def test_review_required_and_blocked_outcomes_obey_exit_contract(tmp_path):
    review = valid_job()
    review["parts"][0].update(shape="irregular", area=12)
    review_completed, review_path = run_cli(
        tmp_path, review, "SYNTHETIC-CLI-REVIEW"
    )
    assert review_completed.returncode == 2
    assert json.loads((review_path / "run-manifest.json").read_text())[
        "run_outcome"
    ] == "review_required"

    blocked = valid_job()
    blocked["parts"][0]["width"] = -1
    blocked_completed, blocked_path = run_cli(
        tmp_path, blocked, "SYNTHETIC-CLI-BLOCKED"
    )
    assert blocked_completed.returncode == 3
    assert json.loads((blocked_path / "run-manifest.json").read_text())[
        "run_outcome"
    ] == "blocked"
    assert not (blocked_path / "rfq_nesting.json").exists()
