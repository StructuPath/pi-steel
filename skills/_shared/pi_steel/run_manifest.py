"""Run manifests and isolated atomic artifact publication."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


MANIFEST_SCHEMA_VERSION = "1.0.0"
RUN_OUTCOMES = frozenset(
    {
        "ready",
        "review_required",
        "blocked",
        "dependency_missing",
        "usage_or_internal_error",
    }
)
OUTCOME_EXIT_CODES = {
    "ready": 0,
    "review_required": 2,
    "blocked": 3,
    "dependency_missing": 4,
    "usage_or_internal_error": 1,
}
PACKAGE_STATUSES = frozenset(
    {
        "draft",
        "review_required",
        "validated",
        "nested_partial",
        "nest_verified",
        "rfq_draft_review_required",
        "rfq_ready_for_review",
    }
)
ARTIFACT_READINESS = frozenset(
    {"geometry_verified", "reference_only", "draft", "diagnostic"}
)
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_HASH = re.compile(r"^[0-9a-f]{64}$")


class ManifestError(RuntimeError):
    """Raised when a run cannot be published safely."""


def canonical_json_bytes(value: Any) -> bytes:
    """Return a stable UTF-8 JSON representation suitable for hashing."""
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def outcome_exit_code(outcome: str) -> int:
    try:
        return OUTCOME_EXIT_CODES[outcome]
    except KeyError as exc:
        raise ManifestError(f"unknown run outcome: {outcome}") from exc


def semantic_manifest_projection(manifest: dict[str, Any]) -> dict[str, Any]:
    """Remove volatile fields and the self-referential hash before semantic hashing."""
    projection = copy.deepcopy(manifest)
    for field in ("semantic_hash", "run_id", "created_at"):
        projection.pop(field, None)
    return projection


def _safe_relative_path(value: str | Path) -> PurePosixPath:
    text = Path(value).as_posix()
    path = PurePosixPath(text)
    if (
        text in {"", "."}
        or path.is_absolute()
        or ".." in path.parts
        or path.name in {"run-manifest.json", "latest-run.json"}
    ):
        raise ManifestError(f"unsafe or reserved artifact path: {text}")
    return path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class RunPublisher:
    """Stage one isolated run and publish it with an integrity manifest."""

    def __init__(
        self,
        destination: str | Path,
        *,
        stage: str,
        run_outcome: str,
        package_status: str,
        input_hash: str,
        configuration_hash: str,
        schema_versions: dict[str, str],
        tool_versions: dict[str, str],
        explicit_dates: dict[str, str],
        warnings: list[Any] | None = None,
        approximations: list[Any] | None = None,
        run_id: str | None = None,
        created_at: str | None = None,
    ) -> None:
        if run_outcome not in RUN_OUTCOMES:
            raise ManifestError(f"unknown run outcome: {run_outcome}")
        if package_status not in PACKAGE_STATUSES:
            raise ManifestError(f"unknown package status: {package_status}")
        if not _HASH.fullmatch(input_hash) or not _HASH.fullmatch(configuration_hash):
            raise ManifestError("input and configuration hashes must be SHA-256 hex")

        self.destination = Path(destination).resolve()
        self.run_id = run_id or (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            + "-"
            + uuid.uuid4().hex[:12]
        )
        if not _RUN_ID.fullmatch(self.run_id):
            raise ManifestError(f"invalid run id: {self.run_id}")

        self._metadata = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "run_id": self.run_id,
            "stage": stage,
            "run_outcome": run_outcome,
            "package_status": package_status,
            "created_at": created_at or _utc_now(),
            "schema_versions": dict(schema_versions),
            "tool_versions": dict(tool_versions),
            "input_hash": input_hash,
            "configuration_hash": configuration_hash,
            "explicit_dates": dict(explicit_dates),
            "warnings": list(warnings or []),
            "approximations": list(approximations or []),
        }
        self._artifacts: dict[str, dict[str, Any]] = {}
        self._published = False

        staging_parent = self.destination / ".staging"
        staging_parent.mkdir(parents=True, exist_ok=True)
        self.staging_path = Path(
            tempfile.mkdtemp(prefix=f"{self.run_id}-", dir=staging_parent)
        )
        self.final_path = self.destination / "runs" / self.run_id

    def __enter__(self) -> "RunPublisher":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if not self._published and self.staging_path.exists():
            shutil.rmtree(self.staging_path)

    def path_for(self, relative_path: str | Path) -> Path:
        relative = _safe_relative_path(relative_path)
        target = self.staging_path.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def register_artifact(
        self,
        relative_path: str | Path,
        *,
        readiness: str,
        media_type: str | None = None,
    ) -> Path:
        if readiness not in ARTIFACT_READINESS:
            raise ManifestError(f"unknown artifact readiness: {readiness}")
        relative = _safe_relative_path(relative_path)
        text = relative.as_posix()
        if text in self._artifacts:
            raise ManifestError(f"artifact already registered: {text}")
        record: dict[str, Any] = {"readiness": readiness}
        if media_type:
            record["media_type"] = media_type
        self._artifacts[text] = record
        return self.path_for(relative)

    def write_bytes(
        self,
        relative_path: str | Path,
        value: bytes,
        *,
        readiness: str,
        media_type: str | None = None,
    ) -> Path:
        target = self.register_artifact(
            relative_path, readiness=readiness, media_type=media_type
        )
        target.write_bytes(value)
        return target

    def write_json(
        self,
        relative_path: str | Path,
        value: Any,
        *,
        readiness: str,
    ) -> Path:
        return self.write_bytes(
            relative_path,
            canonical_json_bytes(value),
            readiness=readiness,
            media_type="application/json",
        )

    def write_qa_report(self, value: Any) -> Path:
        """Register the standard machine-readable QA artifact for a stage run."""
        return self.write_json("qa-report.json", value, readiness="diagnostic")

    def publish(self) -> Path:
        if self._published:
            raise ManifestError("run already published")
        if self.final_path.exists():
            raise ManifestError(f"run already exists: {self.run_id}")
        if (
            self._metadata["run_outcome"] in {"ready", "review_required", "blocked"}
            and "qa-report.json" not in self._artifacts
        ):
            raise ManifestError(
                f"{self._metadata['run_outcome']} runs require qa-report.json"
            )

        actual_files = set()
        for path in self.staging_path.rglob("*"):
            if path.is_symlink():
                raise ManifestError("artifact symlinks are not allowed")
            if path.is_file():
                actual_files.add(path.relative_to(self.staging_path).as_posix())
        registered_files = set(self._artifacts)
        if actual_files != registered_files:
            missing = sorted(registered_files - actual_files)
            extra = sorted(actual_files - registered_files)
            raise ManifestError(
                f"artifact allow-list mismatch; missing={missing}, unregistered={extra}"
            )

        artifact_records = []
        for relative in sorted(self._artifacts):
            path = self.staging_path / relative
            record = {
                "path": relative,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
                **self._artifacts[relative],
            }
            artifact_records.append(record)

        manifest = {**self._metadata, "artifacts": artifact_records}
        manifest["semantic_hash"] = sha256_bytes(
            canonical_json_bytes(semantic_manifest_projection(manifest))
        )
        manifest_path = self.staging_path / "run-manifest.json"
        manifest_path.write_bytes(canonical_json_bytes(manifest))

        self.final_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(self.staging_path, self.final_path)
        manifest_hash = sha256_file(self.final_path / "run-manifest.json")
        pointer = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "run_id": self.run_id,
            "run_directory": f"runs/{self.run_id}",
            "manifest_sha256": manifest_hash,
        }
        pointer_fd, pointer_name = tempfile.mkstemp(
            prefix=".latest-run-", dir=self.destination
        )
        try:
            with os.fdopen(pointer_fd, "wb") as stream:
                stream.write(canonical_json_bytes(pointer))
            os.replace(pointer_name, self.destination / "latest-run.json")
        finally:
            if os.path.exists(pointer_name):
                os.unlink(pointer_name)

        self._published = True
        return self.final_path
