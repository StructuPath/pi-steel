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
        "package/skills/_shared/bootstrap.py",
        "package/skills/_shared/pi_steel/__init__.py",
        "package/skills/_shared/pi_steel/run_manifest.py",
        "package/skills/_shared/schemas/run-manifest.schema.json",
        "package/pyproject.toml",
        "package/requirements.txt",
        "package/requirements-tested.txt",
        "package/requirements-dev.txt",
        "package/DATA_PROVENANCE.md",
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
