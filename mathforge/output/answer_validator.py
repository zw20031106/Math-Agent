from __future__ import annotations

import re

from mathforge.harness.schemas import CandidateSolution, ProblemIR


class AnswerValidator:
    def validate(self, candidate: CandidateSolution, problem: ProblemIR) -> list[str]:
        answer = candidate.final_answer.strip()
        errors: list[str] = []
        if not answer:
            errors.append("empty_answer")
        elif problem.answer_type == "choice" and not re.fullmatch(r"[A-H](?:\s*[,、]\s*[A-H])*", answer, re.I):
            errors.append("invalid_choice")
        elif problem.answer_type == "integer" and not re.fullmatch(r"[+-]?\d+", answer):
            errors.append("invalid_integer")
        elif problem.answer_type == "fraction" and not (
            re.fullmatch(r"[+-]?\d+\s*/\s*\d+", answer)
            or re.fullmatch(r"\\frac\{[+-]?\d+\}\{\d+\}", answer)
        ):
            errors.append("invalid_fraction")
        elif problem.answer_type == "vector" and not (
            "," in answer
            and (
                re.match(r"^\s*[\[(]", answer)
                or re.search(r"\^(?:\{?T\}?|\\top)\s*$", answer, re.I)
            )
        ):
            errors.append("invalid_vector")
        elif problem.answer_type == "tuple" and "," not in answer:
            errors.append("invalid_tuple")
        elif problem.answer_type == "interval" and not re.match(
            r"^\s*[\[(].*[\])]\s*$",
            answer,
        ):
            errors.append("invalid_interval")
        elif problem.answer_type == "set" and not (
            ("{" in answer and "}" in answer)
            or (r"\{" in answer and r"\}" in answer)
        ):
            errors.append("invalid_set")
        elif problem.answer_type == "matrix" and not (
            r"\begin" in answer
            or re.match(r"^\s*\[\s*[\[(]", answer)
        ):
            errors.append("invalid_matrix")
        return errors
