from __future__ import annotations

from dataclasses import asdict, dataclass

from mathforge.harness.schemas import CandidateSolution, ProblemIR
from mathforge.output.answer_validator import AnswerValidator


class CandidateAdmissionError(ValueError):
    pass


@dataclass(frozen=True)
class CandidateAdmissionDecision:
    candidate_id: str
    accepted: bool
    rejection_codes: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


class CandidateAdmissionGate:
    """Apply the deterministic Candidate contract before evidence or arbitration."""

    def __init__(self, answer_validator: AnswerValidator | None = None) -> None:
        self._answer_validator = answer_validator or AnswerValidator()

    def evaluate(
        self,
        candidate: CandidateSolution,
        problem: ProblemIR,
        *,
        answer_shape_status: str | None = None,
    ) -> CandidateAdmissionDecision:
        rejection_codes: list[str] = []
        try:
            candidate.validate()
        except (TypeError, ValueError):
            rejection_codes.append("candidate_schema_invalid")
        if candidate.answer_type != problem.answer_type:
            rejection_codes.append("incompatible_answer_type")
        rejection_codes.extend(self._answer_validator.validate(candidate, problem))
        if (
            answer_shape_status is not None
            and answer_shape_status != "pass"
        ):
            rejection_codes.append(f"answer_shape_{answer_shape_status}")
        rejection_codes = sorted(set(rejection_codes))
        return CandidateAdmissionDecision(
            candidate_id=candidate.candidate_id,
            accepted=not rejection_codes,
            rejection_codes=rejection_codes,
        )
