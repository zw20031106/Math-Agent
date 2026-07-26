from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from mathforge.model_identity import EXACT_INTERN_MODEL


EVIDENCE_REGISTRY_SCHEMA_VERSION = "1.0"
EVIDENCE_REGISTRY_POLICY = "explicit-allow"
TREE_FINGERPRINT_ALGORITHM = "sha256-utf8-filehash-lines-v1"

_HASH = re.compile(r"[0-9a-f]{64}")
_CLASSIFICATIONS = frozenset(
    {"eligible-baseline", "historical-ineligible", "diagnostic-only"}
)
_MANIFEST_STATUSES = frozenset(
    {"absent", "running", "completed", "degraded", "aborted", "failed"}
)
_OUTPUT_CONTRACTS = frozenset(
    {"legacy-id-final-trace", "public-id-status-final-trace"}
)
_REGISTRY_FIELDS = frozenset(
    {
        "schema_version",
        "policy",
        "review_date",
        "baseline_candidate_git_commit",
        "baseline_candidate_config_sha256",
        "dataset_sha256",
        "tree_fingerprint_algorithm",
        "active_baseline_id",
        "entries",
    }
)
_ENTRY_FIELDS = frozenset(
    {
        "id",
        "relative_path",
        "classification",
        "eligible_for_baseline",
        "reasons",
        "file_count",
        "tree_sha256",
        "dataset_sha256",
        "config_sha256",
        "git_commit",
        "requested_model",
        "response_model_observable",
        "trace_schema",
        "output_contract",
        "manifest_status",
    }
)


