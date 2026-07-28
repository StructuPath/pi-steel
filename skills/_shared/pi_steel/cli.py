"""Shared command-line behavior for shipped pi-steel stages."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


class StageArgumentParser(argparse.ArgumentParser):
    """Map command usage errors to the shared stage-contract exit code."""

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def package_version(entry_file: str) -> str:
    package_path = Path(entry_file).resolve().parents[3] / "package.json"
    try:
        return json.loads(package_path.read_text(encoding="utf-8"))["version"]
    except (OSError, KeyError, json.JSONDecodeError):
        return "unknown"
