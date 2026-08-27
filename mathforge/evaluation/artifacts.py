from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import math
import re
from typing import Any

from mathforge.harness.fingerprints import semantic_fingerprint
from mathforge.model_identity import (
    EXACT_INTERN_MODEL,
    ModelIdentity,
)
from mathforge.provenance import RunProvenance


_REQUIRED_FIELDS = frozenset(
    {
        "benchmark_schema_version",
        "dataset_sha256",
        "config_sha256",
        "git_commit",
        "code_dirty",
        "requested_model",
        "request_source",
        "response_model_observable",
        "thinking_mode_observable",
        "unobservable_reason",
        "run_provenance",
        "summary",
        "records",
        "artifact_sha256",
    }
)

# A run identity is deliberately independent from the artifact schema.  This
# lets old diagnostic artifacts remain readable while making registration of a
# new baseline fail closed when any reproducibility input is missing.
RUN_IDENTITY_FIELDS = (
    "commit_sha",
    "competition_config_sha",
    "prompt_fingerprint",
    "skill_fingerprint",
    "tool_fingerprint",
    "dataset_sha",
    "model_identity",
    "python",
    "platform",
)
_RUN_IDENTITY_FIELD_SET = frozenset(RUN_IDENTITY_FIELDS)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT_SHA = re.compile(r"[0-9a-f]{40,64}\Z")
COMPETITION_OUTER_SECONDS = 900.0
COMPETITION_TIMING_PROFILE = "competition"
DEBUG_NONCOMPARABLE_TIMING_PROFILE = "debug-noncomparable"


@dataclass(frozen=True)
class RunIdentity:
    """The immutable inputs needed to identify one benchmark run.

    ``model_identity`` remains a structured value because the injected client
    exposes observability and request-source fields in addition to the model
    name.  It is intentionally not reduced to a single model string.
    """

    commit_sha: str
    competition_config_sha: str
    prompt_fingerprint: str
    skill_fingerprint: str
    tool_fingerprint: str
    dataset_sha: str
    model_identity: dict[str, Any] | str
    python: str
    platform: str

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RunIdentity":
        if not isinstance(payload, dict) or set(payload) != _RUN_IDENTITY_FIELD_SET:
            raise ValueError("run identity fields are invalid")
        return cls(**payload)

    def validate(self) -> None:
        errors = run_identity_errors(self)
        if errors:
            raise ValueError("; ".join(errors))


# Public alias used by characterization/evidence callers that prefer the
# longer name from the E0 plan.
CurrentRunIdentity = RunIdentity


def run_identity_errors(
    identity: RunIdentity | dict[str, Any],
    *,
    code_dirty: bool | None = None,
    require_clean: bool = False,
    require_exact_model: bool = False,
) -> list[str]:
    """Return deterministic validation errors for a current-run identity."""

    if isinstance(identity, RunIdentity):
        payload = identity.to_dict()
    elif isinstance(identity, dict):
        payload = dict(identity)
    else:
        return ["run identity must be an object"]
    errors: list[str] = []
    missing = sorted(_RUN_IDENTITY_FIELD_SET - set(payload))
    extra = sorted(set(payload) - _RUN_IDENTITY_FIELD_SET)
    if missing:
        errors.append(f"run identity fields are missing: {missing}")
    if extra:
        errors.append(f"run identity fields are unknown: {extra}")
    if missing or extra:
        return errors

    if not isinstance(payload["commit_sha"], str) or not _COMMIT_SHA.fullmatch(
        payload["commit_sha"]
    ):
        errors.append("run identity commit_sha is invalid")
    for field in (
        "competition_config_sha",
        "prompt_fingerprint",
        "skill_fingerprint",
        "tool_fingerprint",
        "dataset_sha",
    ):
        value = payload[field]
        if not isinstance(value, str) or not _SHA256.fullmatch(value):
            errors.append(f"run identity {field} is invalid")
    for field in ("python", "platform"):
        value = payload[field]
        if not isinstance(value, str) or not value.strip():
            errors.append(f"run identity {field} is invalid")

    model = payload["model_identity"]
    if isinstance(model, dict):
        try:
            parsed_model = ModelIdentity.from_dict(model)
        except (TypeError, ValueError):
            errors.append("run identity model_identity is invalid")
        else:
            if require_exact_model and (
                parsed_model.requested_model != EXACT_INTERN_MODEL
                or parsed_model.request_source != "argument:--model"
            ):
                errors.append("run identity model_identity is not the exact competition model")
    elif not isinstance(model, str) or not model.strip():
        errors.append("run identity model_identity is invalid")
    elif require_exact_model and model != EXACT_INTERN_MODEL:
        errors.append("run identity model_identity is not the exact competition model")

    if code_dirty is not None and type(code_dirty) is not bool:
        errors.append("run identity code_dirty is invalid")
    if require_clean and code_dirty is not False:
        errors.append("run identity requires a clean worktree")
    return errors


def validate_current_run_identity(
    identity: RunIdentity | dict[str, Any],
    *,
    code_dirty: bool | None = None,
    require_clean: bool = False,
    require_exact_model: bool = False,
) -> list[str]:
    """Compatibility entry point for E0 tests and registry tooling."""

    return run_identity_errors(
        identity,
        code_dirty=code_dirty,
        require_clean=require_clean,
        require_exact_model=require_exact_model,
    )


