from __future__ import annotations

from mathforge.harness.schemas import CandidateSolution, ProblemIR
from mathforge.verification.answer_normalization import answer_shape_valid


MAX_FINAL_ANSWER_CHARS = 16384
MAX_RECOVERED_FINAL_ANSWER_CHARS = 4096


class AnswerValidator:
    def validate(self, candidate: CandidateSolution, problem: ProblemIR) -> list[str]:
        answer = candidate.final_answer.strip()
        errors: list[str] = []
        if not answer:
            errors.append("empty_answer")
        elif len(answer) > MAX_FINAL_ANSWER_CHARS:
            errors.append("final_answer_too_long")
        elif (
            candidate.parse_tier == "answer_recovered"
            and len(answer) > MAX_RECOVERED_FINAL_ANSWER_CHARS
        ):
            errors.append("recovered_answer_too_long")
        elif not answer_shape_valid(answer, problem.answer_type):
            errors.append(f"invalid_{problem.answer_type}")
        return errors
