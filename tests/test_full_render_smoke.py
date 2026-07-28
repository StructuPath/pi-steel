import importlib.util
import json
import os
import shutil
import subprocess
import sys
from xml.etree import ElementTree
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
    commands = {
        "pdftotext": shutil.which("pdftotext"),
        "pdfinfo": shutil.which("pdfinfo"),
        "pdftoppm": shutil.which("pdftoppm"),
        "pdfimages": shutil.which("pdfimages"),
    }
    unavailable = (
        missing
        + ([] if office else ["LibreOffice"])
        + [name for name, path in commands.items() if path is None]
    )
    if unavailable:
        message = "full render requires " + ", ".join(unavailable)
        if os.environ.get("PI_STEEL_REQUIRE_FULL_RENDER") == "1":
            pytest.fail(message)
        pytest.skip(message)
    return {"office": office, **commands}


def run_rendered(tmp_path, package, run_id):
    import matplotlib.image
    import numpy

    input_path = tmp_path / f"{run_id}.json"
    input_path.write_text(json.dumps(package), encoding="utf-8")
    logo_path = tmp_path / "synthetic-logo.png"
    logo = numpy.ones((40, 120, 3), dtype=float)
    logo[4:36, 4:116] = (1.0, 0.0, 1.0)
    logo[12:28, 16:104] = (0.0, 1.0, 1.0)
    matplotlib.image.imsave(logo_path, logo)
    profile = json.loads((FIXTURES / "synthetic-profile.json").read_text())
    profile["logo"] = str(logo_path)
    profile_path = tmp_path / "synthetic-profile.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    output = tmp_path / "published"
    environment = os.environ.copy()
    environment["PI_STEEL_CONFIG"] = str(profile_path)
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
    tools = require_full_environment()
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
    assert qa["rfq"]["logo_status"] == "embedded"

    workbook = next(run_path.glob("*.xlsx"))
    pdf_output = tmp_path / "workbook-pdf"
    pdf_output.mkdir()
    converted = subprocess.run(
        [
            tools["office"],
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

    info = subprocess.run(
        [tools["pdfinfo"], workbook_pdf],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    page_count = next(
        int(line.split(":", 1)[1])
        for line in info.splitlines()
        if line.startswith("Pages:")
    )
    assert page_count == 1

    text_output = tmp_path / "workbook.txt"
    extracted = subprocess.run(
        [tools["pdftotext"], "-layout", workbook_pdf, text_output],
        capture_output=True,
        text=True,
    )
    assert extracted.returncode == 0, extracted.stdout + extracted.stderr
    rendered_text = text_output.read_text()
    for expected in (
        "DRAFT",
        "Synthetic Pipeline Project",
        "REQUEST FOR QUOTATION",
        "Response Requested By",
    ):
        assert expected in rendered_text

    bbox_output = tmp_path / "workbook-bbox.html"
    subprocess.run(
        [tools["pdftotext"], "-bbox-layout", workbook_pdf, bbox_output],
        capture_output=True,
        text=True,
        check=True,
    )
    root = ElementTree.parse(bbox_output).getroot()
    pages = [element for element in root.iter() if element.tag.endswith("page")]
    words = [element for element in root.iter() if element.tag.endswith("word")]
    assert len(pages) == 1
    page_width = float(pages[0].attrib["width"])
    page_height = float(pages[0].attrib["height"])
    assert words
    for word in words:
        assert 0 <= float(word.attrib["xMin"]) < float(word.attrib["xMax"]) <= page_width
        assert 0 <= float(word.attrib["yMin"]) < float(word.attrib["yMax"]) <= page_height

    word_positions = {
        (word.text or "").upper(): float(word.attrib["yMin"]) for word in words
    }
    assert word_positions["REQUEST"] < page_height * 0.2
    assert word_positions["RESPONSE"] < word_positions["TOTAL"]
    assert word_positions["TOTAL"] < word_positions["TERMS"]
    assert word_positions["TERMS"] < page_height * 0.95

    images = subprocess.run(
        [tools["pdfimages"], "-list", workbook_pdf],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    image_rows = [
        line for line in images.splitlines()
        if line.strip() and line.lstrip()[0].isdigit()
    ]
    assert image_rows, "the runtime synthetic logo was not embedded in the PDF"

    raster_base = tmp_path / "workbook-page"
    subprocess.run(
        [
            tools["pdftoppm"],
            "-f",
            "1",
            "-l",
            "1",
            "-singlefile",
            "-png",
            workbook_pdf,
            raster_base,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    import matplotlib.image
    import numpy

    raster = matplotlib.image.imread(raster_base.with_suffix(".png"))
    occupied = numpy.any(raster[..., :3] < 0.98, axis=2)
    rows, columns = numpy.where(occupied)
    assert rows.size and columns.size
    assert rows.min() > 1 and columns.min() > 1
    assert rows.max() < occupied.shape[0] - 2
    assert columns.max() < occupied.shape[1] - 2

    synthetic_logo = (
        (raster[..., 0] > 0.8)
        & (raster[..., 1] < 0.2)
        & (raster[..., 2] > 0.8)
    )
    logo_rows, logo_columns = numpy.where(synthetic_logo)
    assert logo_rows.size and logo_columns.size
    logo_bounds = (
        logo_columns.min() / raster.shape[1] * page_width,
        logo_rows.min() / raster.shape[0] * page_height,
        logo_columns.max() / raster.shape[1] * page_width,
        logo_rows.max() / raster.shape[0] * page_height,
    )
    assert logo_bounds[1] < page_height * 0.2
    for word in words:
        if (word.text or "").upper() not in {"RESPONSE", "TOTAL", "TERMS"}:
            continue
        word_bounds = tuple(
            float(word.attrib[field])
            for field in ("xMin", "yMin", "xMax", "yMax")
        )
        assert (
            logo_bounds[2] <= word_bounds[0]
            or word_bounds[2] <= logo_bounds[0]
            or logo_bounds[3] <= word_bounds[1]
            or word_bounds[3] <= logo_bounds[1]
        ), f"synthetic logo overlaps key text {word.text!r}"


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