def build_run_identity(
    *,
    commit_sha: str,
    competition_config_sha: str,
    prompt_fingerprint: str,
    skill_fingerprint: str,
    tool_fingerprint: str,
    dataset_sha: str,
    model_identity: dict[str, Any] | str,
    python: str,
    platform: str,
) -> RunIdentity:
    return RunIdentity(
        commit_sha=commit_sha,
        competition_config_sha=competition_config_sha,
        prompt_fingerprint=prompt_fingerprint,
        skill_fingerprint=skill_fingerprint,
        tool_fingerprint=tool_fingerprint,
        dataset_sha=dataset_sha,
        model_identity=deepcopy(model_identity),
        python=python,
        platform=platform,
    )


def timing_profile_for(config: Any) -> str:
    """Classify a run without silently treating debug timing as formal data."""

    try:
        outer_seconds = float(config.outer_platform_limit_seconds)
    except (AttributeError, TypeError, ValueError):
        return DEBUG_NONCOMPARABLE_TIMING_PROFILE
    if (
        getattr(config, "profile", None) == "competition"
        and getattr(config, "status", None) != "test"
        and math.isclose(outer_seconds, COMPETITION_OUTER_SECONDS, abs_tol=1e-9)
    ):
        return COMPETITION_TIMING_PROFILE
    return DEBUG_NONCOMPARABLE_TIMING_PROFILE


def ensure_competition_timing(config: Any) -> None:
    """Reject a misconfigured formal competition profile before model calls."""

    if (
        getattr(config, "profile", None) != "competition"
        or getattr(config, "status", None) == "test"
    ):
        return
    try:
        outer_seconds = float(config.outer_platform_limit_seconds)
    except (AttributeError, TypeError, ValueError):
        raise ValueError("competition timing profile is invalid") from None
    if not math.isclose(outer_seconds, COMPETITION_OUTER_SECONDS, abs_tol=1e-9):
        raise ValueError(
            "formal competition benchmark must use a 900-second outer limit; "
            "1200 seconds is debug-noncomparable"
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
        provenance = RunProvenance.from_dict(dict(artifact["run_provenance"]))
    except (AttributeError, TypeError, ValueError):
        errors.append("artifact run provenance is invalid")
    else:
        identity = ModelIdentity.from_dict(provenance.model_identity)
        identity_fields = identity.to_dict()
        if any(artifact.get(key) != value for key, value in identity_fields.items()):
            errors.append("artifact model identity does not match provenance")
        if artifact.get("code_dirty") != provenance.code_dirty:
            errors.append("artifact dirty state does not match provenance")
        if (
            identity.requested_model != EXACT_INTERN_MODEL
            or identity.request_source != "argument:--model"
        ):
            errors.append("artifact requested model is not the exact competition model")
    if not isinstance(artifact.get("records"), list):
        errors.append("artifact records must be a list")
    if not isinstance(artifact.get("summary"), dict):
        errors.append("artifact summary must be an object")
    run_identity = artifact.get("run_identity")
    if run_identity is not None:
        identity_errors = run_identity_errors(run_identity)
        errors.extend(identity_errors)
        if not identity_errors:
            identity_payload = (
                run_identity.to_dict()
                if isinstance(run_identity, RunIdentity)
                else dict(run_identity)
            )
            if artifact.get("dataset_sha256") != identity_payload["dataset_sha"]:
                errors.append("artifact dataset hash does not match run identity")
            for artifact_field, identity_field in (
                ("config_sha256", "competition_config_sha"),
                ("prompt_sha256", "prompt_fingerprint"),
                ("skill_sha256", "skill_fingerprint"),
                ("tool_sha256", "tool_fingerprint"),
            ):
                if artifact_field in artifact and artifact.get(artifact_field) != identity_payload[
                    identity_field
                ]:
                    errors.append(
                        f"artifact {artifact_field} does not match run identity"
                    )
            provenance_payload = artifact.get("run_provenance")
            if isinstance(provenance_payload, dict) and (
                identity_payload["commit_sha"]
                != provenance_payload.get("code_commit")
            ):
                errors.append("artifact commit does not match run identity")
    return errors


def validate_baseline_artifact(artifact: dict[str, Any]) -> list[str]:
    """Validate the stricter E0 contract required for baseline registration.

    Historical artifacts continue to use :func:`validate_artifact`; callers
    must opt into this function when they intend to activate a baseline.
    """

    errors = validate_artifact(artifact)
    identity = artifact.get("run_identity")
    if identity is None:
        errors.append("baseline artifact is missing run_identity")
    else:
        errors.extend(
            run_identity_errors(
                identity,
                code_dirty=artifact.get("code_dirty"),
                require_clean=True,
                require_exact_model=True,
            )
        )
        if isinstance(identity, RunIdentity):
            identity_payload = identity.to_dict()
        elif isinstance(identity, dict):
            identity_payload = identity
        else:
            identity_payload = {}
        provenance = artifact.get("run_provenance")
        if identity_payload and isinstance(provenance, dict):
            if identity_payload.get("model_identity") != provenance.get("model_identity"):
                errors.append("baseline run identity does not match provenance model")
    if artifact.get("timing_profile") != COMPETITION_TIMING_PROFILE:
        errors.append("baseline artifact timing profile is not competition")
    try:
        outer_seconds = float(artifact.get("outer_platform_limit_seconds"))
    except (TypeError, ValueError):
        outer_seconds = None
    if outer_seconds is None or not math.isclose(
        outer_seconds,
        COMPETITION_OUTER_SECONDS,
        abs_tol=1e-9,
    ):
        errors.append("baseline artifact must use a 900-second outer limit")
    return sorted(set(errors))


# Short aliases make the registration gate discoverable without weakening the
# explicit baseline validator above.
baseline_registration_errors = validate_baseline_artifact


def can_register_baseline(artifact: dict[str, Any]) -> bool:
    return not validate_baseline_artifact(artifact)
