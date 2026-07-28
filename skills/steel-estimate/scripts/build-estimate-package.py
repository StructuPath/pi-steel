#!/usr/bin/env python3
"""Build one deterministic, review-gated steel estimate package."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import re
import sys
import tempfile
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any


SHARED_ROOT = Path(__file__).resolve().parents[2] / "_shared"
if str(SHARED_ROOT) not in sys.path:
    sys.path.insert(0, str(SHARED_ROOT))
from bootstrap import bootstrap_shared  # noqa: E402

bootstrap_shared(__file__)
from pi_steel import (  # noqa: E402
    RunPublisher,
    StageArgumentParser,
    canonical_json_bytes,
    outcome_exit_code,
    package_version,
    publish_failure_diagnostic,
    sha256_bytes,
)
from pi_steel.contracts import ESTIMATE_PACKAGE_VERSION  # noqa: E402
from pi_steel.validation import (  # noqa: E402
    eligible_on_hand_stock,
    validate_estimate_package,
)


PIPELINE_VERSION = "1.0.0"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SKILLS_ROOT = Path(__file__).resolve().parents[2]
nest_engine = _load_module(
    "pi_steel_estimate_nest",
    SKILLS_ROOT / "steel-nest" / "scripts" / "nest.py",
)
rfq_compiler = _load_module(
    "pi_steel_estimate_rfq",
    SKILLS_ROOT / "steel-rfq" / "scripts" / "generate-rfq.py",
)


class PipelineInputError(ValueError):
    pass


def normalized_package(package: dict[str, Any]) -> dict[str, Any]:
    """Return a stable canonical ordering without changing supplied facts."""
    value = copy.deepcopy(package)
    value["items"] = sorted(
        value.get("items", []),
        key=lambda item: (
            item.get("item_id", "") if isinstance(item, dict) else ""
        ),
    )
    value["stock"] = sorted(
        value.get("stock", []),
        key=lambda stock: (
            stock.get("inventory_id", "") if isinstance(stock, dict) else "",
            stock.get("material", "") if isinstance(stock, dict) else "",
            stock.get("grade", "") if isinstance(stock, dict) else "",
            stock.get("thickness", 0) if isinstance(stock, dict) else 0,
            stock.get("width", 0) if isinstance(stock, dict) else 0,
            stock.get("height", 0) if isinstance(stock, dict) else 0,
        ),
    )
    review = value.get("review", {})
    if isinstance(review, dict):
        review["findings"] = sorted(
            review.get("findings", []),
            key=lambda finding: finding.get("finding_id", ""),
        )
        review["acknowledgements"] = sorted(
            review.get("acknowledgements", []),
            key=lambda acknowledgement: (
                acknowledgement.get("finding_id", ""),
                acknowledgement.get("timestamp", ""),
                acknowledgement.get("actor", ""),
            ),
        )
    return value


def _legacy_hole(hole: dict[str, Any]) -> dict[str, Any]:
    if hole["kind"] == "round":
        return {
            "dia": hole["diameter"],
            "x": hole["x"],
            "y": hole["y"],
        }
    return {
        "w": hole["width"],
        "h": hole["height"],
        "x": hole["x"],
        "y": hole["y"],
    }


def nest_job_from_package(
    package: dict[str, Any],
    *,
    estimate_input_hash: str,
    eligible_inventory_ids: set[str],
    kerf_in: float,
    part_gap_in: float,
    edge_margin_in: float,
    density_lb_in3: float,
) -> dict[str, Any] | None:
    plate_items = [
        item
        for item in package["items"]
        if item["intent"] == "fabricated_part" and item.get("geometry")
    ]
    if not plate_items:
        return None
    stock_rows = []
    for index, stock in enumerate(package.get("stock", []), start=1):
        if (
            stock["stock_kind"] == "on_hand"
            and stock.get("inventory_id") not in eligible_inventory_ids
        ):
            continue
        stock_rows.append(
            {
                "stock_id": stock.get("inventory_id")
                or f"purchasable-stock:{index:04d}",
                "name": stock.get("inventory_id") or f"Purchase Stock {index}",
                "material": stock["material"],
                "grade": stock["grade"],
                "width": stock["width"],
                "height": stock["height"],
                "thickness": stock["thickness"],
                "qty": stock["quantity"],
            }
        )
    parts = []
    for item in plate_items:
        geometry = item["geometry"]
        part = {
            "source_id": item["source_id"],
            "item_id": item["item_id"],
            "name": item.get("mark") or item["item_id"],
            "material": item["material"],
            "grade": item["grade"],
            "thickness": geometry["thickness"],
            "width": geometry["width"],
            "height": geometry["height"],
            "qty": item["quantity"],
            "shape": geometry["shape"],
            "rotatable": geometry.get("rotatable", True),
            "holes": [_legacy_hole(hole) for hole in geometry.get("holes", [])],
        }
        if geometry.get("area") is not None:
            part["area"] = geometry["area"]
        parts.append(part)
    return {
        "job_name": package["project"].get("name")
        or package["project"]["project_id"],
        "project_id": package["project"]["project_id"],
        "revision_id": package["project"]["revision"]["revision_id"],
        "estimate_input_hash": estimate_input_hash,
        "unit_system": package["unit_system"],
        "settings": {
            "kerf_in": kerf_in,
            "part_gap_in": part_gap_in,
            "edge_margin_in": edge_margin_in,
            "density_lb_in3": density_lb_in3,
        },
        "stock": stock_rows,
        "parts": parts,
    }


def build_bom_projection(
    package: dict[str, Any], nest_result: dict[str, Any] | None
) -> dict[str, Any]:
    items = []
    known_member_weight = 0.0
    for item in package["items"]:
        row = {
            "source_id": item["source_id"],
            "item_id": item["item_id"],
            "intent": item["intent"],
            "quantity": item["quantity"],
            "description": item.get("description", ""),
        }
        if item.get("mark") is not None:
            row["mark"] = item["mark"]
        if item.get("grade") is not None:
            row["grade"] = item["grade"]
        if item.get("designation") is not None:
            row["designation"] = item["designation"]
        if item.get("geometry") is not None:
            row["geometry"] = item["geometry"]
        if item.get("allowance_basis") is not None:
            row["allowance_basis"] = item["allowance_basis"]
        if item.get("reason") is not None:
            row["reason"] = item["reason"]
        weight = item.get("total_weight_lbs")
        if (
            weight is None
            and item.get("length_ft") is not None
            and item.get("unit_weight_plf") is not None
        ):
            weight = item["quantity"] * item["length_ft"] * item["unit_weight_plf"]
        if (
            weight is not None
            and item["intent"] == "fabricated_part"
            and item.get("geometry") is None
        ):
            row["calculated_weight_lbs"] = round(float(weight), 3)
            known_member_weight += float(weight)
        items.append(row)

    nested_plate_weight = (
        nest_result["total_part_weight_lb"] if nest_result is not None else 0.0
    )
    fabricated_weight = known_member_weight + nested_plate_weight
    allowance_weight = 0.0
    allowance_rows = []
    for item in package["items"]:
        if item["intent"] != "allowance":
            continue
        basis = item["allowance_basis"]
        if basis["kind"] == "percent" and basis["applies_to"] == "fabricated_weight":
            weight = fabricated_weight * basis["value"] / 100
        elif basis["kind"] == "fixed_weight":
            weight = basis["value"]
        else:
            weight = None
        allowance_rows.append(
            {
                "item_id": item["item_id"],
                "basis": basis,
                "calculated_weight_lbs": (
                    None if weight is None else round(weight, 3)
                ),
                "vendor_quantity": None,
            }
        )
        if weight is not None:
            allowance_weight += weight
    complete = not (nest_result and nest_result["unplaced"])
    return {
        "schema_version": "1.0.0",
        "project_id": package["project"]["project_id"],
        "revision_id": package["project"]["revision"]["revision_id"],
        "items": items,
        "totals": {
            "known_member_weight_lbs": round(known_member_weight, 3),
            "nested_plate_weight_lbs": round(nested_plate_weight, 3),
            "fabricated_weight_lbs": round(fabricated_weight, 3),
            "allowance_weight_lbs": round(allowance_weight, 3),
            "estimate_weight_lbs": round(fabricated_weight + allowance_weight, 3),
            "status": "complete" if complete else "incomplete_unplaced",
        },
        "allowances": allowance_rows,
        "pricing_status": "not_calculated_without_explicit_cost_basis",
    }


def _annotated_handoff(nest_result: dict[str, Any] | None):
    if nest_result is None:
        return None
    handoff = copy.deepcopy(nest_result["rfq_nesting"])
    for row in handoff["rows"]:
        row["geometry_readiness"] = nest_result["geometry_readiness"]
    return handoff


def apply_inventory_consumption(
    package: dict[str, Any],
    rfq_normalized: dict[str, Any],
    nest_result: dict[str, Any] | None,
    eligible_inventory_ids: set[str],
) -> list[dict[str, Any]]:
    """Reduce RFQ demand only for traceable on-hand sheets actually consumed."""
    used = Counter(
        report["stock_id"]
        for report in (nest_result or {}).get("plate_reports", [])
        if report["stock_id"] in eligible_inventory_ids
    )
    normalized_by_id = {
        item["item_id"]: item for item in rfq_normalized.get("items", [])
    }
    purchase_items = sorted(
        (
            item
            for item in package.get("items", [])
            if item.get("intent") == "purchased_stock"
            and (
                (item.get("dimensions") or {}).get("inventory_id")
                or (item.get("dimensions") or {}).get("stock_id")
            )
        ),
        key=lambda row: row["item_id"],
    )
    lineage = []
    for inventory_id in sorted(used):
        remaining = used[inventory_id]
        for item in purchase_items:
            if remaining <= 0:
                break
            dimensions = item.get("dimensions") or {}
            linked_stock_id = (
                dimensions.get("inventory_id") or dimensions.get("stock_id")
            )
            if linked_stock_id != inventory_id:
                continue
            rfq_item = normalized_by_id.get(item["item_id"])
            if rfq_item is None:
                continue
            original_quantity = rfq_item["quantity"]
            satisfied = min(original_quantity, remaining)
            if satisfied <= 0:
                continue
            remaining -= satisfied
            open_quantity = original_quantity - satisfied
            if open_quantity:
                rfq_item["quantity"] = open_quantity
                if rfq_item.get("purchase_weight_lbs") is not None:
                    rfq_item["purchase_weight_lbs"] = round(
                        rfq_item["purchase_weight_lbs"]
                        * open_quantity
                        / original_quantity,
                        3,
                    )
            else:
                rfq_normalized["items"].remove(rfq_item)
                normalized_by_id.pop(item["item_id"], None)
            lineage.append(
                {
                    "inventory_id": inventory_id,
                    "purchase_item_id": item["item_id"],
                    "satisfied_quantity": satisfied,
                    "remaining_purchase_quantity": open_quantity,
                }
            )
    return lineage


def _fixed_xlsx(path: Path, issued_date: str) -> None:
    """Normalize volatile XLSX metadata and ZIP timestamps for stable byte hashes."""
    timestamp = f"{issued_date}T00:00:00Z".encode()
    with zipfile.ZipFile(path, "r") as source:
        entries = {
            info.filename: (info, source.read(info.filename))
            for info in source.infolist()
        }
    core_name = "docProps/core.xml"
    if core_name in entries:
        original, content = entries[core_name]
        content = re.sub(
            rb"(<dcterms:(?:created|modified)[^>]*>).*?(</dcterms:(?:created|modified)>)",
            lambda match: match.group(1) + timestamp + match.group(2),
            content,
        )
        entries[core_name] = (original, content)
    with tempfile.NamedTemporaryFile(
        prefix=path.stem + "-", suffix=".xlsx", dir=path.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(
            temporary_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as destination:
            for name in sorted(entries):
                original, content = entries[name]
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = original.external_attr
                info.create_system = original.create_system
                destination.writestr(info, content)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _finding(code, severity, path, message):
    return {
        "code": code,
        "severity": severity,
        "path": path,
        "message": message,
    }


def _valid_date(value: str) -> bool:
    try:
        return date.fromisoformat(value).isoformat() == value
    except (TypeError, ValueError):
        return False


def build_pipeline(args) -> tuple[dict[str, Any], Path]:
    if not _valid_date(args.prepared_date):
        raise PipelineInputError("--prepared-date must be an ISO date (YYYY-MM-DD)")
    if not _valid_date(args.issued_date):
        raise PipelineInputError("--issued-date must be an ISO date (YYYY-MM-DD)")
    input_path = Path(args.input)
    package = json.loads(input_path.read_text(encoding="utf-8"))
    validation = validate_estimate_package(package)
    normalized = (
        normalized_package(package)
        if isinstance(package, dict)
        else {"invalid_input": package}
    )
    eligible_inventory_ids = (
        {
            stock["inventory_id"]
            for stock in eligible_on_hand_stock(package)
        }
        if not validation.blockers
        else set()
    )
    findings = [
        {
            "code": finding["code"],
            "severity": finding["severity"],
            "path": finding["path"],
            "message": finding["message"],
        }
        for finding in validation.active_findings
    ]
    validation_blocked = bool(validation.blockers)

    try:
        profile, profile_source = rfq_compiler.resolve_company_profile(input_path)
        profile_findings = rfq_compiler.validate_company_profile(
            profile, profile.get("_profile_path") if profile else None
        )
    except rfq_compiler.RfqInputError as exc:
        profile, profile_source = None, "invalid"
        profile_findings = [
            {
                "code": "invalid_company_profile",
                "severity": "error",
                "message": str(exc),
            }
        ]
    findings.extend(
        _finding(
            finding["code"],
            "blocker" if finding["severity"] == "error" else "warning",
            "$.company_profile",
            finding["message"],
        )
        for finding in profile_findings
    )
    profile_blocked = bool(profile_findings)

    nest_result = None
    if not validation_blocked:
        nest_job = nest_job_from_package(
            normalized,
            estimate_input_hash=validation.input_hash,
            eligible_inventory_ids=eligible_inventory_ids,
            kerf_in=args.kerf_in,
            part_gap_in=args.part_gap_in,
            edge_margin_in=args.edge_margin_in,
            density_lb_in3=args.density_lb_in3,
        )
        if nest_job is not None:
            nest_result = nest_engine.run_job(nest_job)
            for nest_finding in nest_result["validation_findings"]:
                findings.append(
                    _finding(
                        nest_finding["code"],
                        "blocker"
                        if nest_finding["severity"] == "error"
                        else "warning",
                        nest_finding["path"],
                        nest_finding["message"],
                    )
                )
            for verifier_finding in nest_result["verification"]["findings"]:
                findings.append(
                    _finding(
                        verifier_finding["code"],
                        "blocker",
                        verifier_finding["path"],
                        verifier_finding["message"],
                    )
                )
            if nest_result["unplaced"]:
                findings.append(
                    _finding(
                        "unplaced_parts",
                        "blocker",
                        "$.nest.unplaced",
                        (
                            f"{sum(row['quantity'] for row in nest_result['unplaced'])} "
                            "required plate part(s) remain unplaced."
                        ),
                    )
                )
    unplaced = bool(nest_result and nest_result["unplaced"])
    nest_blocked = bool(
        nest_result
        and (
            nest_result["outcome"] == "blocked"
            or nest_result["verification"]["status"] != "verified"
        )
    )
    reference_only = bool(
        nest_result and nest_result["geometry_readiness"] == "reference_only"
    )
    approximations = []
    if reference_only:
        approximations.append(
            {
                "code": "BOUNDING_BOX_NESTING",
                "message": "Irregular plate geometry is reference-only.",
            }
        )

    render_missing = []
    if not args.no_render and nest_result is not None:
        render_missing = nest_engine.missing_render_dependencies()
        if render_missing:
            findings.append(
                _finding(
                    "render_dependency_missing",
                    "blocker",
                    "$.render",
                    "Missing rendering modules: " + ", ".join(render_missing),
                )
            )

    rfq_normalized = None
    inventory_consumption = []
    compiler_error = None
    if not validation_blocked and not profile_blocked and not nest_blocked and not render_missing:
        try:
            rfq_normalized = rfq_compiler.normalize_canonical_package(package)
            inventory_consumption = apply_inventory_consumption(
                package,
                rfq_normalized,
                nest_result,
                eligible_inventory_ids,
            )
            if not rfq_normalized["items"]:
                raise rfq_compiler.RfqInputError(
                    "no open vendor-supply items remain after inventory consumption"
                )
        except rfq_compiler.RfqInputError as exc:
            compiler_error = str(exc)
            findings.append(
                _finding("rfq_input_blocked", "blocker", "$.rfq", compiler_error)
            )

    blocked = (
        validation_blocked
        or profile_blocked
        or nest_blocked
        or unplaced
        or bool(render_missing)
        or compiler_error is not None
    )
    review_warnings = [
        finding["message"]
        for finding in findings
        if finding["severity"] == "warning"
    ]
    if blocked:
        outcome = "dependency_missing" if render_missing else "blocked"
        package_status = "nested_partial" if unplaced else "draft"
    elif reference_only or review_warnings:
        outcome = "review_required"
        package_status = "rfq_draft_review_required"
    else:
        outcome = "ready"
        package_status = "rfq_ready_for_review"

    handoff = _annotated_handoff(nest_result)
    configuration = {
        "pipeline_version": PIPELINE_VERSION,
        "nest_algorithm_version": nest_engine.NEST_ALGORITHM_VERSION,
        "rfq_compiler_version": rfq_compiler.RFQ_COMPILER_VERSION,
        "prepared_date": args.prepared_date,
        "issued_date": args.issued_date,
        "project_location": args.project_location,
        "kerf_in": args.kerf_in,
        "part_gap_in": args.part_gap_in,
        "edge_margin_in": args.edge_margin_in,
        "density_lb_in3": args.density_lb_in3,
        "render": not args.no_render,
        "bake": not args.no_bake,
        "profile_hash": rfq_compiler.profile_semantic_hash(profile),
    }
    configuration_hash = sha256_bytes(canonical_json_bytes(configuration))
    if validation_blocked:
        project = normalized.get("project", {})
        revision = project.get("revision", {}) if isinstance(project, dict) else {}
        bom = {
            "schema_version": "1.0.0",
            "project_id": (
                project.get("project_id") if isinstance(project, dict) else None
            ),
            "revision_id": (
                revision.get("revision_id") if isinstance(revision, dict) else None
            ),
            "items": [],
            "totals": {"status": "blocked_invalid_input"},
            "allowances": [],
            "pricing_status": "not_calculated_without_valid_input",
        }
    else:
        bom = build_bom_projection(normalized, nest_result)
    project = normalized.get("project", {})
    project = project if isinstance(project, dict) else {}
    revision = project.get("revision", {})
    revision = revision if isinstance(revision, dict) else {}
    qa_report = {
        "schema_version": "1.0.0",
        "stage": "steel-estimate",
        "run_outcome": outcome,
        "package_status": package_status,
        "project_id": project.get("project_id"),
        "revision_id": revision.get("revision_id"),
        "input_hash": validation.input_hash,
        "configuration_hash": configuration_hash,
        "profile_source": profile_source,
        "findings": findings,
        "warnings": review_warnings,
        "approximations": approximations,
        "nest": (
            None
            if nest_result is None
            else {
                "outcome": nest_result["outcome"],
                "geometry_readiness": nest_result["geometry_readiness"],
                "unplaced": nest_result["unplaced"],
                "verification": nest_result["verification"],
            }
        ),
        "rfq": {
            "generated": not blocked,
            "document_status": "DRAFT — NOT SENT OR AWARDED",
            "recalculation_status": None,
        },
    }

    with RunPublisher(
        args.out,
        stage="steel-estimate",
        run_outcome=outcome,
        package_status=package_status,
        input_hash=validation.input_hash,
        configuration_hash=configuration_hash,
        schema_versions={
            "run_manifest": "1.0.0",
            "estimate_package": ESTIMATE_PACKAGE_VERSION,
            "normalized_bom": "1.0.0",
            "nest_result": nest_engine.NEST_RESULT_VERSION,
            "rfq_nesting": rfq_compiler.NEST_HANDOFF_VERSION,
            "rfq_workbook": rfq_compiler.RFQ_COMPILER_VERSION,
        },
        tool_versions={
            "pi_steel": package_version(__file__),
            "estimate_pipeline": PIPELINE_VERSION,
            "nest_algorithm": nest_engine.NEST_ALGORITHM_VERSION,
            "rfq_compiler": rfq_compiler.RFQ_COMPILER_VERSION,
        },
        explicit_dates={
            "prepared_date": args.prepared_date,
            "issued_date": args.issued_date,
        },
        warnings=review_warnings,
        approximations=approximations,
        run_id=args.run_id,
    ) as publisher:
        publisher.write_json(
            "estimate-package.json", normalized, readiness="draft"
        )
        publisher.write_json("normalized-bom.json", bom, readiness="diagnostic")
        if nest_result is not None:
            publisher.write_json(
                "nest-result.json", nest_result, readiness="diagnostic"
            )
            publisher.write_json(
                "rfq-nesting.json", handoff, readiness="diagnostic"
            )
        if inventory_consumption:
            publisher.write_json(
                "inventory-consumption.json",
                inventory_consumption,
                readiness="diagnostic",
            )

        if not blocked:
            compile_result = rfq_compiler.compile_workbook(
                rfq_normalized,
                profile,
                nest_handoff=handoff,
                issued_date=args.issued_date,
                project_location=args.project_location,
                output_directory=publisher.staging_path,
                profile_source=profile_source,
                bake=not args.no_bake,
            )
            workbook_path = compile_result["workbook_path"]
            _fixed_xlsx(workbook_path, args.issued_date)
            qa_report["rfq"]["recalculation_status"] = compile_result[
                "recalculation_status"
            ]
            qa_report["rfq"]["logo_status"] = compile_result["logo_status"]
            publisher.register_artifact(
                workbook_path.name,
                readiness="draft",
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            publisher.write_json(
                "workbook-semantic.json",
                rfq_compiler.workbook_semantic_projection(workbook_path),
                readiness="diagnostic",
            )

        if not args.no_render and nest_result is not None and not render_missing:
            nest_engine.render_layout(nest_result, publisher.staging_path)
            publisher.register_artifact(
                "layout.pdf",
                readiness="reference_only",
                media_type="application/pdf",
            )
            for plate in nest_result["plate_reports"]:
                publisher.register_artifact(
                    f"plate_{plate['index']}.png",
                    readiness="reference_only",
                    media_type="image/png",
                )
            if nest_result["plate_reports"]:
                nest_engine.render_dxf_overview(nest_result, publisher.staging_path)
                nest_engine.render_reference_plate_dxfs(
                    nest_result, publisher.staging_path
                )
                publisher.register_artifact(
                    "reference_nest.dxf",
                    readiness="reference_only",
                    media_type="image/vnd.dxf",
                )
                for plate in nest_result["plate_reports"]:
                    publisher.register_artifact(
                        f"reference_plate_{plate['index']}.dxf",
                        readiness="reference_only",
                        media_type="image/vnd.dxf",
                    )
            if outcome == "ready" and nest_result["burn_dxf_eligible"]:
                nest_engine.render_burn_dxfs(nest_result, publisher.staging_path)
                for plate in nest_result["plate_reports"]:
                    publisher.register_artifact(
                        f"burn_plate_{plate['index']}.dxf",
                        readiness="geometry_verified",
                        media_type="image/vnd.dxf",
                    )

        publisher.write_qa_report(qa_report)
        final_path = publisher.publish()
    return qa_report, final_path


def main(argv=None) -> int:
    parser = StageArgumentParser(description=__doc__)
    parser.configure_failure_diagnostics(
        stage="steel-estimate",
        entry_file=__file__,
        input_option="--input",
        date_options={
            "--prepared-date": "prepared_date",
            "--issued-date": "issued_date",
        },
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", default="outputs")
    parser.add_argument("--prepared-date", required=True)
    parser.add_argument("--issued-date", required=True)
    parser.add_argument("--project-location", default="")
    parser.add_argument("--kerf-in", type=float, default=0.06)
    parser.add_argument("--part-gap-in", type=float, default=0.25)
    parser.add_argument("--edge-margin-in", type=float, default=0.5)
    parser.add_argument("--density-lb-in3", type=float, default=0.2836)
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument("--no-bake", action="store_true")
    parser.add_argument("--run-id", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        qa_report, final_path = build_pipeline(args)
    except (OSError, json.JSONDecodeError, PipelineInputError) as exc:
        diagnostic_path = publish_failure_diagnostic(
            args.out,
            stage="steel-estimate",
            input_path=args.input,
            error=exc,
            tool_version=package_version(__file__),
            run_id=args.run_id,
            explicit_dates={
                "prepared_date": args.prepared_date,
                "issued_date": args.issued_date,
            },
        )
        suffix = (
            f"; diagnostic published: {diagnostic_path}"
            if diagnostic_path is not None
            else "; diagnostic publication unavailable"
        )
        print(f"Estimate package failed: {exc}{suffix}", file=sys.stderr)
        return 1
    print(f"Published {qa_report['run_outcome']} estimate package: {final_path}")
    return outcome_exit_code(qa_report["run_outcome"])


if __name__ == "__main__":
    raise SystemExit(main())
