"""Shared command-line behavior for shipped pi-steel stages."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .run_manifest import (
    ManifestError,
    RunPublisher,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)


class StageArgumentParser(argparse.ArgumentParser):
    """Map command usage errors to the shared stage-contract exit code."""

    def configure_failure_diagnostics(
        self,
        *,
        stage: str,
        entry_file: str,
        input_option: str,
        date_options: dict[str, str] | None = None,
    ) -> None:
        self._failure_context = {
            "stage": stage,
            "entry_file": entry_file,
            "input_option": input_option,
            "date_options": date_options or {},
        }

    def parse_args(self, args=None, namespace=None):
        self._active_argv = list(sys.argv[1:] if args is None else args)
        return super().parse_args(args, namespace)

    def _option_value(self, option: str) -> str | None:
        argv = getattr(self, "_active_argv", [])
        for index, argument in enumerate(argv):
            if argument == option and index + 1 < len(argv):
                return str(argv[index + 1])
            if str(argument).startswith(f"{option}="):
                return str(argument).split("=", 1)[1]
        action = next(
            (item for item in self._actions if option in item.option_strings),
            None,
        )
        if action is not None and action.default not in (None, argparse.SUPPRESS):
            return str(action.default)
        return None

    def error(self, message):
        diagnostic_path = None
        context = getattr(self, "_failure_context", None)
        if context is not None:
            destination = self._option_value("--out")
            if destination is not None:
                explicit_dates = {
                    field: value
                    for option, field in context["date_options"].items()
                    if (value := self._option_value(option)) is not None
                }
                diagnostic_path = publish_failure_diagnostic(
                    destination,
                    stage=context["stage"],
                    input_path=self._option_value(context["input_option"]),
                    error=ValueError(message),
                    tool_version=package_version(context["entry_file"]),
                    run_id=self._option_value("--run-id"),
                    explicit_dates=explicit_dates,
                    finding_code="cli_usage_error",
                )
        self.print_usage(sys.stderr)
        suffix = (
            f"; diagnostic published: {diagnostic_path}"
            if diagnostic_path is not None
            else ""
        )
        self.exit(1, f"{self.prog}: error: {message}{suffix}\n")


def package_version(entry_file: str) -> str:
    package_path = Path(entry_file).resolve().parents[3] / "package.json"
    try:
        return json.loads(package_path.read_text(encoding="utf-8"))["version"]
    except (OSError, KeyError, json.JSONDecodeError):
        return "unknown"


def _diagnostic_message(error: Exception) -> str:
    """Describe a failure without persisting input paths in published artifacts."""
    if isinstance(error, OSError):
        detail = error.strerror or "input/output error"
        return f"{error.__class__.__name__}: {detail}"
    return str(error) or error.__class__.__name__


def publish_failure_diagnostic(
    destination: str | Path,
    *,
    stage: str,
    input_path: str | Path | None,
    error: Exception,
    tool_version: str,
    run_id: str | None = None,
    explicit_dates: dict[str, str] | None = None,
    finding_code: str = "input_unreadable_or_invalid",
) -> Path | None:
    """Best-effort publication for failures that occur after CLI parsing.

    The original failure remains authoritative: publication errors are contained so
    callers can preserve the shared exit-code contract and report the first error.
    """
    path = Path(input_path) if input_path is not None else None
    try:
        input_hash = (
            sha256_file(path)
            if path is not None and path.is_file()
            else sha256_bytes(canonical_json_bytes({"input_state": "unavailable"}))
        )
        message = _diagnostic_message(error)
        finding: dict[str, Any] = {
            "code": finding_code,
            "severity": "error",
            "message": message,
            "exception_type": error.__class__.__name__,
        }
        qa_report = {
            "schema_version": "1.0.0",
            "stage": stage,
            "run_outcome": "usage_or_internal_error",
            "package_status": "draft",
            "findings": [finding],
            "warnings": [],
        }
        configuration_hash = sha256_bytes(
            canonical_json_bytes(
                {
                    "failure_contract": "1.0.0",
                    "stage": stage,
                    "explicit_dates": explicit_dates or {},
                }
            )
        )
        with RunPublisher(
            destination,
            stage=stage,
            run_outcome="usage_or_internal_error",
            package_status="draft",
            input_hash=input_hash,
            configuration_hash=configuration_hash,
            schema_versions={"run_manifest": "1.0.0"},
            tool_versions={"pi_steel": tool_version},
            explicit_dates=explicit_dates or {},
            warnings=[message],
            approximations=[],
            run_id=run_id,
        ) as publisher:
            publisher.write_qa_report(qa_report)
            return publisher.publish()
    except (ManifestError, OSError, TypeError, ValueError):
        return None
