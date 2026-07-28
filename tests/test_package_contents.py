import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_npm_publish_lifecycle_cannot_bypass_release_gate():
    package = json.loads((ROOT / "package.json").read_text())

    assert package["scripts"]["prepublishOnly"] == "npm run release:check"
    assert "check-data-provenance.py --release" in package["scripts"]["release:check"]


def test_npm_dry_run_contains_runtime_contract_and_excludes_private_artifacts():
    result = subprocess.run(
        ["npm", "pack", "--dry-run", "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    files = {entry["path"] for entry in json.loads(result.stdout)[0]["files"]}

    required = {
        "DATA_PROVENANCE.md",
        "DATA_PROVENANCE.json",
        "PUBLIC_DATA_POLICY.md",
        "scripts/check-data-provenance.py",
        "scripts/doctor.py",
        "skills/_shared/schemas/estimate-package.schema.json",
        "skills/_shared/schemas/nest-result.schema.json",
        "skills/_shared/schemas/run-manifest.schema.json",
        "skills/steel-estimate/SKILL.md",
        "skills/steel-estimate/scripts/acknowledge-finding.py",
        "skills/steel-estimate/scripts/build-estimate-package.py",
        "skills/steel-nest/scripts/nest.py",
        "skills/steel-rfq/scripts/generate-rfq.py",
        "skills/steel-takeoff/assets/aisc-shapes-database.json",
    }
    assert required <= files

    forbidden_parts = {
        ".pi-steel",
        "__pycache__",
        "customer-data",
        "local-data",
        "outputs",
        "private",
        "tests",
        "vendor-data",
    }
    assert not any(
        forbidden_parts.intersection(Path(name).parts) for name in files
    )
    assert not any(
        name.endswith((".pyc", ".xlsx", ".xls", ".pdf", ".dxf", ".png"))
        for name in files
    )
    assert not any(Path(name).name == "company-profile.json" for name in files)
