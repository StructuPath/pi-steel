import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-data-provenance.py"


def load_script():
    spec = importlib.util.spec_from_file_location("check_data_provenance", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load provenance checker from {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DataProvenanceTests(unittest.TestCase):
    def test_shape_data_matches_recorded_integrity_contract(self):
        report = load_script().audit()

        self.assertEqual(report["integrity"], "passed", report["errors"])
        self.assertEqual(report["shape_rows"], 477)
        self.assertEqual(
            report["dataset_name"], "StructuPath Structural Shapes Database"
        )
        self.assertEqual(report["copyright_holder"], "StructuPath")
        self.assertEqual(report["license"], "MIT")
        self.assertEqual(report["redistribution_permission"], "authorized")
        self.assertEqual(report["release_readiness"], "ready")

    def test_release_check_accepts_authorized_redistribution(self):
        result = subprocess.run(
            [sys.executable, SCRIPT, "--release"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"redistribution_permission": "authorized"', result.stdout)
        self.assertIn('"release_readiness": "ready"', result.stdout)

    def test_ready_dataset_requires_authorized_redistribution(self):
        module = load_script()
        record = json.loads(module.PROVENANCE_RECORD_PATH.read_text(encoding="utf-8"))
        record["datasets"][0]["redistribution_permission"] = "unverified"

        with tempfile.TemporaryDirectory() as directory:
            record_path = Path(directory) / "DATA_PROVENANCE.json"
            record_path.write_text(json.dumps(record), encoding="utf-8")
            setattr(module, "PROVENANCE_RECORD_PATH", record_path)
            report = module.audit()

        self.assertEqual(report["integrity"], "failed")
        self.assertIn(
            "release-ready data must have authorized redistribution",
            report["errors"],
        )


if __name__ == "__main__":
    unittest.main()