def load_evidence_registry(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("evidence registry must be an object")
    return payload


def validate_evidence_registry(registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = sorted(_REGISTRY_FIELDS - set(registry))
    extra = sorted(set(registry) - _REGISTRY_FIELDS)
    if missing:
        errors.append(f"evidence registry fields are missing: {missing}")
    if extra:
        errors.append(f"evidence registry fields are unknown: {extra}")
    if missing:
        return errors

    if registry["schema_version"] != EVIDENCE_REGISTRY_SCHEMA_VERSION:
        errors.append("evidence registry schema version is unsupported")
    if registry["policy"] != EVIDENCE_REGISTRY_POLICY:
        errors.append("evidence registry policy must be explicit-allow")
    if registry["tree_fingerprint_algorithm"] != TREE_FINGERPRINT_ALGORITHM:
        errors.append("evidence registry tree fingerprint algorithm is unsupported")
    for field in ("baseline_candidate_config_sha256", "dataset_sha256"):
        if not _is_hash(registry[field]):
            errors.append(f"evidence registry {field} is invalid")
    if not _nonempty_string(registry["baseline_candidate_git_commit"]):
        errors.append("evidence registry baseline_candidate_git_commit is invalid")

    entries = registry["entries"]
    if not isinstance(entries, list):
        errors.append("evidence registry entries must be a list")
        return errors

    identifiers: set[str] = set()
    eligible_ids: set[str] = set()
    for index, entry in enumerate(entries):
        prefix = f"evidence registry entry {index}"
        if not isinstance(entry, dict):
            errors.append(f"{prefix} must be an object")
            continue
        entry_missing = sorted(_ENTRY_FIELDS - set(entry))
        entry_extra = sorted(set(entry) - _ENTRY_FIELDS)
        if entry_missing:
            errors.append(f"{prefix} fields are missing: {entry_missing}")
        if entry_extra:
            errors.append(f"{prefix} fields are unknown: {entry_extra}")
        if entry_missing:
            continue

        identifier = entry["id"]
        if not _nonempty_string(identifier):
            errors.append(f"{prefix} id is invalid")
        elif identifier in identifiers:
            errors.append(f"{prefix} id is duplicated")
        else:
            identifiers.add(identifier)

        if not _is_safe_relative_path(entry["relative_path"]):
            errors.append(f"{prefix} relative_path is invalid")
        classification = entry["classification"]
        if classification not in _CLASSIFICATIONS:
            errors.append(f"{prefix} classification is invalid")
        eligible = entry["eligible_for_baseline"]
        if type(eligible) is not bool:
            errors.append(f"{prefix} eligible_for_baseline must be boolean")
        elif eligible != (classification == "eligible-baseline"):
            errors.append(f"{prefix} eligibility conflicts with classification")
        elif eligible and isinstance(identifier, str):
            eligible_ids.add(identifier)

        reasons = entry["reasons"]
        if not isinstance(reasons, list) or any(
            not _nonempty_string(reason) for reason in reasons
        ):
            errors.append(f"{prefix} reasons must be a list of non-empty strings")
        elif eligible and reasons:
            errors.append(f"{prefix} eligible evidence must not have rejection reasons")
        elif not eligible and not reasons:
            errors.append(f"{prefix} ineligible evidence requires rejection reasons")

        if type(entry["file_count"]) is not int or entry["file_count"] < 1:
            errors.append(f"{prefix} file_count is invalid")
        for field in ("tree_sha256", "dataset_sha256"):
            if not _is_hash(entry[field]):
                errors.append(f"{prefix} {field} is invalid")
        if entry["dataset_sha256"] != registry["dataset_sha256"]:
            errors.append(f"{prefix} dataset_sha256 does not match the registry")
        if entry["config_sha256"] is not None and not _is_hash(
            entry["config_sha256"]
        ):
            errors.append(f"{prefix} config_sha256 is invalid")
        if not _nonempty_string(entry["git_commit"]):
            errors.append(f"{prefix} git_commit is invalid")
        if not _nonempty_string(entry["requested_model"]):
            errors.append(f"{prefix} requested_model is invalid")
        if type(entry["response_model_observable"]) is not bool:
            errors.append(f"{prefix} response_model_observable must be boolean")
        if not _nonempty_string(entry["trace_schema"]):
            errors.append(f"{prefix} trace_schema is invalid")
        if entry["output_contract"] not in _OUTPUT_CONTRACTS:
            errors.append(f"{prefix} output_contract is invalid")
        if entry["manifest_status"] not in _MANIFEST_STATUSES:
            errors.append(f"{prefix} manifest_status is invalid")

        if eligible:
            if entry["requested_model"] != EXACT_INTERN_MODEL:
                errors.append(f"{prefix} eligible evidence uses the wrong model")
            if entry["manifest_status"] != "completed":
                errors.append(f"{prefix} eligible evidence is not completed")
            if entry["output_contract"] != "public-id-status-final-trace":
                errors.append(f"{prefix} eligible evidence uses a legacy output contract")
            if entry["git_commit"] != registry["baseline_candidate_git_commit"]:
                errors.append(f"{prefix} eligible evidence uses a different commit")
            if entry["config_sha256"] != registry["baseline_candidate_config_sha256"]:
                errors.append(f"{prefix} eligible evidence uses a different config")

    active = registry["active_baseline_id"]
    if active is not None and active not in eligible_ids:
        errors.append("active_baseline_id must reference eligible evidence")
    if active is None and eligible_ids:
        errors.append("eligible evidence exists without an active_baseline_id")
    if active is not None and eligible_ids != {active}:
        errors.append("exactly one eligible evidence set must be active")
    return errors


def evidence_tree_fingerprint(root: Path) -> tuple[int, str]:
    if not root.is_dir():
        raise ValueError("evidence root must be an existing directory")
    lines = []
    for path in sorted(
        (item for item in root.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(root).as_posix(),
    ):
        relative = path.relative_to(root).as_posix()
        lines.append(f"{relative}\t{sha256(path.read_bytes()).hexdigest()}")
    payload = (("\n".join(lines) + "\n") if lines else "").encode("utf-8")
    return len(lines), sha256(payload).hexdigest()


def validate_registered_trees(
    registry: dict[str, Any],
    results_root: Path,
) -> list[str]:
    errors: list[str] = []
    for entry in registry.get("entries", []):
        if not isinstance(entry, dict) or not _is_safe_relative_path(
            entry.get("relative_path")
        ):
            continue
        root = results_root.joinpath(*PurePosixPath(entry["relative_path"]).parts)
        try:
            file_count, fingerprint = evidence_tree_fingerprint(root)
        except (OSError, ValueError):
            errors.append(f"registered evidence tree is unavailable: {entry.get('id', '')}")
            continue
        if file_count != entry.get("file_count"):
            errors.append(f"registered evidence file count mismatch: {entry.get('id', '')}")
        if fingerprint != entry.get("tree_sha256"):
            errors.append(f"registered evidence fingerprint mismatch: {entry.get('id', '')}")
    return errors


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and _HASH.fullmatch(value) is not None


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_safe_relative_path(value: Any) -> bool:
    if not _nonempty_string(value):
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and "\\" not in value
        and ":" not in value
    )
