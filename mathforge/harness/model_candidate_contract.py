from __future__ import annotations


MODEL_CANDIDATE_PAYLOAD_VERSION = "2.2"

SIMPLE_CANDIDATE_FIELDS = frozenset({"answer", "check"})
STANDARD_CANDIDATE_FIELDS = frozenset(
    {"answer", "method", "steps", "uncertainties"}
)
PROOF_CANDIDATE_FIELDS = frozenset(
    {"conclusion", "method", "proof_steps", "open_conditions"}
)
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
MODEL_CANDIDATE_PROFILE_FIELDS = {
    "simple": MODEL_CANDIDATE_REQUIRED_FIELDS,
    "standard": MODEL_CANDIDATE_REQUIRED_FIELDS,
    "proof": MODEL_CANDIDATE_REQUIRED_FIELDS,
}
MODEL_CANDIDATE_NONEMPTY_FIELDS = MODEL_CANDIDATE_REQUIRED_FIELDS
MODEL_CANDIDATE_COMPATIBILITY_FIELDS = frozenset({"method_steps"})
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
    }
)
MODEL_CLAIM_FIELDS = frozenset(
    {
        "claim_id",
        "statement",
        "depends_on",
        "check_type",
        "importance",
    }
)
MODEL_CLAIM_HOST_FIELDS = frozenset(
    {
        "status",
        "claim_kind",
        "verification_state",
        "check_spec",
        "schema_version",
    }
)

MODEL_CANDIDATE_STRUCTURAL_SHAPE = (
    '{"final_answer":"\\\\boxed{<answer>}",'
    '"solution_text":"<public derivation>"}'
)

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
