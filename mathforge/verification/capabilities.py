from __future__ import annotations

from enum import Enum


class ClaimKind(str, Enum):
    UNKNOWN = "unknown"
    REASONING = "reasoning"
    DEFINITION = "definition"
    THEOREM_PRECONDITIONS = "theorem_preconditions"
    NECESSITY = "necessity"
    SUFFICIENCY = "sufficiency"
    EXISTENCE = "existence"
    UNIQUENESS = "uniqueness"
    BOUNDARY = "boundary"
    INTERCHANGE = "interchange"
    EQUALITY = "equality"
    MATRIX_SHAPE = "matrix_shape"
    PROBABILITY_NORMALIZATION = "probability_normalization"
    FINITE_CASE = "finite_case"
    ANSWER_SHAPE = "answer_shape"


class VerificationCapability(str, Enum):
    NONE = "none"
    SYNTAX_RESTRICTED_PARSE = "syntax.restricted_parse"
    SYNTAX_LATEX_BRACE_BALANCE = "syntax.latex_brace_balance"
    ANSWER_SHAPE = "answer.shape"
    EQUALITY_SYMBOLIC_UNDER_DOMAIN = "equality.symbolic_under_domain"
    ALGEBRA_SIMPLIFICATION = "algebra.simplification"
    EQUALITY_NUMERICAL_SAMPLES = "equality.numerical_samples"
    MATRIX_SHAPE = "matrix.shape"
    PROBABILITY_NORMALIZATION = "probability.normalization"
    FINITE_CASE_EXACT = "finite_case.exact"
    PROOF_OBLIGATION_REVIEW = "proof.obligation_review"
    # Reserved for an explicit deterministic proof checker.  No current LLM
    # path may emit this capability, which keeps ``formally_verified`` honest.
    FORMAL_PROOF = "formal.proof"


class ClaimVerificationState(str, Enum):
    UNKNOWN = "unknown"
    SYNTAX_CHECKED = "syntax_checked"
    NUMERICALLY_SUPPORTED = "numerically_supported"
    SEMANTICALLY_VERIFIED = "semantically_verified"
    REJECTED = "rejected"


_PROOF_CLAIM_KINDS = frozenset(
    {
        ClaimKind.DEFINITION.value,
        ClaimKind.THEOREM_PRECONDITIONS.value,
        ClaimKind.NECESSITY.value,
        ClaimKind.SUFFICIENCY.value,
        ClaimKind.EXISTENCE.value,
        ClaimKind.UNIQUENESS.value,
        ClaimKind.BOUNDARY.value,
        ClaimKind.INTERCHANGE.value,
    }
)

_CHECK_CLAIM_KINDS = {
    "reasoning": ClaimKind.REASONING.value,
    "symbolic_equivalence": ClaimKind.EQUALITY.value,
    "matrix_shape_check": ClaimKind.MATRIX_SHAPE.value,
    "density_normalization": ClaimKind.PROBABILITY_NORMALIZATION.value,
    "small_case_enumeration": ClaimKind.FINITE_CASE.value,
    "answer_type_check": ClaimKind.ANSWER_SHAPE.value,
}

_SEMANTIC_CAPABILITIES = frozenset(
    {
        VerificationCapability.EQUALITY_SYMBOLIC_UNDER_DOMAIN.value,
        VerificationCapability.MATRIX_SHAPE.value,
        VerificationCapability.PROBABILITY_NORMALIZATION.value,
        VerificationCapability.FINITE_CASE_EXACT.value,
    }
)

_CAPABILITY_CLAIM_KINDS = {
    VerificationCapability.EQUALITY_SYMBOLIC_UNDER_DOMAIN.value: frozenset(
        {ClaimKind.EQUALITY.value}
    ),
    VerificationCapability.MATRIX_SHAPE.value: frozenset(
        {ClaimKind.MATRIX_SHAPE.value}
    ),
    VerificationCapability.PROBABILITY_NORMALIZATION.value: frozenset(
        {ClaimKind.PROBABILITY_NORMALIZATION.value}
    ),
    VerificationCapability.FINITE_CASE_EXACT.value: frozenset(
        {ClaimKind.FINITE_CASE.value}
    ),
}


def derive_claim_kind(check_suggestion: str) -> str:
    normalized = str(check_suggestion).strip().lower()
    if normalized in _PROOF_CLAIM_KINDS:
        return normalized
    return _CHECK_CLAIM_KINDS.get(normalized, ClaimKind.UNKNOWN.value)


def capability_verifies_claim(capability: str) -> bool:
    return str(capability) in _SEMANTIC_CAPABILITIES


def capability_applies_to_claim(capability: str, claim_kind: str) -> bool:
    return str(claim_kind) in _CAPABILITY_CLAIM_KINDS.get(
        str(capability),
        frozenset(),
    )


def fatal_capability_applies(
    capability: str,
    claim_kind: str,
    *,
    input_complete: bool,
    context_complete: bool,
    representation_only: bool = False,
) -> bool:
    return (
        input_complete
        and context_complete
        and not representation_only
        and capability_applies_to_claim(capability, claim_kind)
    )


def capability_satisfies_obligation(capability: str, obligation_kind: str) -> bool:
    return (
        str(capability) == VerificationCapability.PROOF_OBLIGATION_REVIEW.value
        and str(obligation_kind) in _PROOF_CLAIM_KINDS
    )
