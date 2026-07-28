import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "steel-rfq" / "scripts" / "recalc.py"
SPEC = importlib.util.spec_from_file_location("pi_steel_recalc_reliability", SCRIPT)
recalc = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = recalc
SPEC.loader.exec_module(recalc)


def test_recalculation_flag_failure_is_distinct_and_prevents_bake(monkeypatch):
    class BrokenWorkbook:
        calculation = SimpleNamespace()

        def save(self, _path):
            raise OSError("synthetic save failure")

    import openpyxl

    monkeypatch.setattr(openpyxl, "load_workbook", lambda _path: BrokenWorkbook())
    bake_calls = []
    monkeypatch.setattr(
        recalc, "libreoffice_bake", lambda path: bake_calls.append(path) or True
    )

    with pytest.raises(recalc.RecalculationError, match="synthetic save failure"):
        recalc.recalculate("synthetic.xlsx")
    assert bake_calls == []


def test_cli_reports_recalculation_failure_without_deferred_label(
    monkeypatch, capsys, tmp_path
):
    workbook = tmp_path / "synthetic.xlsx"
    workbook.write_bytes(b"synthetic")
    monkeypatch.setattr(
        recalc,
        "recalculate",
        lambda _path: (_ for _ in ()).throw(
            recalc.RecalculationError("synthetic flag failure")
        ),
    )
    monkeypatch.setattr(sys, "argv", ["recalc.py", str(workbook)])

    assert recalc.main() == 1
    captured = capsys.readouterr()
    assert "synthetic flag failure" in captured.err
    assert "deferred_recalculate_on_open" not in captured.out + captured.err
