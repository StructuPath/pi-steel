#!/usr/bin/env python3
"""Record one explicit human review decision in a canonical estimate package."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


SHARED_ROOT = Path(__file__).resolve().parents[2] / "_shared"
if str(SHARED_ROOT) not in sys.path:
    sys.path.insert(0, str(SHARED_ROOT))
from bootstrap import bootstrap_shared  # noqa: E402

bootstrap_shared(__file__)
from pi_steel import canonical_json_bytes  # noqa: E402
from pi_steel.validation import (  # noqa: E402
    acknowledge_finding,
    validate_estimate_package,
)


class AcknowledgementInputError(ValueError):
    """Raised when an explicit acknowledgement cannot be recorded safely."""


def _valid_timestamp(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return "T" in value and parsed.tzinfo is not None


def _findings_for_decision(
    package: dict[str, Any], current_hash: str
) -> list[dict[str, Any]]:
    generated = validate_estimate_package(package).findings
    supplied = package.get("review", {}).get("findings", [])
    combined: dict[tuple[str, str], dict[str, Any]] = {}
    for finding in [*generated, *supplied]:
        finding_id = finding.get("finding_id")
        relevant_hash = finding.get("relevant_hash")
        if isinstance(finding_id, str) and isinstance(relevant_hash, str):
            combined[(finding_id, relevant_hash)] = finding
    return [
        finding
        for finding in combined.values()
        if finding.get("relevant_hash") == current_hash
    ]


def record_acknowledgement(args: argparse.Namespace) -> dict[str, Any]:
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    if input_path == output_path:
        raise AcknowledgementInputError(
            "--output must be a new file; the source package is never overwritten"
        )
    if output_path.exists():
        raise AcknowledgementInputError(
            f"output already exists: {output_path}"
        )
    if not args.actor.strip():
        raise AcknowledgementInputError("--actor must name the human reviewer")
    if not _valid_timestamp(args.timestamp):
        raise AcknowledgementInputError(
            "--timestamp must be an explicit ISO-8601 date-time"
        )

    try:
        package = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcknowledgementInputError(
            f"estimate package could not be read: {exc}"
        ) from exc
    if not isinstance(package, dict):
        raise AcknowledgementInputError("estimate package must be a JSON object")

    validation = validate_estimate_package(package)
    if args.input_hash != validation.input_hash:
        raise AcknowledgementInputError(
            "--input-hash is stale for the current estimate input"
        )
    matches = [
        finding
        for finding in _findings_for_decision(package, validation.input_hash)
        if finding["finding_id"] == args.finding_id
    ]
    if not matches:
        stale = [
            finding
            for finding in package.get("review", {}).get("findings", [])
            if finding.get("finding_id") == args.finding_id
        ]
        if stale:
            raise AcknowledgementInputError(
                "finding exists but is stale for the current estimate input hash"
            )
        raise AcknowledgementInputError(
            "finding ID is not active for the current estimate input"
        )
    if len(matches) != 1:
        raise AcknowledgementInputError(
            "finding ID is ambiguous for the current estimate input"
        )
    finding = matches[0]
    duplicate = any(
        acknowledgement.get("finding_id") == args.finding_id
        and acknowledgement.get("input_hash") == validation.input_hash
        and acknowledgement.get("actor") == args.actor.strip()
        and acknowledgement.get("timestamp") == args.timestamp
        and acknowledgement.get("disposition") == args.disposition
        for acknowledgement in package.get("review", {}).get(
            "acknowledgements", []
        )
    )
    if duplicate:
        raise AcknowledgementInputError(
            "this exact acknowledgement is already recorded"
        )

    acknowledgement = acknowledge_finding(
        package,
        finding,
        actor=args.actor.strip(),
        timestamp=args.timestamp,
        disposition=args.disposition,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", dir=output_path.parent
    )
    try:
        with os.fdopen(file_descriptor, "wb") as stream:
            stream.write(canonical_json_bytes(package))
        os.link(temporary_name, output_path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return acknowledgement


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--input", required=True)
    result.add_argument("--output", required=True)
    result.add_argument("--finding-id", required=True)
    result.add_argument(
        "--input-hash",
        required=True,
        help="Relevant estimate input hash copied from the reviewed finding.",
    )
    result.add_argument("--actor", required=True)
    result.add_argument("--timestamp", required=True)
    result.add_argument(
        "--disposition",
        required=True,
        choices=("accepted", "rejected", "deferred"),
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        acknowledgement = record_acknowledgement(args)
    except AcknowledgementInputError as exc:
        print(f"Acknowledgement failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "finding_id": acknowledgement["finding_id"],
                "disposition": acknowledgement["disposition"],
                "input_hash": acknowledgement["input_hash"],
                "recorded": True,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
