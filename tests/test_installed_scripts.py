import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_packed_npm_artifact_contains_runtime_and_runs_doctor(tmp_path):
    pack = subprocess.run(
        ["npm", "pack", "--json", "--pack-destination", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert pack.returncode == 0, pack.stdout + pack.stderr
    metadata = json.loads(pack.stdout)
    archive = tmp_path / metadata[0]["filename"]

    with tarfile.open(archive) as package:
        members = set(package.getnames())
        package.extractall(tmp_path / "unpacked", filter="data")

    expected = {
        "package/scripts/doctor.py",
        "package/scripts/check-public-data.py",
        "package/skills/_shared/bootstrap.py",
        "package/skills/_shared/pi_steel/__init__.py",
        "package/skills/_shared/pi_steel/run_manifest.py",
        "package/skills/_shared/schemas/run-manifest.schema.json",
        "package/skills/steel-estimate/SKILL.md",
        "package/skills/steel-estimate/scripts/build-estimate-package.py",
        "package/skills/steel-estimate/references/estimate-package-example.json",
        "package/skills/steel-estimate/references/output-contract.md",
        "package/skills/steel-rfq/scripts/generate-rfq.py",
        "package/skills/steel-rfq/references/rfq-input.md",
        "package/pyproject.toml",
        "package/requirements.txt",
        "package/requirements-tested.txt",
        "package/requirements-dev.txt",
        "package/requirements-render.txt",
        "package/DATA_PROVENANCE.md",
        "package/DATA_PROVENANCE.json",
    }
    assert expected <= members
    assert not any(name.startswith("package/tests/") for name in members)
    assert not any("__pycache__" in name or name.endswith(".pyc") for name in members)
    assert not any("company-profile.json" in name for name in members)

    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    installed_root = tmp_path / "unpacked" / "package"
    doctor = subprocess.run(
        [sys.executable, installed_root / "scripts" / "doctor.py", "--json"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert doctor.returncode == 0, doctor.stdout + doctor.stderr
    assert json.loads(doctor.stdout)["run_outcome"] == "ready"

    provenance = subprocess.run(
        [
            sys.executable,
            installed_root / "scripts" / "check-data-provenance.py",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert provenance.returncode == 0, provenance.stdout + provenance.stderr
    assert json.loads(provenance.stdout)["release_readiness"] == "blocked"

    privacy = subprocess.run(
        [
            sys.executable,
            installed_root / "scripts" / "check-public-data.py",
        ],
        cwd=installed_root,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert privacy.returncode == 0, privacy.stdout + privacy.stderr

    environment["PI_STEEL_CONFIG"] = str(
        ROOT / "tests" / "fixtures" / "pipeline" / "synthetic-profile.json"
    )
    pipeline_output = tmp_path / "installed-output"
    pipeline = subprocess.run(
        [
            sys.executable,
            installed_root
            / "skills"
            / "steel-estimate"
            / "scripts"
            / "build-estimate-package.py",
            "--input",
            ROOT / "tests" / "fixtures" / "pipeline" / "synthetic-estimate.json",
            "--out",
            pipeline_output,
            "--prepared-date",
            "2026-07-28",
            "--issued-date",
            "2026-07-29",
            "--project-location",
            "Example City, ST",
            "--no-render",
            "--no-bake",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert pipeline.returncode == 0, pipeline.stdout + pipeline.stderr
    pointer = json.loads((pipeline_output / "latest-run.json").read_text())
    run_path = pipeline_output / pointer["run_directory"]
    manifest = json.loads((run_path / "run-manifest.json").read_text())
    assert manifest["run_outcome"] == "ready"
    assert list(run_path.glob("*.xlsx"))
