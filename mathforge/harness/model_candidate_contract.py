from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any


MODEL_CANDIDATE_PAYLOAD_VERSION = "3.0"

ANSWER_ONLY_PROFILE = "answer_only"
WORKED_SOLUTION_PROFILE = "worked_solution"
PROOF_FULL_PROFILE = "proof_full"
CANDIDATE_PROFILES = frozenset(
    {ANSWER_ONLY_PROFILE, WORKED_SOLUTION_PROFILE, PROOF_FULL_PROFILE}
)

ANSWER_ONLY_CANDIDATE_FIELDS = frozenset({"final_answer", "check"})
WORKED_SOLUTION_CANDIDATE_FIELDS = frozenset(
    {"final_answer", "method", "steps", "uncertainties"}
)
PROOF_FULL_CANDIDATE_FIELDS = frozenset(
    {"final_answer", "method", "proof_steps", "open_conditions"}
)
MODEL_CANDIDATE_PROFILE_FIELDS = {
    ANSWER_ONLY_PROFILE: ANSWER_ONLY_CANDIDATE_FIELDS,
    WORKED_SOLUTION_PROFILE: WORKED_SOLUTION_CANDIDATE_FIELDS,
    PROOF_FULL_PROFILE: PROOF_FULL_CANDIDATE_FIELDS,
}

SIMPLE_CANDIDATE_FIELDS = ANSWER_ONLY_CANDIDATE_FIELDS
STANDARD_CANDIDATE_FIELDS = WORKED_SOLUTION_CANDIDATE_FIELDS
PROOF_CANDIDATE_FIELDS = PROOF_FULL_CANDIDATE_FIELDS

LEGACY_SIMPLE_CANDIDATE_FIELDS = frozenset({"answer", "check"})
LEGACY_STANDARD_CANDIDATE_FIELDS = frozenset(
    {"answer", "method", "steps", "uncertainties"}
)
LEGACY_PROOF_CANDIDATE_FIELDS = frozenset(
    {"conclusion", "method", "proof_steps", "open_conditions"}
)
LEGACY_CANDIDATE_FIELD_SETS = frozenset(
    {
        LEGACY_SIMPLE_CANDIDATE_FIELDS,
        LEGACY_STANDARD_CANDIDATE_FIELDS,
        LEGACY_PROOF_CANDIDATE_FIELDS,
    }
)

SEMANTIC_STEP_FIELDS = frozenset({"statement", "claim_kind", "depends_on"})
SEMANTIC_CHECK_FIELDS = frozenset({"statement", "claim_kind"})
MODEL_CLAIM_KINDS = frozenset(
    {
        "unknown",
        "reasoning",
        "definition",
        "theorem_preconditions",
        "necessity",
        "sufficiency",
        "existence",
        "uniqueness",
        "boundary",
        "interchange",
        "equality",
        "matrix_shape",
        "probability_normalization",
        "finite_case",
        "answer_shape",
    }
)

# Internal normalized Candidate fields. Models no longer receive this as a wire
# schema; these names remain the executable Host boundary after normalization.
MODEL_CANDIDATE_REQUIRED_FIELDS = frozenset({"final_answer", "solution_text"})
MODEL_CANDIDATE_OPTIONAL_FIELDS = frozenset(
    {
        "method",
        "public_solution_steps",
        "claims",
        "assumptions",
        "theorems",
        "unresolved_obligations",
    }
)
MODEL_CANDIDATE_NONEMPTY_FIELDS = MODEL_CANDIDATE_REQUIRED_FIELDS
MODEL_CANDIDATE_COMPATIBILITY_FIELDS = frozenset()
MODEL_CANDIDATE_HOST_FIELDS = frozenset(
    {
        "candidate_id",
        "role",
        "answer_type",
        "planned_method_family",
        "version",
        "schema_version",
        "parse_status",
        "parse_tier",
        "source",
        "is_method_duplicate",
        "contract_deviations",
        "degraded",
        "assurance",
        "method_steps",
    }
)
MODEL_CLAIM_FIELDS = frozenset(
    {
        "statement",
        "depends_on",
        "check_type",
        "importance",
        "claim_kind",
    }
)
MODEL_CLAIM_HOST_FIELDS = frozenset(
    {
        "claim_id",
        "status",
        "verification_state",
        "check_spec",
        "schema_version",
        "version",
    }
)

