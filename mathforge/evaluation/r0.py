"""Phase R0 evidence contracts.

R0 is deliberately an evidence-only phase.  It records the executable
identity of the current candidate, keeps historical official aggregates
separate from current evidence, and only declares a current baseline complete
when the required repeated artifacts are present and comparable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import platform
import subprocess
from typing import Any, Mapping, Sequence

from mathforge.config import HarnessConfig
from mathforge.agents.registry import PromptContractLoader
from mathforge.evaluation.artifacts import COMPETITION_TIMING_PROFILE
from mathforge.harness.context_budget import (
    InternS2TokenCounter,
    tokenizer_provenance,
)
from mathforge.harness.fingerprints import content_tree_fingerprint, semantic_fingerprint
from mathforge.model_identity import EXACT_INTERN_MODEL, ModelIdentity, exact_model_identity
from mathforge.skills.registry import SkillRegistry


R0_SCHEMA_VERSION = "1.0"
CURRENT_IDENTITY_SCHEMA_VERSION = R0_SCHEMA_VERSION
HISTORICAL_REFERENCE_SCHEMA_VERSION = R0_SCHEMA_VERSION
CURRENT_BASELINE_SCHEMA_VERSION = R0_SCHEMA_VERSION
R0_MIN_REPETITIONS = 3
# Keep the algorithm identifier descriptive but compact so the repository
# secret scanner does not confuse it with an opaque credential.
SOURCE_TREE_FINGERPRINT_ALGORITHM = "sha256-source-v1"
_HASH = set("0123456789abcdef")
_TOKEN_COUNTING_MODES = frozenset({"official_tokenizer", "multilingual_estimate"})
R0_METRIC_NAMES = (
    "accuracy",
    "prompt_tokens",
    "completion_tokens",
    "truncation",
    "timeouts",
    "tails",
    "calls",
    "latency",
    "zero_candidate",
    "invalid",
)


def capture_current_candidate_identity(
    root: Path,
    *,
    config_path: Path,
    requested_model: str = EXACT_INTERN_MODEL,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Capture the reproducibility identity required by R0-T01.

    The artifact contains only public fingerprints and model/tokenizer
    metadata.  It never reads or serializes credentials.
    """

    root = root.resolve()
    config_path = config_path.resolve()
    if not config_path.is_file():
        raise FileNotFoundError(config_path)
    model_identity = exact_model_identity(
        requested_model,
        request_source="argument:--model",
    ).to_dict()
    tokenizer = tokenizer_provenance()
    counter = InternS2TokenCounter()
    payload: dict[str, Any] = {
        "schema_version": CURRENT_IDENTITY_SCHEMA_VERSION,
        "phase": "R0-T01",
        "captured_at": captured_at or datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_value(root, "rev-parse", "HEAD") or "unavailable",
        "code_dirty": _git_dirty(root),
        "tree_sha256": source_tree_fingerprint(root),
        "tree_fingerprint_algorithm": SOURCE_TREE_FINGERPRINT_ALGORITHM,
        "competition_config_sha256": _file_sha256(config_path),
        # ``run_benchmark`` stores the semantic HarnessConfig fingerprint,
        # whereas the raw file hash is useful for provenance.  Keep both so
        # a real benchmark artifact can be compared without weakening the
        # exact-file identity contract.
        "competition_config_fingerprint": _config_fingerprint(config_path),
        "prompt_tree_sha256": content_tree_fingerprint(root / "prompts", "*.md"),
        "skill_tree_sha256": _skill_tree_fingerprint(root),
        "prompt_fingerprint": PromptContractLoader().fingerprint,
        "skill_fingerprint": SkillRegistry().fingerprint,
        "model_identity": model_identity,
        "token_counting_mode": (
            "official_tokenizer" if counter.exact_available else "multilingual_estimate"
        ),
        "tokenizer_provenance": tokenizer,
        "python": f"{platform.python_implementation()} {platform.python_version()}",
        "platform": platform.platform(),
    }
    errors = validate_current_candidate_identity(payload)
    if errors:
        raise ValueError("invalid captured identity: " + "; ".join(errors))
    return payload


