import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINTS = {
    "steel-estimate": (
        ROOT
        / "skills"
        / "steel-estimate"
        / "scripts"
        / "build-estimate-package.py",
        [
            "--input",
            "{input}",
            "--prepared-date",
            "2026-07-28",
            "--issued-date",
            "2026-07-29",
        ],
    ),
    "steel-nest": (
        ROOT / "skills" / "steel-nest" / "scripts" / "nest.py",
        ["--job", "{input}", "--no-render"],
    ),
    "steel-rfq": (
        ROOT / "skills" / "steel-rfq" / "scripts" / "generate-rfq.py",
        ["--input", "{input}", "--issued-date", "2026-07-29", "--no-bake"],
    ),
}


@pytest.mark.parametrize("stage", ENTRYPOINTS)
@pytest.mark.parametrize(
    "input_state", ["unavailable_file", "malformed", "missing_argument"]
)
def test_post_parse_input_failures_publish_machine_readable_run(
    tmp_path, stage, input_state
):
    script, stage_args = ENTRYPOINTS[stage]
    input_path = tmp_path / f"{input_state}.json"
    if input_state == "malformed":
        input_path.write_text('{"not": "complete"', encoding="utf-8")
    rendered_stage_args = [
        str(input_path) if argument == "{input}" else argument
        for argument in stage_args
    ]
    if input_state == "missing_argument":
        input_index = rendered_stage_args.index(str(input_path))
        del rendered_stage_args[input_index - 1 : input_index + 1]
    output = tmp_path / f"{stage}-{input_state}-published"
    run_id = f"SYNTHETIC-{stage.upper()}-{input_state.upper()}"
    command = [
        sys.executable,
        script,
        *rendered_stage_args,
        "--out",
        output,
        "--run-id",
        run_id,
    ]
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["XDG_CONFIG_HOME"] = str(tmp_path / "empty-config")

    completed = subprocess.run(
        command,
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    pointer = json.loads((output / "latest-run.json").read_text(encoding="utf-8"))
    assert pointer["run_id"] == run_id
    run_path = output / pointer["run_directory"]
    manifest = json.loads(
        (run_path / "run-manifest.json").read_text(encoding="utf-8")
    )
    qa_report = json.loads(
        (run_path / "qa-report.json").read_text(encoding="utf-8")
    )
    assert manifest["stage"] == stage
    assert manifest["run_outcome"] == "usage_or_internal_error"
    assert manifest["package_status"] == "draft"
    assert qa_report["run_outcome"] == "usage_or_internal_error"
    expected_code = (
        "cli_usage_error"
        if input_state == "missing_argument"
        else "input_unreadable_or_invalid"
    )
    assert qa_report["findings"][0]["code"] == expected_code
    assert str(input_path) not in json.dumps(qa_report)
    assert "diagnostic published:" in completed.stderr
