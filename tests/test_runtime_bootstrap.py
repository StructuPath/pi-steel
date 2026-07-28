import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import openpyxl


ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "skills" / "_shared"
sys.path.insert(0, str(SHARED))

from bootstrap import bootstrap_shared, find_skills_root


def run_from(cwd, *command):
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    return subprocess.run(
        [str(value) for value in command],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
    )


def load_doctor():
    path = ROOT / "scripts" / "doctor.py"
    spec = importlib.util.spec_from_file_location("pi_steel_doctor", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_bootstrap_finds_skills_from_skill_and_root_entrypoints():
    nest_script = ROOT / "skills" / "steel-nest" / "scripts" / "nest.py"
    doctor_script = ROOT / "scripts" / "doctor.py"

    assert find_skills_root(nest_script) == ROOT / "skills"
    assert find_skills_root(doctor_script) == ROOT / "skills"
    assert bootstrap_shared(nest_script) == ROOT / "skills"

    import pi_steel

    assert pi_steel.outcome_exit_code("dependency_missing") == 4


def test_current_python_entrypoints_work_from_an_arbitrary_cwd(tmp_path):
    bom_path = tmp_path / "synthetic-bom.csv"
    bom_path.write_text(
        "Mark,Qty,Size,Grade,Length_ft,Unit_Wt_plf,Total_Wt_lbs,Connections,Notes\n"
        "SYNTHETIC-M1,1,W14X30,A992,10,30,300,None,synthetic fixture\n",
        encoding="utf-8",
    )
    workbook_path = tmp_path / "synthetic-workbook.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active["A1"] = "SYNTHETIC-RUNTIME"
    workbook.save(workbook_path)

    nest = run_from(
        tmp_path,
        sys.executable,
        ROOT / "skills" / "steel-nest" / "scripts" / "nest.py",
        "--help",
    )
    validate = run_from(
        tmp_path,
        sys.executable,
        ROOT / "skills" / "steel-takeoff" / "scripts" / "validate-bom.py",
        bom_path,
    )
    recalc = run_from(
        tmp_path,
        sys.executable,
        ROOT / "skills" / "steel-rfq" / "scripts" / "recalc.py",
        workbook_path,
    )
    doctor = run_from(
        tmp_path,
        sys.executable,
        ROOT / "scripts" / "doctor.py",
        "--json",
    )

    assert nest.returncode == 0, nest.stderr
    assert validate.returncode == 0, validate.stdout + validate.stderr
    assert recalc.returncode == 0, recalc.stdout + recalc.stderr
    assert doctor.returncode == 0, doctor.stdout + doctor.stderr
    assert json.loads(doctor.stdout)["run_outcome"] == "ready"


def test_doctor_returns_machine_readable_dependency_missing_for_unsupported_python():
    doctor = load_doctor()
    report = doctor.diagnose(
        version_info=(3, 10, 9),
        module_finder=lambda _name: object(),
        command_finder=lambda name: "synthetic-jq" if name == "jq" else None,
    )

    assert report["run_outcome"] == "dependency_missing"
    assert report["exit_code"] == 4
    assert "python" in report["missing_required"]


def test_doctor_reports_optional_capabilities_without_blocking_base_runtime():
    doctor = load_doctor()

    def module_finder(name):
        return object() if name in doctor.REQUIRED_MODULES else None

    report = doctor.diagnose(
        version_info=(3, 12, 1),
        module_finder=module_finder,
        command_finder=lambda name: "synthetic-jq" if name == "jq" else None,
    )

    assert report["run_outcome"] == "ready"
    assert report["optional_capabilities"]["nest_rendering"]["available"] is False
    assert report["optional_capabilities"]["formula_baking"]["available"] is False
