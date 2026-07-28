import importlib.util
import json
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "steel-estimate" / "scripts" / "build-estimate-package.py"
FIXTURES = ROOT / "tests" / "fixtures" / "pipeline"


pytestmark = pytest.mark.full_render


def require_full_environment():
    missing = [
        module
        for module in ("ezdxf", "matplotlib", "numpy")
        if importlib.util.find_spec(module) is None
    ]
    office = shutil.which("soffice") or shutil.which("libreoffice")
    pdf_text = shutil.which("pdftotext")
    unavailable = missing + ([] if office else ["LibreOffice"]) + (
        [] if pdf_text else ["pdftotext"]
    )
    if unavailable:
        message = "full render requires " + ", ".join(unavailable)
        if os.environ.get("PI_STEEL_REQUIRE_FULL_RENDER") == "1":
            pytest.fail(message)
        pytest.skip(message)
    return office


def run_rendered(tmp_path, package, run_id):
    input_path = tmp_path / f"{run_id}.json"
    input_path.write_text(json.dumps(package), encoding="utf-8")
    output = tmp_path / "published"
    environment = os.environ.copy()
    environment["PI_STEEL_CONFIG"] = str(FIXTURES / "synthetic-profile.json")
    completed = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--input",
            input_path,
            "--out",
            output,
            "--prepared-date",
            "2026-07-28",
            "--issued-date",
            "2026-07-29",
            "--project-location",
            "Example City, ST",
            "--run-id",
            run_id,
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    pointer = json.loads((output / "latest-run.json").read_text())
    return completed, output / pointer["run_directory"]


def test_ready_package_renders_reference_and_verified_outputs(tmp_path):
    office = require_full_environment()
    package = json.loads((FIXTURES / "synthetic-estimate.json").read_text())
    completed, run_path = run_rendered(
        tmp_path, package, "SYNTHETIC-FULL-RENDER-READY"
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert (run_path / "layout.pdf").read_bytes().startswith(b"%PDF")
    assert list(run_path.glob("plate_*.png"))
    assert list(run_path.glob("reference_plate_*.dxf"))
    assert list(run_path.glob("burn_plate_*.dxf"))
    qa = json.loads((run_path / "qa-report.json").read_text())
    assert qa["rfq"]["recalculation_status"] == "baked_via_libreoffice"

    workbook = next(run_path.glob("*.xlsx"))
    pdf_output = tmp_path / "workbook-pdf"
    pdf_output.mkdir()
    converted = subprocess.run(
        [
            office,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            pdf_output,
            workbook,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert converted.returncode == 0, converted.stdout + converted.stderr
    workbook_pdf = pdf_output / f"{workbook.stem}.pdf"
    assert workbook_pdf.read_bytes().startswith(b"%PDF")
    assert workbook_pdf.stat().st_size > 1_000
    text_output = tmp_path / "workbook.txt"
    extracted = subprocess.run(
        ["pdftotext", "-layout", workbook_pdf, text_output],
        capture_output=True,
        text=True,
    )
    assert extracted.returncode == 0, extracted.stdout + extracted.stderr
    rendered_text = text_output.read_text()
    for expected in (
        "DRAFT",
        "Synthetic Pipeline Project",
        "RFQ",
        "Response Requested By",
    ):
        assert expected in rendered_text


def test_irregular_render_never_publishes_burn_authority(tmp_path):
    require_full_environment()
    package = json.loads((FIXTURES / "synthetic-estimate.json").read_text())
    package = deepcopy(package)
    package["items"][2]["geometry"].update(shape="irregular", area=30)
    completed, run_path = run_rendered(
        tmp_path, package, "SYNTHETIC-FULL-RENDER-REFERENCE"
    )
    assert completed.returncode == 2, completed.stdout + completed.stderr
    assert list(run_path.glob("reference_plate_*.dxf"))
    assert not list(run_path.glob("burn_plate_*.dxf"))
    manifest = json.loads((run_path / "run-manifest.json").read_text())
    assert manifest["run_outcome"] == "review_required"
    assert not any(
        artifact["readiness"] == "geometry_verified"
        for artifact in manifest["artifacts"]
    )
