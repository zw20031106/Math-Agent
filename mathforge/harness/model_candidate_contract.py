from __future__ import annotations

import json
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
