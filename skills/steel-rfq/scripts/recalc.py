#!/usr/bin/env python3
"""
Recalculate an .xlsx so formula results are correct/current.

openpyxl writes formulas but never computes them, so a freshly built
workbook has stale or empty cached values. This does two things:

  1. Flags the workbook to fully recalculate when opened (Excel / LibreOffice
     honor this), so values are always correct on open.
  2. If LibreOffice is installed, does a headless round-trip so the computed
     values are baked into the file immediately (needed when the file is
     read programmatically or previewed without opening in Excel).

Usage:  python3 recalc.py <workbook.xlsx>
Exit code is 0 on success; the file is edited in place.
"""
import os
import shutil
import subprocess
import sys
import tempfile


class RecalculationError(RuntimeError):
    """Raised when recalculate-on-open cannot be recorded safely."""


def flag_recalc_on_load(path):
    import openpyxl

    try:
        wb = openpyxl.load_workbook(path)
        wb.calculation.fullCalcOnLoad = True
        wb.calculation.forceFullCalc = True
        wb.calculation.calcMode = "auto"
        wb.save(path)
    except Exception as exc:
        raise RecalculationError(
            f"could not record recalculate-on-open state for {path}: {exc}"
        ) from exc


def libreoffice_bake(path):
    """Round-trip through LibreOffice headless to write computed values in place."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return False
    with tempfile.TemporaryDirectory() as td:
        try:
            subprocess.run(
                [soffice, "--headless", "--calc", "--convert-to", "xlsx",
                 "--outdir", td, path],
                capture_output=True, timeout=120, check=True,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False
        produced = os.path.join(td, os.path.splitext(os.path.basename(path))[0] + ".xlsx")
        if os.path.exists(produced):
            shutil.copyfile(produced, path)
            return True
    return False


def recalculate(path, *, bake=True):
    """Set recalc-on-open and return an honest cache status."""
    flag_recalc_on_load(path)
    if bake and libreoffice_bake(path):
        return "baked_via_libreoffice"
    return "deferred_recalculate_on_open"


def main():
    if len(sys.argv) < 2:
        print("usage: python3 recalc.py <workbook.xlsx>", file=sys.stderr)
        return 1
    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"file not found: {path}", file=sys.stderr)
        return 1
    # Set recalc-on-open FIRST so LibreOffice honors it, then bake. Do NOT
    # reload with openpyxl afterward — that would strip the cached values
    # LibreOffice just computed.
    try:
        status = recalculate(path)
    except RecalculationError as exc:
        print(f"recalc: failed — {exc}", file=sys.stderr)
        return 1
    if status == "baked_via_libreoffice":
        print(f"recalc: values computed and baked via LibreOffice — {path}")
    else:
        print(f"recalc: recalc-on-open set (open in Excel to compute values) — {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
