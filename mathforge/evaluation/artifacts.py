from __future__ import annotations

from copy import deepcopy
from typing import Any

from mathforge.harness.fingerprints import semantic_fingerprint
from mathforge.provenance import RunProvenance


_REQUIRED_FIELDS = frozenset(
    {
        "benchmark_schema_version",
        "dataset_sha256",
        "config_sha256",
        "git_commit",
        "model_identifier",
        "run_provenance",
        "summary",
        "records",
        "artifact_sha256",
    }
)


def finalize_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    artifact = deepcopy(payload)
    artifact.pop("artifact_sha256", None)
    artifact["artifact_sha256"] = semantic_fingerprint(artifact)
    return artifact


def validate_artifact(artifact: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = sorted(_REQUIRED_FIELDS - set(artifact))
    if missing:
        errors.append(f"artifact fields are missing: {missing}")
        return errors
    expected = str(artifact.get("artifact_sha256", ""))
    unsigned = deepcopy(artifact)
    unsigned.pop("artifact_sha256", None)
    if semantic_fingerprint(unsigned) != expected:
        errors.append("artifact_sha256 mismatch")
    try:
        RunProvenance.from_dict(dict(artifact["run_provenance"]))
    except (AttributeError, TypeError, ValueError):
        errors.append("artifact run provenance is invalid")
    if not isinstance(artifact.get("records"), list):
        errors.append("artifact records must be a list")
    if not isinstance(artifact.get("summary"), dict):
        errors.append("artifact summary must be an object")
    return errors