def validate_current_candidate_identity(payload: Mapping[str, Any]) -> list[str]:
    """Validate a current-candidate identity without requiring a clean tree."""

    required = {
        "schema_version",
        "phase",
        "captured_at",
        "git_commit",
        "code_dirty",
        "tree_sha256",
        "tree_fingerprint_algorithm",
        "competition_config_sha256",
        "competition_config_fingerprint",
        "prompt_tree_sha256",
        "skill_tree_sha256",
        "model_identity",
        "token_counting_mode",
        "tokenizer_provenance",
        "python",
        "platform",
    }
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return ["current candidate identity must be an object"]
    missing = sorted(required - set(payload))
    if missing:
        errors.append(f"current candidate identity fields are missing: {missing}")
        return errors
    if payload.get("schema_version") != CURRENT_IDENTITY_SCHEMA_VERSION:
        errors.append("current candidate identity schema version is unsupported")
    if payload.get("phase") != "R0-T01":
        errors.append("current candidate identity phase is invalid")
    for field in (
        "tree_sha256",
        "competition_config_sha256",
        "competition_config_fingerprint",
        "prompt_tree_sha256",
        "skill_tree_sha256",
    ):
        if not _is_sha256(payload.get(field)):
            errors.append(f"current candidate identity {field} is invalid")
    for field in ("prompt_fingerprint", "skill_fingerprint"):
        if field in payload and not _is_sha256(payload.get(field)):
            errors.append(f"current candidate identity {field} is invalid")
    if payload.get("tree_fingerprint_algorithm") != SOURCE_TREE_FINGERPRINT_ALGORITHM:
        errors.append("current candidate identity tree algorithm is invalid")
    commit = payload.get("git_commit")
    if not isinstance(commit, str) or not commit.strip():
        errors.append("current candidate identity git_commit is invalid")
    elif commit != "unavailable" and not _is_hex_commit(commit):
        errors.append("current candidate identity git_commit is invalid")
    if payload.get("code_dirty") is not None and type(payload.get("code_dirty")) is not bool:
        errors.append("current candidate identity code_dirty is invalid")
    try:
        identity = ModelIdentity.from_dict(dict(payload["model_identity"]))
    except (TypeError, ValueError):
        errors.append("current candidate identity model_identity is invalid")
    else:
        if identity.requested_model != EXACT_INTERN_MODEL:
            errors.append("current candidate identity uses the wrong model")
        if identity.request_source != "argument:--model":
            errors.append("current candidate identity model source is invalid")
    if payload.get("token_counting_mode") not in _TOKEN_COUNTING_MODES:
        errors.append("current candidate identity token_counting_mode is invalid")
    tokenizer = payload.get("tokenizer_provenance")
    if not isinstance(tokenizer, Mapping):
        errors.append("current candidate identity tokenizer provenance is invalid")
    else:
        for field in (
            "repository",
            "revision",
            "fallback_version",
        ):
            if not isinstance(tokenizer.get(field), str) or not tokenizer.get(field):
                errors.append(f"current candidate identity tokenizer {field} is invalid")
        for field in (
            "tokenizer_json_sha256",
            "tokenizer_config_sha256",
            "chat_template_sha256",
            "fallback_sha256",
        ):
            if not _is_sha256(tokenizer.get(field)):
                errors.append(f"current candidate identity tokenizer {field} is invalid")
    for field in ("captured_at", "python", "platform"):
        if not isinstance(payload.get(field), str) or not payload.get(field).strip():
            errors.append(f"current candidate identity {field} is invalid")
    return sorted(set(errors))


def source_tree_fingerprint(root: Path) -> str:
    """Hash the source files that determine runtime behavior."""

    root = root.resolve()
    paths: set[Path] = set()
    for relative in ("main.py", "llm_client.py", "user_agent.py"):
        path = root / relative
        if path.is_file():
            paths.add(path)
    for directory in (root / "mathforge", root / "scripts"):
        if directory.is_dir():
            paths.update(path for path in directory.rglob("*.py") if path.is_file())
    digest = sha256()
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes().replace(b"\r\n", b"\n")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def build_historical_reference_registry(
    references: Sequence[Mapping[str, Any]],
    *,
    dataset_sha256: str,
    source_document: str,
    source_sha256: str,
) -> dict[str, Any]:
    """Build an explicit historical-only registration for R0-T02."""

    payload = {
        "schema_version": HISTORICAL_REFERENCE_SCHEMA_VERSION,
        "phase": "R0-T02",
        "status": "historical-only",
        "dataset_sha256": dataset_sha256,
        "source": {
            "kind": "plan-aggregate",
            "document": source_document,
            "sha256": source_sha256,
        },
        "references": [dict(item) for item in references],
        "active_baseline_id": None,
        "privacy": {
            "contains_credentials": False,
            "contains_absolute_paths": False,
            "contains_private_reasoning_transcripts": False,
        },
    }
    errors = validate_historical_reference_registry(payload)
    if errors:
        raise ValueError("invalid historical reference registry: " + "; ".join(errors))
    return payload


