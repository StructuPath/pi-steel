import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-data-provenance.py"


def load_script():
    spec = importlib.util.spec_from_file_location("check_data_provenance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DataProvenanceTests(unittest.TestCase):
    def test_shape_data_matches_recorded_integrity_contract(self):
        report = load_script().audit()

        self.assertEqual(report["integrity"], "passed", report["errors"])
        self.assertEqual(report["shape_rows"], 477)
        self.assertEqual(report["release_readiness"], "blocked")

    def test_release_check_blocks_unverified_redistribution(self):
        result = subprocess.run(
            [sys.executable, SCRIPT, "--release"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('"redistribution_permission": "unverified"', result.stdout)


if __name__ == "__main__":
    unittest.main()
