import ast
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-public-data.py"


def load_scanner():
    spec = importlib.util.spec_from_file_location("check_public_data", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def out_defaults(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defaults = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        if node.args[0].value != "--out":
            continue
        for keyword in node.keywords:
            if keyword.arg == "default" and isinstance(keyword.value, ast.Constant):
                defaults.append(keyword.value.value)
    return defaults


class PublicDataPolicyTests(unittest.TestCase):
    def test_repository_passes_public_data_check(self):
        result = subprocess.run(
            [sys.executable, ROOT / "scripts" / "check-public-data.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_scanner_fails_closed_for_sensitive_and_unknown_files(self):
        scanner = load_scanner()
        with self.subTest("environment filename"):
            root = self._fixture_root()
            path = root / ("." + "env" + ".local")
            path.write_text("placeholder", encoding="utf-8")
            findings = scanner.scan_paths([path], root=root, patterns={})
            self.assertTrue(any("environment file" in item for item in findings))

        with self.subTest("private key extension"):
            root = self._fixture_root()
            path = root / ("deploy." + "p" + "em")
            path.write_text("placeholder", encoding="utf-8")
            findings = scanner.scan_paths([path], root=root, patterns={})
            self.assertTrue(any("key or certificate" in item for item in findings))

        with self.subTest("unknown binary"):
            root = self._fixture_root()
            path = root / "fixture.bin"
            path.write_bytes(bytes((0, 159, 255, 0)))
            findings = scanner.scan_paths([path], root=root, patterns={})
            self.assertTrue(any("unknown binary" in item for item in findings))

    def test_scanner_checks_unlisted_text_and_unquoted_credentials(self):
        scanner = load_scanner()
        root = self._fixture_root()
        source = root / "fixture.ts"
        credential = "API_" + "KEY" + "=" + "live-value"
        source.write_text(credential, encoding="utf-8")

        findings = scanner.scan_paths([source], root=root)

        self.assertTrue(any("credential assignment" in item for item in findings))

    def test_scanner_detects_high_confidence_secret_formats_without_echoing_value(self):
        scanner = load_scanner()
        root = self._fixture_root()
        source = root / "fixture.txt"
        generated_secret = "gh" + "p_" + ("a" * 36)
        source.write_text(generated_secret, encoding="utf-8")

        findings = scanner.scan_paths([source], root=root)

        self.assertTrue(any("GitHub access token" in item for item in findings))
        self.assertFalse(any(generated_secret in item for item in findings))

    def test_scanner_checks_staged_blob_not_only_worktree_copy(self):
        scanner = load_scanner()
        root = self._git_fixture_root()
        source = root / "settings.txt"
        staged_value = "to" + "ken=staged-value"
        source.write_text(staged_value, encoding="utf-8")
        subprocess.run(["git", "add", "settings.txt"], cwd=root, check=True)
        source.write_text("safe placeholder", encoding="utf-8")

        findings = scanner.staged_findings(root)

        self.assertTrue(
            any(
                item.startswith("staged settings.txt:")
                and item.endswith("credential assignment")
                for item in findings
            )
        )
        self.assertFalse(any(staged_value in item for item in findings))

    def test_history_scan_reports_commit_path_and_category_without_value(self):
        scanner = load_scanner()
        root = self._git_fixture_root()
        source = root / "retired.txt"
        retired_value = "pass" + "word=retired-value"
        source.write_text(retired_value, encoding="utf-8")
        subprocess.run(["git", "add", "retired.txt"], cwd=root, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Synthetic Test",
                "-c",
                "user.email=" + "synthetic" + "@" + "example.invalid",
                "commit",
                "-m",
                "synthetic history fixture",
            ],
            cwd=root,
            check=True,
            capture_output=True,
        )
        source.write_text("safe placeholder", encoding="utf-8")
        subprocess.run(["git", "add", "retired.txt"], cwd=root, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Synthetic Test",
                "-c",
                "user.email=" + "synthetic" + "@" + "example.invalid",
                "commit",
                "-m",
                "remove synthetic credential",
            ],
            cwd=root,
            check=True,
            capture_output=True,
        )

        findings = scanner.revision_findings(["--all"], root)

        self.assertTrue(
            any(
                item.startswith("commit ")
                and " retired.txt:" in item
                and item.endswith("credential assignment")
                for item in findings
            )
        )
        self.assertFalse(any(retired_value in item for item in findings))

    def test_history_scan_reports_non_noreply_author_without_address(self):
        scanner = load_scanner()
        root = self._git_fixture_root()
        (root / "safe.txt").write_text("safe placeholder", encoding="utf-8")
        subprocess.run(["git", "add", "safe.txt"], cwd=root, check=True)
        address = "synthetic" + "@" + "example.invalid"
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Synthetic Test",
                "-c",
                "user.email=" + address,
                "commit",
                "-m",
                "synthetic metadata fixture",
            ],
            cwd=root,
            check=True,
            capture_output=True,
        )

        findings = scanner.revision_metadata_findings(["--all"], root)

        self.assertTrue(any("non-noreply email address" in item for item in findings))
        self.assertFalse(any(address in item for item in findings))

    def test_artifact_cli_defaults_are_git_ignored(self):
        scripts = [
            ROOT / "skills" / "steel-estimate" / "scripts" / "build-estimate-package.py",
            ROOT / "skills" / "steel-nest" / "scripts" / "nest.py",
            ROOT / "skills" / "steel-rfq" / "scripts" / "generate-rfq.py",
        ]
        self.assertEqual([out_defaults(path) for path in scripts], [["outputs"]] * 3)
        for directory in ("outputs", "out"):
            ignored = subprocess.run(
                ["git", "check-ignore", "-q", f"{directory}/synthetic-probe"],
                cwd=ROOT,
            )
            self.assertEqual(ignored.returncode, 0, directory)

    def _fixture_root(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def _git_fixture_root(self):
        root = self._fixture_root()
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        return root


if __name__ == "__main__":
    unittest.main()