def validate_historical_reference_registry(payload: Mapping[str, Any]) -> list[str]:
    required = {
        "schema_version",
        "phase",
        "status",
        "dataset_sha256",
        "source",
        "references",
        "active_baseline_id",
        "privacy",
    }
    if not isinstance(payload, Mapping):
        return ["historical reference registry must be an object"]
    errors: list[str] = []
    missing = sorted(required - set(payload))
    if missing:
        errors.append(f"historical reference fields are missing: {missing}")
        return errors
    if payload.get("schema_version") != HISTORICAL_REFERENCE_SCHEMA_VERSION:
        errors.append("historical reference schema version is unsupported")
    if payload.get("phase") != "R0-T02":
        errors.append("historical reference phase is invalid")
    if payload.get("status") != "historical-only":
        errors.append("historical reference status must be historical-only")
    if not _is_sha256(payload.get("dataset_sha256")):
        errors.append("historical reference dataset_sha256 is invalid")
    source = payload.get("source")
    if not isinstance(source, Mapping):
        errors.append("historical reference source is invalid")
    else:
        if source.get("kind") != "plan-aggregate":
            errors.append("historical reference source kind is invalid")
        if not isinstance(source.get("document"), str) or not source.get("document"):
            errors.append("historical reference source document is invalid")
        if not _is_sha256(source.get("sha256")):
            errors.append("historical reference source sha256 is invalid")
    references = payload.get("references")
    if not isinstance(references, list) or not references:
        errors.append("historical references must be a non-empty list")
    else:
        seen: set[str] = set()
        for index, reference in enumerate(references):
            prefix = f"historical reference {index}"
            if not isinstance(reference, Mapping):
                errors.append(f"{prefix} must be an object")
                continue
            identifier = reference.get("id")
            if not isinstance(identifier, str) or not identifier.strip() or identifier in seen:
                errors.append(f"{prefix} id is invalid or duplicated")
            seen.add(str(identifier))
            if reference.get("status") != "historical_official_reference":
                errors.append(f"{prefix} status must be historical_official_reference")
            if reference.get("eligible_for_baseline") is not False:
                errors.append(f"{prefix} must not be eligible for baseline")
            if not isinstance(reference.get("date"), str) or not reference.get("date"):
                errors.append(f"{prefix} date is invalid")
            metrics = reference.get("metrics")
            if not isinstance(metrics, Mapping):
                errors.append(f"{prefix} metrics are invalid")
            else:
                if metrics.get("case_count") != 112:
                    errors.append(f"{prefix} case_count must be 112")
                accuracy = metrics.get("accuracy")
                if not isinstance(accuracy, (int, float)) or not 0 <= accuracy <= 1:
                    errors.append(f"{prefix} accuracy is invalid")
            reasons = reference.get("reasons")
            if not isinstance(reasons, list) or not reasons or any(
                not isinstance(reason, str) or not reason.strip() for reason in reasons
            ):
                errors.append(f"{prefix} reasons must be non-empty strings")
    if payload.get("active_baseline_id") is not None:
        errors.append("historical reference registry cannot activate a baseline")
    return sorted(set(errors))


