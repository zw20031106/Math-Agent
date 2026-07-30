from __future__ import annotations

import re

from mathforge.harness.schemas import CandidateSolution, ProblemIR


_ANSWER_BLOCK = re.compile(
    r"^\s*(?:(?:final\s*)?answer|最终答案|答案)\s*[:：].*$",
    re.IGNORECASE | re.MULTILINE,
)
_LIMIT_NOTICE = "[Solution abbreviated to the configured output limit.]"


class DeterministicFormatter:
    def format(self, candidate: CandidateSolution, problem: ProblemIR) -> str:
        del problem
        answer = candidate.final_answer.strip()
        solution = candidate.solution_text.strip() or "\n".join(
            candidate.public_solution_steps
        ).strip()
        if not solution:
            return answer
        if candidate.parse_status.split(":", 1)[0] == "raw_text":
            return solution
        without_answer_blocks = _ANSWER_BLOCK.sub("", solution).strip()
        if not answer:
            return without_answer_blocks
        if without_answer_blocks:
            return f"{without_answer_blocks}\n\nFinal answer: {answer}"
        return f"Final answer: {answer}"


def bound_final_response(
    text: str,
    *,
    exact_answer: str,
    max_chars: int,
) -> str:
    """Bound exposition while retaining one complete canonical answer block."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text

    answer_block = f"Final answer: {exact_answer.strip()}"
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