# E2 keeps the executable Host Candidate boundary stable while making the
# model-facing payload explicit.  The model supplies mathematical semantics;
# the Host assigns lifecycle, identity, and scheduling metadata after parsing.
MODEL_SEMANTIC_PAYLOAD_VERSION = "1.0"
MODEL_SEMANTIC_REQUIRED_FIELDS = frozenset({"final_answer", "solution_text"})
MODEL_SEMANTIC_OPTIONAL_FIELDS = frozenset(
    {
        "method",
        "public_solution_steps",
        "claims",
        "assumptions",
        "theorems",
        "unresolved_obligations",
        "proof_steps",
        "critical_claims",
        "open_conditions",
    }
)
MODEL_SEMANTIC_FIELDS = (
    MODEL_SEMANTIC_REQUIRED_FIELDS | MODEL_SEMANTIC_OPTIONAL_FIELDS
)
MODEL_SEMANTIC_HOST_FIELDS = frozenset(
    {
        *MODEL_CANDIDATE_HOST_FIELDS,
        *MODEL_CLAIM_HOST_FIELDS,
        "artifact_id",
        "message_id",
        "task_id",
        "turn_id",
        "plan_id",
        "plan_version",
        "priority",
        "token_limit",
        "token_limits",
        "max_tokens",
        "max_output_tokens",
        "timeout",
        "timeout_seconds",
        "status",
    }
)


def _semantic_host_fields(value: Any) -> set[str]:
    """Return Host-owned keys found at any depth of a model payload."""

    found: set[str] = set()
    if isinstance(value, dict):
        found.update(MODEL_SEMANTIC_HOST_FIELDS.intersection(value))
        for nested in value.values():
            found.update(_semantic_host_fields(nested))
    elif isinstance(value, list):
        for nested in value:
            found.update(_semantic_host_fields(nested))
    return found


def _semantic_string_list(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"ModelSemanticPayload.{field_name} must be a string list")
    return tuple(str(item) for item in value)


def _semantic_object_list(value: Any, field_name: str) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"ModelSemanticPayload.{field_name} must be an object list")
    return tuple(deepcopy(item) for item in value)