def build_current_head_baseline(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    identity: Mapping[str, Any],
    dataset_sha256: str,
    min_repetitions: int = R0_MIN_REPETITIONS,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Aggregate repeated benchmark artifacts without inventing missing data."""

    identity_errors = validate_current_candidate_identity(identity)
    blockers: list[str] = list(identity_errors)
    if identity.get("code_dirty") is not False:
        blockers.append(
            "current candidate identity does not describe a clean worktree"
        )
    if identity.get("git_commit") in {None, "", "unavailable"}:
        blockers.append("current candidate identity has no resolvable git commit")
    if min_repetitions < 1:
        raise ValueError("min_repetitions must be positive")
    if not _is_sha256(dataset_sha256):
        raise ValueError("dataset_sha256 is invalid")
    repetitions: list[dict[str, Any]] = []
    seen_artifact_hashes: set[str] = set()
    for index, artifact in enumerate(artifacts):
        artifact_errors = _validate_repetition_artifact(
            artifact,
            identity=identity,
            dataset_sha256=dataset_sha256,
        )
        artifact_hash = _artifact_fingerprint(artifact)
        if artifact_hash and artifact_hash in seen_artifact_hashes:
            artifact_errors.append("duplicate repetition artifact fingerprint")
        if artifact_errors:
            blockers.extend(f"repetition {index}: {error}" for error in artifact_errors)
            continue
        seen_artifact_hashes.add(artifact_hash)
        repetitions.append(
            {
                "repetition_index": index,
                "artifact_sha256": artifact_hash,
                "summary": dict(artifact.get("summary", {})),
                "metrics": _extract_r0_metrics(artifact),
            }
        )
    if len(repetitions) < min_repetitions:
        blockers.append(
            f"requires at least {min_repetitions} valid repetitions; found {len(repetitions)}"
        )
    aggregate_metrics = _aggregate_r0_metrics(repetitions)
    metric_gaps = sorted(
        {
            name
            for name, value in aggregate_metrics.items()
            if value is None
        }
        | {
            name
            for repetition in repetitions
            for name, value in repetition["metrics"].items()
            if value is None
        }
    )
    if metric_gaps:
        blockers.append("missing required baseline metrics: " + ", ".join(metric_gaps))
    status = "complete" if not blockers else "blocked"
    payload = {
        "schema_version": CURRENT_BASELINE_SCHEMA_VERSION,
        "phase": "R0-T03",
        "status": status,
        "captured_at": captured_at or datetime.now(timezone.utc).isoformat(),
        "identity": dict(identity),
        "dataset_sha256": dataset_sha256,
        "timing_profile": COMPETITION_TIMING_PROFILE,
        "required_repetitions": min_repetitions,
        "repetitions": repetitions,
        "metrics": aggregate_metrics,
        "metric_gaps": metric_gaps,
        "blockers": sorted(set(blockers)),
        "active_baseline_eligible": False,
        "activation_note": (
            "R0 records a current candidate baseline; active registration is deferred "
            "until the later release gate."
        ),
    }
    errors = validate_current_head_baseline(payload)
    if errors:
        raise ValueError("invalid current baseline: " + "; ".join(errors))
    return payload


def validate_current_head_baseline(payload: Mapping[str, Any]) -> list[str]:
    required = {
        "schema_version",
        "phase",
        "status",
        "captured_at",
        "identity",
        "dataset_sha256",
        "timing_profile",
        "required_repetitions",
        "repetitions",
        "metrics",
        "metric_gaps",
        "blockers",
        "active_baseline_eligible",
        "activation_note",
    }
    if not isinstance(payload, Mapping):
        return ["current baseline must be an object"]
    errors: list[str] = []
    missing = sorted(required - set(payload))
    if missing:
        errors.append(f"current baseline fields are missing: {missing}")
        return errors
    if payload.get("schema_version") != CURRENT_BASELINE_SCHEMA_VERSION:
        errors.append("current baseline schema version is unsupported")
    if payload.get("phase") != "R0-T03":
        errors.append("current baseline phase is invalid")
    status = payload.get("status")
    if status not in {"blocked", "complete"}:
        errors.append("current baseline status is invalid")
    errors.extend(validate_current_candidate_identity(payload.get("identity", {})))
    if not _is_sha256(payload.get("dataset_sha256")):
        errors.append("current baseline dataset_sha256 is invalid")
    if payload.get("timing_profile") != COMPETITION_TIMING_PROFILE:
        errors.append("current baseline timing profile is not competition")
    required_repetitions = payload.get("required_repetitions")
    if type(required_repetitions) is not int or required_repetitions < 1:
        errors.append("current baseline required_repetitions is invalid")
    repetitions = payload.get("repetitions")
    if not isinstance(repetitions, list):
        errors.append("current baseline repetitions must be a list")
        repetitions = []
    else:
        seen_indexes: set[int] = set()
        seen_hashes: set[str] = set()
        for index, repetition in enumerate(repetitions):
            if not isinstance(repetition, Mapping):
                errors.append(f"current baseline repetition {index} must be an object")
                continue
            repetition_index = repetition.get("repetition_index")
            if type(repetition_index) is not int or repetition_index < 0:
                errors.append(f"current baseline repetition {index} index is invalid")
            elif repetition_index in seen_indexes:
                errors.append(f"current baseline repetition {index} index is duplicated")
            else:
                seen_indexes.add(repetition_index)
            artifact_hash = repetition.get("artifact_sha256")
            if not _is_sha256(artifact_hash):
                errors.append(f"current baseline repetition {index} artifact hash is invalid")
            elif artifact_hash in seen_hashes:
                errors.append(f"current baseline repetition {index} artifact hash is duplicated")
            else:
                seen_hashes.add(artifact_hash)
            if not isinstance(repetition.get("summary"), Mapping):
                errors.append(f"current baseline repetition {index} summary is invalid")
            repetition_metrics = repetition.get("metrics")
            if not isinstance(repetition_metrics, Mapping):
                errors.append(f"current baseline repetition {index} metrics are invalid")
            elif set(repetition_metrics) != set(R0_METRIC_NAMES):
                errors.append(f"current baseline repetition {index} metric fields are invalid")
    metrics = payload.get("metrics")
    if not isinstance(metrics, Mapping) or set(metrics) != set(R0_METRIC_NAMES):
        errors.append("current baseline metrics are invalid")
    metric_gaps = payload.get("metric_gaps")
    if not isinstance(metric_gaps, list) or any(
        item not in R0_METRIC_NAMES for item in metric_gaps
    ):
        errors.append("current baseline metric_gaps are invalid")
    elif isinstance(metrics, Mapping):
        expected_gaps = sorted(
            name for name in R0_METRIC_NAMES if metrics.get(name) is None
        )
        if metric_gaps != expected_gaps:
            errors.append("current baseline metric_gaps do not match metrics")
    if status == "complete" and (
        errors or len(repetitions) < int(required_repetitions or 1)
    ):
        errors.append("complete current baseline does not satisfy repetition gate")
    if status == "complete" and payload.get("identity", {}).get("code_dirty") is not False:
        errors.append("complete current baseline requires a clean worktree")
    if status == "complete" and payload.get("identity", {}).get("git_commit") in {
        None,
        "",
        "unavailable",
    }:
        errors.append("complete current baseline requires a resolvable git commit")
    blockers = payload.get("blockers")
    if not isinstance(blockers, list) or any(
        not isinstance(item, str) or not item.strip() for item in blockers
    ):
        errors.append("current baseline blockers must be strings")
    elif status == "blocked" and not blockers:
        errors.append("blocked current baseline must declare blockers")
    elif status == "complete" and blockers:
        errors.append("complete current baseline cannot declare blockers")
    if payload.get("active_baseline_eligible") is not False:
        errors.append("R0 current baseline must not activate the release baseline")
    return sorted(set(errors))


def _validate_repetition_artifact(
    artifact: Mapping[str, Any],
    *,
    identity: Mapping[str, Any],
    dataset_sha256: str,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(artifact, Mapping):
        return ["artifact must be an object"]
    if artifact.get("dataset_sha256") != dataset_sha256:
        errors.append("dataset hash does not match identity")
    accepted_config_hashes = {
        identity.get("competition_config_sha256"),
        identity.get("competition_config_fingerprint"),
    }
    if artifact.get("config_sha256") not in accepted_config_hashes:
        errors.append("config hash does not match identity")
    if artifact.get("git_commit") != identity.get("git_commit"):
        errors.append("artifact commit does not match identity")
    if artifact.get("timing_profile") != COMPETITION_TIMING_PROFILE:
        errors.append("artifact timing profile is not competition")
    if "code_dirty" in artifact and artifact.get("code_dirty") != identity.get(
        "code_dirty"
    ):
        errors.append("artifact dirty state does not match identity")
    artifact_identity = artifact.get("run_identity")
    if isinstance(artifact_identity, Mapping):
        if artifact_identity.get("commit_sha") != identity.get("git_commit"):
            errors.append("commit does not match identity")
        if artifact_identity.get("competition_config_sha") != identity.get(
            "competition_config_fingerprint"
        ):
            errors.append("run identity config does not match identity")
        if artifact_identity.get("dataset_sha") != dataset_sha256:
            errors.append("run identity dataset does not match identity")
        if artifact_identity.get("model_identity") != identity.get("model_identity"):
            errors.append("run identity model does not match identity")
        if artifact_identity.get("prompt_fingerprint") != identity.get(
            "prompt_fingerprint",
            identity.get("prompt_tree_sha256"),
        ):
            errors.append("run identity prompt does not match identity")
        if artifact_identity.get("skill_fingerprint") != identity.get(
            "skill_fingerprint",
            identity.get("skill_tree_sha256"),
        ):
            errors.append("run identity skill does not match identity")
    else:
        errors.append("artifact run_identity is missing")
    if not isinstance(artifact.get("summary"), Mapping):
        errors.append("artifact summary is missing")
    elif artifact["summary"].get("case_count") != 112:
        errors.append("artifact summary case_count must be 112")
    declared_hash = artifact.get("artifact_sha256")
    if declared_hash is not None:
        if not _is_sha256(declared_hash):
            errors.append("artifact_sha256 is invalid")
        else:
            unsigned = dict(artifact)
            unsigned.pop("artifact_sha256", None)
            if semantic_fingerprint(unsigned) != declared_hash:
                errors.append("artifact_sha256 mismatch")
    return errors


def _artifact_fingerprint(artifact: Any) -> str:
    if not isinstance(artifact, Mapping):
        return ""
    declared = artifact.get("artifact_sha256")
    if isinstance(declared, str) and _is_sha256(declared):
        return declared
    # Summary-only diagnostic artifacts do not always carry the standard
    # artifact_sha256 field.  Exclude the caller-assigned repetition label so
    # copying one run under three labels cannot satisfy the repetition gate.
    unsigned = {
        key: value
        for key, value in artifact.items()
        if key not in {"artifact_sha256", "repetition_index"}
    }
    return semantic_fingerprint(unsigned)


def _extract_r0_metrics(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the metric names required by R0 without inventing values."""

    summary = artifact.get("summary")
    summary = summary if isinstance(summary, Mapping) else {}
    records = artifact.get("records")
    records = records if isinstance(records, list) else []
    metrics: dict[str, Any] = {
        "accuracy": _first_value(summary, "accuracy"),
        "prompt_tokens": _first_value(
            summary, "prompt_tokens", "average_prompt_tokens"
        ),
        "completion_tokens": _first_value(
            summary,
            "completion_tokens",
            "average_completion_tokens",
            "average_observed_output_tokens",
        ),
        "truncation": _first_value(
            summary, "truncation", "truncation_rate", "truncated_count"
        ),
        "timeouts": _first_value(
            summary,
            "timeouts",
            "timeout_rate",
            "model_call_timeout_count",
        ),
        "tails": _first_value(
            summary, "tails", "tail_count", "background_tail_started"
        ),
        "calls": _first_value(
            summary,
            "calls",
            "logical_calls",
            "average_model_calls",
            "model_calls",
        ),
        "latency": _latency_value(summary),
        "zero_candidate": _first_value(
            summary, "zero_candidate", "zero_candidate_rate"
        ),
        "invalid": _first_value(
            summary, "invalid", "invalid_rate", "json_failure_rate"
        ),
    }
    run_metrics = [
        item.get("run_metrics")
        for item in records
        if isinstance(item, Mapping) and isinstance(item.get("run_metrics"), Mapping)
    ]
    if metrics["prompt_tokens"] is None and run_metrics:
        metrics["prompt_tokens"] = _mean(
            item.get("prompt_tokens") for item in run_metrics
        )
    if metrics["completion_tokens"] is None and run_metrics:
        metrics["completion_tokens"] = _mean(
            item.get("observed_output_tokens") for item in run_metrics
        )
    if metrics["calls"] is None and run_metrics:
        metrics["calls"] = _mean(item.get("model_calls") for item in run_metrics)
    if metrics["timeouts"] is None and run_metrics:
        metrics["timeouts"] = _sum(
            item.get("model_call_timeout_count") for item in run_metrics
        )
    if metrics["tails"] is None and run_metrics:
        metrics["tails"] = _sum(
            item.get("background_tail_started") for item in run_metrics
        )
    if metrics["zero_candidate"] is None:
        metrics["zero_candidate"] = _derived_zero_candidate(summary)
    if metrics["invalid"] is None:
        metrics["invalid"] = _first_value(summary, "invalid_expected_count")
    if metrics["truncation"] is None:
        metrics["truncation"] = _derived_truncation(records)
    return metrics


def _aggregate_r0_metrics(repetitions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    aggregate: dict[str, Any] = {}
    for name in R0_METRIC_NAMES:
        values = [
            repetition.get("metrics", {}).get(name)
            for repetition in repetitions
            if isinstance(repetition.get("metrics"), Mapping)
        ]
        values = [value for value in values if value is not None]
        aggregate[name] = _mean(values) if values and name != "latency" else (
            _aggregate_latency(values) if values else None
        )
    return aggregate


def _aggregate_latency(values: Sequence[Any]) -> dict[str, float] | None:
    mappings = [value for value in values if isinstance(value, Mapping)]
    if mappings:
        result: dict[str, float] = {}
        for key in ("p50_seconds", "p95_seconds"):
            numbers = [item.get(key) for item in mappings if _number(item.get(key))]
            if numbers:
                result[key] = float(sum(numbers) / len(numbers))
        return result or None
    numeric = [value for value in values if _number(value)]
    return {"mean_seconds": float(sum(numeric) / len(numeric))} if numeric else None


def _latency_value(summary: Mapping[str, Any]) -> Any:
    if _number(summary.get("latency")):
        return float(summary["latency"])
    result = {
        normalized: float(summary[source])
        for normalized, source in (
            ("p50_seconds", "latency_p50_seconds"),
            ("p95_seconds", "latency_p95_seconds"),
        )
        if _number(summary.get(source))
    }
    return result or None


def _derived_zero_candidate(summary: Mapping[str, Any]) -> Any:
    counts = summary.get("error_code_counts")
    case_count = summary.get("case_count")
    if isinstance(counts, Mapping) and _number(case_count) and case_count:
        count = counts.get("all_candidates_failed")
        if _number(count):
            return float(count) / float(case_count)
    return None


def _derived_truncation(records: Sequence[Any]) -> Any:
    assessed = 0
    truncated = 0
    for record in records:
        if not isinstance(record, Mapping):
            continue
        result = record.get("result")
        trace = result.get("trace") if isinstance(result, Mapping) else None
        if not isinstance(trace, list):
            continue
        for event in trace:
            if not isinstance(event, Mapping) or event.get("event") != "truncation_assessed":
                continue
            assessed += 1
            status = str(event.get("status", "")).upper()
            if (
                event.get("truncated") is True
                or status == "TRUNCATED"
                or "TRUNCATION" in status
            ):
                truncated += 1
    return float(truncated) / assessed if assessed else None


def _first_value(mapping: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = mapping.get(name)
        if value is not None:
            return value
    return None


def _mean(values: Any) -> float | None:
    numeric = [float(value) for value in values if _number(value)]
    return sum(numeric) / len(numeric) if numeric else None


def _sum(values: Any) -> float | None:
    numeric = [float(value) for value in values if _number(value)]
    return sum(numeric) if numeric else None


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _skill_tree_fingerprint(root: Path) -> str:
    legacy = content_tree_fingerprint(root / "skills", "*.md")
    packages = content_tree_fingerprint(root / "mathforge" / "skills" / "packages", "SKILL.md")
    return semantic_fingerprint({"legacy": legacy, "packages": packages})


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _config_fingerprint(path: Path) -> str:
    """Return the semantic fingerprint used by benchmark run identities."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return HarnessConfig.from_dict(payload).fingerprint
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        pass
    # A malformed config is still represented deterministically in the
    # identity artifact; benchmark execution will reject it separately.
    return semantic_fingerprint({"raw_config_sha256": _file_sha256(path)})


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HASH


def _is_hex_commit(value: str) -> bool:
    return 40 <= len(value) <= 64 and set(value) <= _HASH


def _git_value(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def _git_dirty(root: Path) -> bool | None:
    result = _git_value(root, "status", "--porcelain", "--untracked-files=normal")
    if result:
        return True
    try:
        subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return False


__all__ = [
    "CURRENT_BASELINE_SCHEMA_VERSION",
    "CURRENT_IDENTITY_SCHEMA_VERSION",
    "HISTORICAL_REFERENCE_SCHEMA_VERSION",
    "R0_METRIC_NAMES",
    "R0_MIN_REPETITIONS",
    "R0_SCHEMA_VERSION",
    "SOURCE_TREE_FINGERPRINT_ALGORITHM",
    "build_current_head_baseline",
    "build_historical_reference_registry",
    "capture_current_candidate_identity",
    "source_tree_fingerprint",
    "validate_current_candidate_identity",
    "validate_current_head_baseline",
    "validate_historical_reference_registry",
]
