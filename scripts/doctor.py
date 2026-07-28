#!/usr/bin/env python3
"""Diagnose the supported pi-steel Python runtime and optional capabilities."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


SHARED_ROOT = Path(__file__).resolve().parents[1] / "skills" / "_shared"
sys.path.insert(0, str(SHARED_ROOT))
from bootstrap import bootstrap_shared  # noqa: E402

bootstrap_shared(__file__)
from pi_steel import outcome_exit_code  # noqa: E402


REQUIRED_MODULES = {
    "jsonschema": "contract validation",
    "openpyxl": "RFQ workbook generation",
    "pandas": "spreadsheet adapters",
}
OPTIONAL_CAPABILITIES = {
    "nest_rendering": ("ezdxf", "matplotlib", "numpy"),
}


def _module_status(name, module_finder):
    available = module_finder(name) is not None
    item = {"name": name, "kind": "python_module", "available": available}
    if available:
        try:
            item["version"] = version(name)
        except PackageNotFoundError:
            item["version"] = "unknown"
    return item


def diagnose(
    *,
    version_info=None,
    module_finder=importlib.util.find_spec,
    command_finder=shutil.which,
):
    current = version_info or sys.version_info
    python_supported = (3, 11) <= tuple(current[:2]) < (3, 14)
    required = [
        {
            "name": "python",
            "kind": "runtime",
            "available": python_supported,
            "version": ".".join(str(value) for value in current[:3]),
            "supported": ">=3.11,<3.14",
        }
    ]
    for name, purpose in REQUIRED_MODULES.items():
        item = _module_status(name, module_finder)
        item["purpose"] = purpose
        required.append(item)

    jq_path = command_finder("jq")
    required.append(
        {
            "name": "jq",
            "kind": "command",
            "available": jq_path is not None,
            "path": jq_path,
            "purpose": "AISC shape lookup helpers",
        }
    )

    optional = {}
    for capability, modules in OPTIONAL_CAPABILITIES.items():
        checks = [_module_status(name, module_finder) for name in modules]
        optional[capability] = {
            "available": all(check["available"] for check in checks),
            "dependencies": checks,
        }

    office_path = command_finder("soffice") or command_finder("libreoffice")
    optional["formula_baking"] = {
        "available": office_path is not None,
        "dependencies": [
            {
                "name": "libreoffice",
                "kind": "command",
                "available": office_path is not None,
                "path": office_path,
            }
        ],
    }

    missing = [item["name"] for item in required if not item["available"]]
    outcome = "dependency_missing" if missing else "ready"
    return {
        "schema_version": "1.0.0",
        "run_outcome": outcome,
        "exit_code": outcome_exit_code(outcome),
        "required": required,
        "optional_capabilities": optional,
        "missing_required": missing,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit compact JSON instead of indented JSON",
    )
    args = parser.parse_args(argv)
    report = diagnose()
    if args.json:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
