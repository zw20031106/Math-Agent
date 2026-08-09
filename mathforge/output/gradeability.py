from __future__ import annotations

from dataclasses import asdict, dataclass

from mathforge.evaluation.scoring import extract_final_answer
from mathforge.output.deterministic_formatter import canonical_final_response
from mathforge.verification.answer_normalization import (
    answer_shape_valid,
    canonical_answer,
)


@dataclass(frozen=True)
class ScorerRoundTrip:
    status: str
    extracted_answer: str
    expected_canonical: str
    extracted_canonical: str
    reformatted: bool = False

    def to_dict(self) -> dict[str, str | bool]:
        return asdict(self)


def enforce_scorer_round_trip(
    response: str,
    *,
    exact_answer: str,
    answer_type: str,
    response_mode: str,
) -> tuple[str, ScorerRoundTrip]:
    """Guarantee that the production scorer extracts the intended answer."""

    expected = canonical_answer(exact_answer, answer_type)
    first = _round_trip(response, expected=expected, answer_type=answer_type)
    if first.status == "pass":
        return response, first

    repaired = canonical_final_response(
        response,
        exact_answer=exact_answer,
        answer_type=answer_type,
        response_mode=response_mode,
    )
    second = _round_trip(repaired, expected=expected, answer_type=answer_type)
    if second.status != "pass":
        raise ValueError("final answer is not scorer-round-trip gradeable")
    return repaired, ScorerRoundTrip(
        status="pass",
        extracted_answer=second.extracted_answer,
        expected_canonical=second.expected_canonical,
        extracted_canonical=second.extracted_canonical,
        reformatted=True,
    )


def is_gradeable_response(response: str, answer_type: str) -> bool:
    extracted = extract_final_answer(response)
    if not extracted:
        return False
    normalized_type = str(answer_type).strip().lower()
    if normalized_type in {"proof", "text", "explanation", "derivation"}:
        return True
    return answer_shape_valid(extracted, normalized_type)


def _round_trip(
    response: str,
    *,
    expected: str,
    answer_type: str,
) -> ScorerRoundTrip:
    extracted = extract_final_answer(response)
    actual = canonical_answer(extracted, answer_type) if extracted else ""
    normalized_type = str(answer_type).strip().lower()
    shape_valid = (
        bool(extracted)
        if normalized_type in {"proof", "text", "explanation", "derivation"}
        else answer_shape_valid(extracted, normalized_type)
    )
    return ScorerRoundTrip(
        status="pass" if shape_valid and actual == expected else "failed",
        extracted_answer=extracted,
        expected_canonical=expected,
        extracted_canonical=actual,
    )
