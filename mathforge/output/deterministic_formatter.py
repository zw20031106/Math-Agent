from __future__ import annotations

import re

from mathforge.harness.schemas import CandidateSolution, ProblemIR


_ANSWER_BLOCK = re.compile(
    r"^\s*(?:(?:final\s*)?answer|最终答案|答案)\s*[:：].*$",
    re.IGNORECASE | re.MULTILINE,
)
_LIMIT_NOTICE = "[Solution abbreviated to the configured output limit.]"
_LATEX_ANSWER_TYPES = frozenset(
    {
        "algebraic_structure",
        "expression",
        "fraction",
        "integer",
        "interval",
        "matrix",
        "polynomial",
        "set",
        "tuple",
        "vector",
    }
)


class DeterministicFormatter:
    def format(self, candidate: CandidateSolution, problem: ProblemIR) -> str:
        answer = candidate.final_answer.strip()
        solution = candidate.solution_text.strip() or "\n".join(
            candidate.public_solution_steps
        ).strip()
        if not solution:
            return canonical_final_response(
                "",
                exact_answer=answer,
                answer_type=problem.answer_type,
            )
        if not answer:
            return _ANSWER_BLOCK.sub("", solution).strip()
        return canonical_final_response(
            solution,
            exact_answer=answer,
            answer_type=problem.answer_type,
        )


def latex_final_answer(answer: str, answer_type: str) -> str:
    normalized = str(answer or "").strip()
    if not normalized or str(answer_type).strip().lower() not in _LATEX_ANSWER_TYPES:
        return normalized
    if normalized.startswith("$") and normalized.endswith("$"):
        return normalized
    if normalized.startswith(r"\(") and normalized.endswith(r"\)"):
        normalized = normalized[2:-2].strip()
    elif normalized.startswith(r"\[") and normalized.endswith(r"\]"):
        normalized = normalized[2:-2].strip()
    return f"${normalized}$"


def canonical_final_response(
    text: str,
    *,
    exact_answer: str,
    answer_type: str,
) -> str:
    body = _ANSWER_BLOCK.sub("", str(text or "")).strip()
    answer = latex_final_answer(exact_answer, answer_type)
    if not answer:
        return body
    answer_block = f"Final answer: {answer}"
    return f"{body}\n\n{answer_block}" if body else answer_block


def bound_final_response(
    text: str,
    *,
    exact_answer: str,
    max_chars: int,
    answer_type: str | None = None,
) -> str:
    """Bound exposition while retaining one complete canonical answer block."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text

    answer = (
        latex_final_answer(exact_answer, answer_type)
        if answer_type is not None
        else exact_answer.strip()
    )
    answer_block = f"Final answer: {answer}"
    suffix = f"\n\n{_LIMIT_NOTICE}\n\n{answer_block}"
    if len(suffix) >= max_chars:
        return answer_block

    body = text
    if body.rstrip().endswith(answer_block):
        body = body.rstrip()[: -len(answer_block)].rstrip()
    available = max_chars - len(suffix)
    prefix = body[:available].rstrip()
    for separator in ("\n\n", "\n", "。", ". ", "; "):
        boundary = prefix.rfind(separator)
        if boundary >= available // 2:
            prefix = prefix[: boundary + len(separator)].rstrip()
            break
    return f"{prefix}{suffix}" if prefix else suffix.lstrip()
