"""Schema and domain validation for canonical estimate packages."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

from .contracts import (
    ESTIMATE_PACKAGE_VERSION,
    content_hash,
    estimate_input_hash,
    finding_id_for,
)
from .geometry_verify import (
    SUPPORTED_SHAPES,
    finite_positive,
    hole_within_bounds,
    net_area,
)


_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "estimate-package.schema.json"
)
_REVIEWABLE_BLOCKERS = frozenset(
    {
        "missing_material_basis",
        "unconfirmed_on_hand_stock",
    }
)


@dataclass(frozen=True)
class ValidationResult:
    status: str
    input_hash: str
    findings: list[dict[str, Any]]
    active_findings: list[dict[str, Any]]

    @property
    def blockers(self) -> list[dict[str, Any]]:
        return [
            finding
            for finding in self.active_findings
            if finding["severity"] == "blocker"
        ]

    @property
    def warnings(self) -> list[dict[str, Any]]:
        return [
            finding
            for finding in self.active_findings
            if finding["severity"] == "warning"
        ]


def _path(parts: Any) -> str:
    result = "$"
    for part in parts:
        result += f"[{part}]" if isinstance(part, int) else f".{part}"
    return result


def _finding(
    *,
    code: str,
    severity: str,
    path: str,
    message: str,
    relevant_hash: str,
) -> dict[str, Any]:
    return {
        "finding_id": finding_id_for(code, path),
        "code": code,
        "severity": severity,
        "path": path,
        "message": message,
        "relevant_hash": relevant_hash,
    }


def _add(
    findings: list[dict[str, Any]],
    input_hash: str,
    code: str,
    severity: str,
    path: str,
    message: str,
) -> None:
    findings.append(
        _finding(
            code=code,
            severity=severity,
            path=path,
            message=message,
            relevant_hash=input_hash,
        )
    )


@lru_cache(maxsize=1)
def _schema_validator():
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    )


def _schema_findings(
    package: dict[str, Any], input_hash: str
) -> list[dict[str, Any]]:
    findings = []
    for error in sorted(
        _schema_validator().iter_errors(package),
        key=lambda item: list(item.path),
    ):
        _add(
            findings,
            input_hash,
            "schema_validation",
            "blocker",
            _path(error.absolute_path),
            error.message,
        )
    return findings


def _geometry_findings(
    item: dict[str, Any],
    index: int,
    input_hash: str,
    findings: list[dict[str, Any]],
) -> None:
    geometry = item.get("geometry")
    if not isinstance(geometry, dict):
        return
    base = f"$.items[{index}].geometry"
    shape = geometry.get("shape")
    if shape not in SUPPORTED_SHAPES:
        _add(
            findings,
            input_hash,
            "unsupported_shape",
            "blocker",
            f"{base}.shape",
            f"Unsupported shape {shape!r}; expected rect or irregular.",
        )
    dimensions = ("width", "height", "thickness")
    for field in dimensions:
        value = geometry.get(field)
        if isinstance(value, (int, float)) and not math.isfinite(value):
            _add(
                findings,
                input_hash,
                "nonfinite_dimension",
                "blocker",
                f"{base}.{field}",
                f"{field} must be finite.",
            )
        elif not finite_positive(value):
            _add(
                findings,
                input_hash,
                "nonpositive_dimension",
                "blocker",
                f"{base}.{field}",
                f"{field} must be greater than zero.",
            )
    width, height = geometry.get("width"), geometry.get("height")
    if finite_positive(width) and finite_positive(height):
        for hole_index, hole in enumerate(geometry.get("holes", [])):
            if not hole_within_bounds(hole, width, height):
                _add(
                    findings,
                    input_hash,
                    "hole_out_of_bounds",
                    "blocker",
                    f"{base}.holes[{hole_index}]",
                    "Hole geometry must be positive and contained by the part.",
                )
        try:
            area = net_area(geometry)
        except (TypeError, ValueError, OverflowError):
            area = math.nan
        if not math.isfinite(area) or area <= 0:
            _add(
                findings,
                input_hash,
                "nonpositive_net_area",
                "blocker",
                base,
                "Part net area after holes must be greater than zero.",
            )
        if shape == "irregular" and not finite_positive(geometry.get("area")):
            _add(
                findings,
                input_hash,
                "invalid_irregular_area",
                "blocker",
                f"{base}.area",
                "Irregular parts require a positive true-cut area.",
            )


def validate_estimate_package(package: dict[str, Any]) -> ValidationResult:
    if not isinstance(package, dict):
        input_hash = content_hash(package)
        finding = _finding(
            code="schema_validation",
            severity="blocker",
            path="$",
            message="Estimate package must be a JSON object.",
            relevant_hash=input_hash,
        )
        return ValidationResult("invalid", input_hash, [finding], [finding])
    input_hash = estimate_input_hash(package)
    version = package.get("schema_version")
    if version != ESTIMATE_PACKAGE_VERSION:
        finding = _finding(
            code="unsupported_contract_version",
            severity="blocker",
            path="$.schema_version",
            message=(
                f"Unsupported estimate package version {version!r}; "
                f"migrate to {ESTIMATE_PACKAGE_VERSION} before processing."
            ),
            relevant_hash=input_hash,
        )
        return ValidationResult("invalid", input_hash, [finding], [finding])

    findings = _schema_findings(package, input_hash)
    if findings:
        return ValidationResult("invalid", input_hash, findings, findings)
    source_ids: dict[str, int] = {}
    item_ids: dict[str, int] = {}
    for index, item in enumerate(package.get("items", [])):
        base = f"$.items[{index}]"
        quantity = item.get("quantity")
        if (
            not isinstance(quantity, int)
            or isinstance(quantity, bool)
            or quantity <= 0
        ):
            _add(
                findings,
                input_hash,
                "invalid_quantity",
                "blocker",
                f"{base}.quantity",
                "Quantity must be a positive integer.",
            )
        for field, seen, code in (
            ("source_id", source_ids, "duplicate_source_id"),
            ("item_id", item_ids, "duplicate_item_id"),
        ):
            identity = item.get(field)
            if identity in seen:
                _add(
                    findings,
                    input_hash,
                    code,
                    "blocker",
                    f"{base}.{field}",
                    f"{field} duplicates item {seen[identity]}; rows were not merged.",
                )
            elif identity is not None:
                seen[identity] = index

        if item.get("identity_warning"):
            _add(
                findings,
                input_hash,
                "unstable_source_identity",
                "warning",
                f"{base}.source_id",
                "No explicit source ID or stable mark was supplied; identity is revision-scoped.",
            )
        if not item.get("source_evidence"):
            _add(
                findings,
                input_hash,
                "missing_source_evidence",
                "warning",
                f"{base}.source_evidence",
                "No drawing or structured-source locator was supplied; none was invented.",
            )
        if item.get("intent") == "fabricated_part":
            _geometry_findings(item, index, input_hash, findings)
            if item.get("geometry") and (
                not item.get("material")
                or not item.get("grade")
                or not finite_positive(item.get("geometry", {}).get("thickness"))
            ):
                _add(
                    findings,
                    input_hash,
                    "missing_material_basis",
                    "blocker",
                    base,
                    "Plate material, grade, and thickness must be explicit before nesting, RFQ, or burn.",
                )
            if not item.get("geometry"):
                if not item.get("designation"):
                    _add(
                        findings,
                        input_hash,
                        "missing_designation",
                        "blocker",
                        f"{base}.designation",
                        "A legacy member requires a section designation.",
                    )
                for field, code, label in (
                    ("length_ft", "invalid_member_length", "Member length"),
                    (
                        "unit_weight_plf",
                        "invalid_unit_weight",
                        "Member unit weight",
                    ),
                ):
                    if not finite_positive(item.get(field)):
                        _add(
                            findings,
                            input_hash,
                            code,
                            "blocker",
                            f"{base}.{field}",
                            f"{label} must be finite and greater than zero.",
                        )
                if not item.get("grade"):
                    _add(
                        findings,
                        input_hash,
                        "missing_grade",
                        "warning",
                        f"{base}.grade",
                        "No material grade was supplied; none was inferred.",
                    )

    for index, stock in enumerate(package.get("stock", [])):
        if stock.get("stock_kind") != "on_hand":
            continue
        required = (
            stock.get("inventory_id"),
            stock.get("measured_at"),
            stock.get("source"),
            stock.get("status") in {"available", "reserved"},
        )
        confirmation = stock.get("reviewer_confirmation", {})
        confirmed = (
            all(required)
            and confirmation.get("estimate_hash") == input_hash
            and confirmation.get("actor")
            and confirmation.get("timestamp")
        )
        if not confirmed:
            _add(
                findings,
                input_hash,
                "unconfirmed_on_hand_stock",
                "blocker",
                f"$.stock[{index}]",
                "On-hand stock cannot reduce purchasing without traceable measurements and hash-bound reviewer confirmation.",
            )

    basis = package.get("commercial_basis", {})
    for index, cost in enumerate(basis.get("costs", [])):
        if cost.get("currency") != basis.get("currency") or not all(
            cost.get(field)
            for field in ("unit_basis", "effective_date", "source")
        ):
            _add(
                findings,
                input_hash,
                "invalid_cost_basis",
                "blocker",
                f"$.commercial_basis.costs[{index}]",
                "Cost currency, unit basis, effective date, and source must be preserved.",
            )

    acknowledgements = package.get("review", {}).get("acknowledgements", [])
    accepted_findings = {
        (acknowledgement.get("finding_id"), acknowledgement.get("input_hash"))
        for acknowledgement in acknowledgements
        if acknowledgement.get("disposition") == "accepted"
    }
    active = []
    for finding in findings:
        acknowledged = (
            finding["severity"] != "blocker"
            and (finding["finding_id"], finding["relevant_hash"])
            in accepted_findings
        )
        if not acknowledged:
            active.append(finding)

    blockers = [f for f in active if f["severity"] == "blocker"]
    if blockers:
        status = (
            "review_required"
            if all(f["code"] in _REVIEWABLE_BLOCKERS for f in blockers)
            else "invalid"
        )
    elif any(f["severity"] == "warning" for f in active):
        status = "review_required"
    else:
        status = "validated"
    return ValidationResult(status, input_hash, findings, active)


def acknowledge_finding(
    package: dict[str, Any],
    finding: dict[str, Any],
    *,
    actor: str,
    timestamp: str,
    disposition: str,
) -> dict[str, Any]:
    if disposition not in {"accepted", "rejected", "deferred"}:
        raise ValueError("unsupported acknowledgement disposition")
    acknowledgement = {
        "finding_id": finding["finding_id"],
        "actor": actor,
        "timestamp": timestamp,
        "disposition": disposition,
        "input_hash": finding["relevant_hash"],
    }
    package.setdefault("review", {}).setdefault("acknowledgements", []).append(
        acknowledgement
    )
    return acknowledgement


def eligible_on_hand_stock(package: dict[str, Any]) -> list[dict[str, Any]]:
    input_hash = estimate_input_hash(package)
    eligible = []
    for stock in package.get("stock", []):
        confirmation = stock.get("reviewer_confirmation", {})
        if (
            stock.get("stock_kind") == "on_hand"
            and stock.get("inventory_id")
            and finite_positive(stock.get("width"))
            and finite_positive(stock.get("height"))
            and finite_positive(stock.get("thickness"))
            and stock.get("measured_at")
            and stock.get("source")
            and stock.get("status") == "available"
            and confirmation.get("actor")
            and confirmation.get("timestamp")
            and confirmation.get("estimate_hash") == input_hash
        ):
            eligible.append(stock)
    return eligible


def purchasable_items(package: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in package.get("items", [])
        if item.get("intent") in {"fabricated_part", "purchased_stock", "hardware"}
    ]


def stock_requiring_purchase(package: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only stock explicitly modeled as purchasable.

    On-hand entries that are unavailable or not confirmed remain validation
    findings; they never silently become vendor demand.
    """
    return [
        stock
        for stock in package.get("stock", [])
        if stock.get("stock_kind") == "purchasable"
    ]
