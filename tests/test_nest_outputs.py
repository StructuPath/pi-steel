import importlib.util
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import ezdxf


ROOT = Path(__file__).resolve().parents[1]
NEST_SCRIPT = ROOT / "skills" / "steel-nest" / "scripts" / "nest.py"
SPEC = importlib.util.spec_from_file_location("pi_steel_nest_outputs", NEST_SCRIPT)
nest = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = nest
SPEC.loader.exec_module(nest)


def rectangular_job():
    return {
        "job_name": "SYNTHETIC-DXF-CHARACTERIZATION",
        "material": "carbon_steel",
        "grade": "A36",
        "unit_system": "imperial",
        "settings": {
            "kerf_in": 0.06,
            "part_gap_in": 0.25,
            "edge_margin_in": 0.5,
            "density_lb_in3": 0.2836,
            "thickness_in": 0.5,
        },
        "stock": [
            {
                "name": "Synthetic A36 Plate",
                "width": 20,
                "height": 20,
                "thickness": 0.5,
                "qty": 1,
            }
        ],
        "parts": [
            {
                "name": "Synthetic Base Plate",
                "width": 8,
                "height": 6,
                "qty": 1,
                "shape": "rect",
                "holes": [{"dia": 1, "x": 4, "y": 3}],
            }
        ],
    }


IRREGULAR_FIXTURE = (
    ROOT / "tests" / "fixtures" / "nest" / "irregular-reference-only.json"
)


def write_job(tmp_path, name, job):
    path = tmp_path / name
    path.write_text(json.dumps(job), encoding="utf-8")
    return path