@dataclass(frozen=True)
class ModelSemanticPayload:
    """The small model-owned mathematical payload used by E2 experiments.

    ``final_answer`` and ``solution_text`` are the only required fields.  All
    identifiers, versions, statuses, priorities, budgets, and timeout metadata
    remain Host-owned and are rejected recursively rather than silently copied.
    Optional structured fields are accepted only when a role genuinely needs
    them (for example, ordered proof steps).
    """

    final_answer: str
    solution_text: str
    method: str = ""
    public_solution_steps: tuple[str, ...] = ()
    claims: tuple[dict[str, Any], ...] = ()
    assumptions: tuple[str, ...] = ()
    theorems: tuple[str, ...] = ()
    unresolved_obligations: tuple[str, ...] = ()
    proof_steps: tuple[dict[str, Any], ...] = ()
    critical_claims: tuple[dict[str, Any], ...] = ()
    open_conditions: tuple[str, ...] = ()
    schema_version: str = MODEL_SEMANTIC_PAYLOAD_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MODEL_SEMANTIC_PAYLOAD_VERSION:
            raise ValueError("invalid ModelSemanticPayload schema version")
        if not isinstance(self.final_answer, str) or not self.final_answer.strip():
            raise ValueError("ModelSemanticPayload.final_answer must be non-empty")
        if not isinstance(self.solution_text, str) or not self.solution_text.strip():
            raise ValueError("ModelSemanticPayload.solution_text must be non-empty")
        if not isinstance(self.method, str):
            raise ValueError("ModelSemanticPayload.method must be a string")
        for name in (
            "public_solution_steps",
            "assumptions",
            "theorems",
            "unresolved_obligations",
            "open_conditions",
        ):
            value = getattr(self, name)
            if not isinstance(value, tuple) or any(
                not isinstance(item, str) for item in value
            ):
                raise ValueError(
                    f"ModelSemanticPayload.{name} must be a string tuple"
                )
        for name in ("claims", "proof_steps", "critical_claims"):
            value = getattr(self, name)
            if not isinstance(value, tuple) or any(
                not isinstance(item, dict) for item in value
            ):
                raise ValueError(
                    f"ModelSemanticPayload.{name} must be an object tuple"
                )
        nested = _semantic_host_fields(self.to_dict(include_empty=True))
        if nested:
            raise ValueError(
                "ModelSemanticPayload contains Host-owned fields: "
                + ", ".join(sorted(nested))
            )

    def to_dict(self, *, include_empty: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "final_answer": self.final_answer,
            "solution_text": self.solution_text,
        }
        optional_values = {
            "method": self.method,
            "public_solution_steps": list(self.public_solution_steps),
            "claims": [deepcopy(item) for item in self.claims],
            "assumptions": list(self.assumptions),
            "theorems": list(self.theorems),
            "unresolved_obligations": list(self.unresolved_obligations),
            "proof_steps": [deepcopy(item) for item in self.proof_steps],
            "critical_claims": [deepcopy(item) for item in self.critical_claims],
            "open_conditions": list(self.open_conditions),
        }
        for name, value in optional_values.items():
            if include_empty or value not in ("", [], None):
                payload[name] = value
        return payload

    @classmethod
    def from_dict(cls, payload: Any) -> "ModelSemanticPayload":
        if not isinstance(payload, dict):
            raise ValueError("ModelSemanticPayload must be an object")
        missing = MODEL_SEMANTIC_REQUIRED_FIELDS - set(payload)
        if missing:
            raise ValueError(
                "ModelSemanticPayload is missing required fields: "
                + ", ".join(sorted(missing))
            )
        forbidden = _semantic_host_fields(payload)
        if forbidden:
            raise ValueError(
                "ModelSemanticPayload contains Host-owned fields: "
                + ", ".join(sorted(forbidden))
            )
        unknown = set(payload) - MODEL_SEMANTIC_FIELDS
        if unknown:
            raise ValueError(
                "unknown ModelSemanticPayload fields: "
                + ", ".join(sorted(unknown))
            )
        final_answer = payload["final_answer"]
        solution_text = payload["solution_text"]
        if not isinstance(final_answer, str) or not final_answer.strip():
            raise ValueError("ModelSemanticPayload.final_answer must be non-empty")
        if not isinstance(solution_text, str) or not solution_text.strip():
            raise ValueError("ModelSemanticPayload.solution_text must be non-empty")
        method = payload.get("method", "")
        if not isinstance(method, str):
            raise ValueError("ModelSemanticPayload.method must be a string")
        return cls(
            final_answer=final_answer,
            solution_text=solution_text,
            method=method,
            public_solution_steps=_semantic_string_list(
                payload.get("public_solution_steps", []), "public_solution_steps"
            ),
            claims=_semantic_object_list(payload.get("claims", []), "claims"),
            assumptions=_semantic_string_list(
                payload.get("assumptions", []), "assumptions"
            ),
            theorems=_semantic_string_list(
                payload.get("theorems", []), "theorems"
            ),
            unresolved_obligations=_semantic_string_list(
                payload.get("unresolved_obligations", []),
                "unresolved_obligations",
            ),
            proof_steps=_semantic_object_list(
                payload.get("proof_steps", []), "proof_steps"
            ),
            critical_claims=_semantic_object_list(
                payload.get("critical_claims", []), "critical_claims"
            ),
            open_conditions=_semantic_string_list(
                payload.get("open_conditions", []), "open_conditions"
            ),
        )

    @classmethod
    def from_payload(cls, payload: Any) -> "ModelSemanticPayload":
        """Compatibility alias used by parser and experiment callers."""

        return cls.from_dict(payload)


def model_semantic_payload_example(profile: str) -> dict[str, Any]:
    """Return the minimal wire example for a response profile."""

    normalized = candidate_profile_for_response_mode(profile)
    if normalized == PROOF_FULL_PROFILE:
        return {
            "final_answer": "<proved conclusion>",
            "solution_text": "<short proof summary>",
            "method": "direct-deduction",
            "proof_steps": [
                {"statement": "<ordered proof step>", "claim_kind": "reasoning"},
                {"statement": "<proof conclusion>", "claim_kind": "sufficiency"},
            ],
            "open_conditions": [],
        }
    return {
        "final_answer": "<exact answer>",
        "solution_text": (
            "one short public check"
            if normalized == ANSWER_ONLY_PROFILE
            else "<concise public derivation>"
        ),
    }


def validate_model_semantic_payload(payload: Any) -> None:
    ModelSemanticPayload.from_dict(payload)


def candidate_profile_for_response_mode(response_mode: str) -> str:
    normalized = str(response_mode).strip().lower()
    if normalized not in CANDIDATE_PROFILES:
        raise ValueError(f"unsupported Candidate response mode: {response_mode}")
    return normalized


