import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PublicDataPolicyTests(unittest.TestCase):
    def test_repository_passes_public_data_check(self):
        result = subprocess.run(
            [sys.executable, ROOT / "scripts" / "check-public-data.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