def run_cli(tmp_path, job_path, output_root, run_id, *extra):
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    return subprocess.run(
        [
            sys.executable,
            NEST_SCRIPT,
            "--job",
            job_path,
            "--out",
            output_root,
            "--run-id",
            run_id,
            *extra,
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )


def latest_run(output_root):
    pointer = json.loads(
        (output_root / "latest-run.json").read_text(encoding="utf-8")
    )
    return output_root / pointer["run_directory"]


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_verified_rectangular_burn_preserves_units_origin_and_cut_entities_only(
    tmp_path,
):
    result = nest.run_job(rectangular_job())
    paths = nest.render_burn_dxfs(result, tmp_path)

    assert len(paths) == 1
    document = ezdxf.readfile(paths[0])
    assert document.units == ezdxf.units.IN

    entities = list(document.modelspace())
    assert {entity.dxf.layer for entity in entities} == {"PROFILE", "HOLES"}
    assert {
        entity.dxftype() for entity in entities if entity.dxf.layer == "PROFILE"
    } == {"LWPOLYLINE"}
    assert {
        entity.dxftype() for entity in entities if entity.dxf.layer == "HOLES"
    } <= {"CIRCLE", "LWPOLYLINE"}
    assert not any(entity.dxftype() == "TEXT" for entity in entities)
    profile = next(entity for entity in entities if entity.dxf.layer == "PROFILE")
    points = list(profile.get_points("xy"))
    assert min(point[0] for point in points) == 0.5
    assert min(point[1] for point in points) == 0.5
    assert profile.closed


def test_irregular_job_publishes_review_required_reference_outputs(tmp_path):
    output_root = tmp_path / "published"
    completed = run_cli(
        tmp_path,
        IRREGULAR_FIXTURE,
        output_root,
        "SYNTHETIC-IRREGULAR-RUN",
    )

    assert completed.returncode == 2, completed.stdout + completed.stderr
    run_path = latest_run(output_root)
    assert not list(run_path.glob("burn_plate_*.dxf"))
    assert (run_path / "reference_nest.dxf").exists()
    assert (run_path / "reference_plate_1.dxf").exists()

    reference = ezdxf.readfile(run_path / "reference_plate_1.dxf")
    reference_layers = {entity.dxf.layer for entity in reference.modelspace()}
    assert "BOUNDS" in reference_layers
    assert "PROFILE" not in reference_layers

    result = load_json(run_path / "result.json")
    qa = load_json(run_path / "qa-report.json")
    manifest = load_json(run_path / "run-manifest.json")
    assert result["geometry_readiness"] == "reference_only"
    assert qa["run_outcome"] == "review_required"
    assert manifest["run_outcome"] == "review_required"
    assert {artifact["readiness"] for artifact in manifest["artifacts"]} <= {
        "reference_only",
        "diagnostic",
    }


def test_geometry_verified_only_request_for_irregular_job_exits_unsuccessfully(
    tmp_path,
):
    output_root = tmp_path / "published"
    completed = run_cli(
        tmp_path,
        IRREGULAR_FIXTURE,
        output_root,
        "SYNTHETIC-GEOMETRY-ONLY-RUN",
        "--geometry-verified-only",
    )

    assert completed.returncode == 2, completed.stdout + completed.stderr
    run_path = latest_run(output_root)
    qa = load_json(run_path / "qa-report.json")
    assert any(
        finding["code"] == "GEOMETRY_VERIFIED_REQUIRED"
        for finding in qa["findings"]
    )
    assert not list(run_path.glob("burn_plate_*.dxf"))


def test_blocked_rerun_is_isolated_and_cannot_expose_stale_burn_output(tmp_path):
    output_root = tmp_path / "published"
    ready_job = write_job(tmp_path, "ready.json", rectangular_job())
    ready = run_cli(
        tmp_path,
        ready_job,
        output_root,
        "SYNTHETIC-READY-RUN",
    )
    assert ready.returncode == 0, ready.stdout + ready.stderr
    ready_path = latest_run(output_root)
    assert (ready_path / "burn_plate_1.dxf").exists()
    ready_manifest = load_json(ready_path / "run-manifest.json")
    assert ready_manifest["run_outcome"] == "ready"
    burn_artifact = next(
        artifact
        for artifact in ready_manifest["artifacts"]
        if artifact["path"] == "burn_plate_1.dxf"
    )
    assert burn_artifact["readiness"] == "geometry_verified"

    blocked_job = deepcopy(rectangular_job())
    blocked_job["parts"].append(
        {
            "name": "Synthetic Oversize Plate",
            "width": 30,
            "height": 30,
            "qty": 1,
            "shape": "rect",
        }
    )
    blocked_path_input = write_job(tmp_path, "blocked.json", blocked_job)
    blocked = run_cli(
        tmp_path,
        blocked_path_input,
        output_root,
        "SYNTHETIC-BLOCKED-RUN",
    )

    assert blocked.returncode == 3, blocked.stdout + blocked.stderr
    blocked_path = latest_run(output_root)
    assert blocked_path.name == "SYNTHETIC-BLOCKED-RUN"
    assert not list(blocked_path.glob("burn_plate_*.dxf"))
    assert (blocked_path / "reference_nest.dxf").exists()
    assert (ready_path / "burn_plate_1.dxf").exists()
    assert load_json(blocked_path / "run-manifest.json")["run_outcome"] == "blocked"
    assert load_json(blocked_path / "qa-report.json")["package_status"] == (
        "nested_partial"
    )


def test_invalid_hole_is_blocked_with_only_safe_reference_and_diagnostics(tmp_path):
    invalid_job = rectangular_job()
    invalid_job["parts"][0]["holes"] = [{"dia": 2, "x": 0.5, "y": 3}]
    job_path = write_job(tmp_path, "invalid-hole.json", invalid_job)
    output_root = tmp_path / "published"

    completed = run_cli(
        tmp_path,
        job_path,
        output_root,
        "SYNTHETIC-INVALID-HOLE-RUN",
    )

    assert completed.returncode == 3, completed.stdout + completed.stderr
    run_path = latest_run(output_root)
    assert not list(run_path.glob("burn_plate_*.dxf"))
    assert not (run_path / "reference_nest.dxf").exists()
    assert (run_path / "qa-report.json").exists()
    manifest = load_json(run_path / "run-manifest.json")
    assert manifest["run_outcome"] == "blocked"
    assert "geometry_verified" not in {
        artifact["readiness"] for artifact in manifest["artifacts"]
    }


def test_missing_render_dependency_publishes_diagnostic_run(tmp_path, monkeypatch):
    monkeypatch.setattr(
        nest, "missing_render_dependencies", lambda: ["synthetic-render-module"]
    )
    args = SimpleNamespace(
        out=tmp_path / "published",
        no_render=False,
        geometry_verified_only=False,
        run_id="SYNTHETIC-DEPENDENCY-RUN",
    )

    _, qa, _, run_path = nest.publish_nest_run(rectangular_job(), args)

    assert qa["run_outcome"] == "dependency_missing"
    assert nest.outcome_exit_code(qa["run_outcome"]) == 4
    assert not (run_path / "layout.pdf").exists()
    assert not list(run_path.glob("burn_plate_*.dxf"))
    assert load_json(run_path / "run-manifest.json")["run_outcome"] == (
        "dependency_missing"
    )


def test_cli_usage_error_uses_stage_contract_exit_one(tmp_path):
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, NEST_SCRIPT],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
