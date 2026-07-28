"""Canonical contract constants and deterministic identity helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any


ESTIMATE_PACKAGE_VERSION = "1.0.0"
NEST_RESULT_VERSION = "1.0.0"
ITEM_INTENTS = frozenset(
    {
        "fabricated_part",
        "purchased_stock",
        "hardware",
        "allowance",
        "exclusion",
        "by_others",
    }
)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def item_id_for(project_id: str, revision_id: str, source_id: str) -> str:
    """Derive normalized identity from project and stable source identity.

    ``revision_id`` remains in the signature for adapter compatibility. Legacy
    source IDs already embed their revision when no stable source key exists;
    explicit source IDs therefore remain stable across revisions.
    """
    digest = content_hash(
        {
            "project_id": project_id,
            "source_id": source_id,
        }
    )
    return f"item:{digest[:24]}"


def instance_ids(item_id: str, quantity: int) -> list[str]:
    """Expand quantity predictably; increasing quantity never renames old instances."""
    if quantity < 0:
        raise ValueError("quantity must be non-negative")
    return [f"{item_id}:instance:{index:04d}" for index in range(1, quantity + 1)]


def placement_ids(item_id: str, quantity: int) -> list[str]:
    """Derive stable per-instance placement identities from canonical item order."""
    if quantity < 0:
        raise ValueError("quantity must be non-negative")
    return [f"{item_id}:placement:{index:04d}" for index in range(1, quantity + 1)]


def fallback_source_id(revision_id: str, identity: Any) -> str:
    """Create a revision-scoped legacy identity from stable row content."""
    return f"legacy:{revision_id}:{content_hash(identity)[:20]}"


def estimate_input_projection(package: dict[str, Any]) -> dict[str, Any]:
    """Return source/config semantics, excluding review and confirmation bookkeeping."""
    projection = {
        key: value
        for key, value in package.items()
        if key not in {"review"}
    }
    projection = json.loads(json.dumps(projection))
    for stock in projection.get("stock", []):
        stock.pop("reviewer_confirmation", None)
    return projection


def estimate_input_hash(package: dict[str, Any]) -> str:
    return content_hash(estimate_input_projection(package))


def finding_id_for(code: str, path: str) -> str:
    return f"finding:{content_hash({'code': code, 'path': path})[:24]}"