def candidate_profile_example(profile: str) -> dict[str, Any]:
    normalized = candidate_profile_for_response_mode(profile)
    if normalized == ANSWER_ONLY_PROFILE:
        return {
            "final_answer": "<exact answer>",
            "check": {
                "statement": "<short public verification>",
                "claim_kind": "answer_shape",
            },
        }
    step = {
        "statement": "<public mathematical step>",
        "claim_kind": "reasoning",
        "depends_on": [],
    }
    if normalized == WORKED_SOLUTION_PROFILE:
        return {
            "final_answer": "<exact answer>",
            "method": "direct-deduction",
            "steps": [step],
            "uncertainties": [],
        }
    return {
        "final_answer": "<proved conclusion>",
        "method": "direct-deduction",
        "proof_steps": [
            step,
            {
                "statement": "<public proof conclusion>",
                "claim_kind": "sufficiency",
                "depends_on": [0],
            },
        ],
        "open_conditions": [],
    }


def candidate_profile_shape(profile: str) -> str:
    return json.dumps(
        candidate_profile_example(profile),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def validate_candidate_profile(payload: Any, profile: str) -> None:
    normalized = candidate_profile_for_response_mode(profile)
    if not isinstance(payload, dict):
        raise ValueError("Candidate profile must be an object")
    if set(payload) != MODEL_CANDIDATE_PROFILE_FIELDS[normalized]:
        raise ValueError("Candidate profile fields do not match response mode")
    answer = payload.get("final_answer")
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("Candidate final_answer must be a non-empty string")
    if normalized == ANSWER_ONLY_PROFILE:
        _validate_check(payload["check"])
        return
    method = payload.get("method")
    if not isinstance(method, str) or not method.strip():
        raise ValueError("Candidate method must be a non-empty string")
    list_name = "steps" if normalized == WORKED_SOLUTION_PROFILE else "proof_steps"
    steps = payload.get(list_name)
    minimum = 1 if normalized == WORKED_SOLUTION_PROFILE else 2
    if not isinstance(steps, list) or len(steps) < minimum:
        raise ValueError(f"Candidate {list_name} is incomplete")
    for index, step in enumerate(steps):
        _validate_step(step, index=index)
    tail_name = (
        "uncertainties"
        if normalized == WORKED_SOLUTION_PROFILE
        else "open_conditions"
    )
    tail = payload.get(tail_name)
    if not isinstance(tail, list) or any(not isinstance(item, str) for item in tail):
        raise ValueError(f"Candidate {tail_name} must be a string list")


def _validate_check(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != SEMANTIC_CHECK_FIELDS:
        raise ValueError("Candidate check fields are invalid")
    if not isinstance(value.get("statement"), str) or not value["statement"].strip():
        raise ValueError("Candidate check statement is empty")
    _validate_claim_kind(value.get("claim_kind"))


def _validate_step(value: Any, *, index: int) -> None:
    if not isinstance(value, dict) or set(value) != SEMANTIC_STEP_FIELDS:
        raise ValueError("Candidate semantic step fields are invalid")
    if not isinstance(value.get("statement"), str) or not value["statement"].strip():
        raise ValueError("Candidate semantic step statement is empty")
    _validate_claim_kind(value.get("claim_kind"))
    dependencies = value.get("depends_on")
    if not isinstance(dependencies, list):
        raise ValueError("Candidate semantic step dependencies must be a list")
    for dependency in dependencies:
        if type(dependency) is not int or not 0 <= dependency < index:
            raise ValueError("Candidate semantic step dependency is invalid")


def _validate_claim_kind(value: Any) -> None:
    if not isinstance(value, str) or value not in MODEL_CLAIM_KINDS:
        raise ValueError("Candidate claim_kind is invalid")


MODEL_CANDIDATE_STRUCTURAL_SHAPE = candidate_profile_shape(ANSWER_ONLY_PROFILE)

MODEL_CANDIDATE_PATCH_FIELDS = frozenset(
    {
        "replacement_claims",
        "final_answer",
        "public_solution_steps",
        "unresolved_obligations",
    }
)
MODEL_CANDIDATE_PATCH_STRUCTURAL_SHAPE = (
    '{"replacement_claims":[{"claim_id":"c1",'
    '"statement":"<corrected public claim>","depends_on":[],'
    '"check_type":"reasoning","importance":"critical"}],'
    '"final_answer":"<corrected or unchanged answer>",'
    '"public_solution_steps":["<corrected public step with $LaTeX$ math>"],'
    '"unresolved_obligations":[]}'
)
