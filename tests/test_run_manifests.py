import json
import os
import sys
from pathlib import Path

import jsonschema
import pytest


ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "skills" / "_shared"
sys.path.insert(0, str(SHARED))

from pi_steel.run_manifest import (
    ManifestError,
    RunPublisher,
    canonical_json_bytes,
    semantic_manifest_projection,
    sha256_bytes,
    sha256_file,
)
import pi_steel.run_manifest as run_manifest


INPUT_HASH = sha256_bytes(b"SYNTHETIC-INPUT")
CONFIGURATION_HASH = sha256_bytes(b"SYNTHETIC-CONFIGURATION")
CREATED_AT = "2026-07-28T12:00:00Z"


def publisher(
    destination,
    run_id,
    *,
    outcome="ready",
    status="validated",
    created_at=CREATED_AT,
):
    return RunPublisher(
        destination,
        stage="runtime_test",
        run_outcome=outcome,
        package_status=status,
        input_hash=INPUT_HASH,
        configuration_hash=CONFIGURATION_HASH,
        schema_versions={"run_manifest": "1.0.0"},
        tool_versions={"pi_steel": "0.3.0"},
        explicit_dates={"as_of": "2026-07-28"},
        run_id=run_id,
        created_at=created_at,
    )


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_published_manifest_validates_and_hashes_allow_listed_artifacts(tmp_path):
    with publisher(tmp_path, "SYNTHETIC-RUN-READY") as run:
        run.write_qa_report(
            {"project_id": "SYNTHETIC-RUNTIME", "findings": []}
        )
        final_path = run.publish()

    manifest_path = final_path / "run-manifest.json"
    manifest = load_json(manifest_path)
    schema = load_json(
        ROOT / "skills" / "_shared" / "schemas" / "run-manifest.schema.json"
    )
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    ).validate(manifest)

    assert [artifact["path"] for artifact in manifest["artifacts"]] == [
        "qa-report.json"
    ]
    artifact = manifest["artifacts"][0]
    assert artifact["sha256"] == sha256_file(final_path / artifact["path"])
    assert manifest["semantic_hash"] == sha256_bytes(
        canonical_json_bytes(semantic_manifest_projection(manifest))
    )


def test_ready_then_blocked_runs_publish_isolated_and_latest_points_to_blocked(tmp_path):
    with publisher(tmp_path, "SYNTHETIC-RUN-READY") as ready:
        ready.write_qa_report({"outcome": "ready"})
        ready_path = ready.publish()

    with publisher(
        tmp_path,
        "SYNTHETIC-RUN-BLOCKED",
        outcome="blocked",
        status="draft",
    ) as blocked:
        blocked.write_qa_report(
            {"outcome": "blocked", "errors": ["synthetic blocker"]}
        )
        blocked_path = blocked.publish()

    pointer = load_json(tmp_path / "latest-run.json")
    assert ready_path.exists()
    assert blocked_path.exists()
    assert ready_path != blocked_path
    assert pointer["run_id"] == "SYNTHETIC-RUN-BLOCKED"
    assert pointer["run_directory"] == "runs/SYNTHETIC-RUN-BLOCKED"
    assert pointer["manifest_sha256"] == sha256_file(
        blocked_path / "run-manifest.json"
    )
    assert load_json(ready_path / "qa-report.json")["outcome"] == "ready"
    assert load_json(blocked_path / "qa-report.json")["outcome"] == "blocked"


def test_semantic_hash_excludes_volatile_run_identity(tmp_path):
    semantic_hashes = []
    runs = (
        ("SYNTHETIC-RUN-A", "2026-07-28T12:00:00Z"),
        ("SYNTHETIC-RUN-B", "2026-07-28T12:01:00Z"),
    )
    for run_id, created_at in runs:
        with publisher(tmp_path, run_id, created_at=created_at) as run:
            run.write_qa_report({"project_id": "SYNTHETIC-RUNTIME"})
            final_path = run.publish()
        semantic_hashes.append(load_json(final_path / "run-manifest.json")["semantic_hash"])

    assert semantic_hashes[0] == semantic_hashes[1]


def test_publication_rejects_unregistered_and_unsafe_artifacts(tmp_path):
    with publisher(tmp_path, "SYNTHETIC-RUN-UNREGISTERED") as run:
        run.write_qa_report({"findings": []})
        run.path_for("unregistered.txt").write_text("synthetic", encoding="utf-8")
        with pytest.raises(ManifestError, match="allow-list mismatch"):
            run.publish()

    with publisher(tmp_path, "SYNTHETIC-RUN-TRAVERSAL") as run:
        with pytest.raises(ManifestError, match="unsafe"):
            run.write_bytes(
                "../outside.txt", b"synthetic", readiness="diagnostic"
            )


def test_ready_publication_requires_qa_report(tmp_path):
    with publisher(tmp_path, "SYNTHETIC-RUN-NO-QA") as run:
        with pytest.raises(ManifestError, match="require qa-report.json"):
            run.publish()


def test_pointer_update_failure_rolls_back_run_and_preserves_prior_pointer(
    tmp_path, monkeypatch
):
    with publisher(tmp_path, "SYNTHETIC-RUN-PRIOR") as prior:
        prior.write_qa_report({"outcome": "ready"})
        prior.publish()
    pointer_before = (tmp_path / "latest-run.json").read_bytes()

    original_replace = os.replace

    def fail_latest_pointer(source, destination):
        if Path(destination).name == "latest-run.json":
            raise OSError("synthetic pointer failure")
        return original_replace(source, destination)

    monkeypatch.setattr(run_manifest.os, "replace", fail_latest_pointer)
    failed = publisher(tmp_path, "SYNTHETIC-RUN-POINTER-FAIL")
    with failed:
        failed.write_qa_report({"outcome": "ready"})
        with pytest.raises(ManifestError, match="unpublished run was rolled back"):
            failed.publish()

    assert not failed.final_path.exists()
    assert (tmp_path / "latest-run.json").read_bytes() == pointer_before
    assert json.loads(pointer_before)["run_id"] == "SYNTHETIC-RUN-PRIOR"
