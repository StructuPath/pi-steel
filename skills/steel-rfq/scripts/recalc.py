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


def flag_recalc_on_load(path):
    import openpyxl
    wb = openpyxl.load_workbook(path)
    try:
        wb.calculation.fullCalcOnLoad = True
    except Exception:
        pass  # older openpyxl — the LibreOffice bake below still fixes values
    wb.save(path)


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


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python3 recalc.py <workbook.xlsx>")
    path = sys.argv[1]
    if not os.path.exists(path):
        sys.exit(f"file not found: {path}")
    # Set recalc-on-open FIRST so LibreOffice honors it, then bake. Do NOT
    # reload with openpyxl afterward — that would strip the cached values
    # LibreOffice just computed.
    flag_recalc_on_load(path)
    baked = libreoffice_bake(path)
    if baked:
        print(f"recalc: values computed and baked via LibreOffice — {path}")
    else:
        print(f"recalc: recalc-on-open set (open in Excel to compute values) — {path}")


if __name__ == "__main__":
    main()
