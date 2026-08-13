from __future__ import annotations

import re

from mathforge.harness.schemas import CandidateSolution, ProblemIR, ResponseMode
from mathforge.parsing.answer_extraction import unwrap_boxed


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
_SIMPLE_MATH_TEXT = re.compile(r"^[\s0-9A-Za-z.+\-*/=<>(),\[\]{}^_]+$")


class DeterministicFormatter:
    def format(self, candidate: CandidateSolution, problem: ProblemIR) -> str:
        answer = candidate.final_answer.strip()
        solution = candidate.solution_text.strip() or "\n".join(
            candidate.public_solution_steps
        ).strip()
        if problem.response_mode != ResponseMode.PROOF_FULL.value:
            return canonical_final_response(
                "",
                exact_answer=answer,
                answer_type=problem.answer_type,
                response_mode=problem.response_mode,
            )
        return canonical_final_response(
            solution,
            exact_answer=answer,
            answer_type=problem.answer_type,
            response_mode=problem.response_mode,
        )


def latex_final_answer(answer: str, answer_type: str) -> str:
    normalized = str(answer or "").strip()
    if not normalized:
        return normalized
    if normalized.startswith("$") and normalized.endswith("$"):
        return normalized
    if normalized.startswith(r"\(") and normalized.endswith(r"\)"):
        normalized = normalized[2:-2].strip()
    elif normalized.startswith(r"\[") and normalized.endswith(r"\]"):
        normalized = normalized[2:-2].strip()
    normalized_type = str(answer_type).strip().lower()
    if normalized_type == "choice":
        return f"$\\mathrm{{{_escape_latex_text(normalized)}}}$"
    if normalized_type == "text":
        if _SIMPLE_MATH_TEXT.fullmatch(normalized) and (
            any(character.isdigit() for character in normalized)
            or any(marker in normalized for marker in ("=", "<", ">", "^", "_"))
        ):
            return f"${normalized}$"
        return f"$\\text{{{_escape_latex_text(normalized)}}}$"
    if normalized_type not in _LATEX_ANSWER_TYPES:
        return normalized
    return f"${normalized}$"


def exact_final_answer(answer: str, answer_type: str) -> str:
    """Return the public answer without labels or outer math delimiters."""

    del answer_type
    normalized = unwrap_boxed(answer).strip()
    prefix = re.fullmatch(
        r"(?:(?:final\s*)?answer|\u6700\u7ec8\u7b54\u6848|\u7b54\u6848)\s*[:\uff1a]\s*(.+)",
        normalized,
        re.IGNORECASE | re.DOTALL,
    )
    if prefix:
        normalized = unwrap_boxed(prefix.group(1)).strip()
    if normalized.startswith("$") and normalized.endswith("$"):
        normalized = normalized[1:-1].strip()
    elif normalized.startswith(r"\(") and normalized.endswith(r"\)"):
        normalized = normalized[2:-2].strip()
    elif normalized.startswith(r"\[") and normalized.endswith(r"\]"):
        normalized = normalized[2:-2].strip()
    wrapper = re.fullmatch(r"\\(?:mathrm|text)\{([^{}]*)\}", normalized)
    return wrapper.group(1).strip() if wrapper else normalized


def _escape_latex_text(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "%": r"\%",
        "&": r"\&",
        "#": r"\#",
        "_": r"\_",
    }
    return "".join(replacements.get(character, character) for character in value)


def canonical_final_response(
    text: str,
    *,
    exact_answer: str,
    answer_type: str,
    response_mode: str | None = None,
) -> str:
    body = _ANSWER_BLOCK.sub("", str(text or "")).strip()
    answer = exact_final_answer(exact_answer, answer_type)
    if response_mode != ResponseMode.PROOF_FULL.value:
        return answer or body
    if not body:
        return answer
    if not answer:
        return body
    last_line = next(
        (line.strip() for line in reversed(body.splitlines()) if line.strip()),
        "",
    )
    return body if last_line == answer else f"{body}\n\n{answer}"


def bound_final_response(
    text: str,
    *,
    exact_answer: str,
    max_chars: int,
    answer_type: str | None = None,
    response_mode: str | None = None,
) -> str:
    """Bound proof exposition while retaining the exact public conclusion."""
    answer = exact_final_answer(exact_answer, answer_type or "text")
    if response_mode != ResponseMode.PROOF_FULL.value:
        return answer or str(text or "").strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text

    suffix = f"\n\n{_LIMIT_NOTICE}\n\n{answer}"
    if len(suffix) >= max_chars:
        return answer[:max_chars]

    body = text
    if answer and body.rstrip().endswith(answer):
        body = body.rstrip()[: -len(answer)].rstrip()
    available = max_chars - len(suffix)
    prefix = body[:available].rstrip()
    for separator in ("\n\n", "\n", "。", ". ", "; "):
        boundary = prefix.rfind(separator)
        if boundary >= available // 2:
            prefix = prefix[: boundary + len(separator)].rstrip()
            break
    return f"{prefix}{suffix}" if prefix else suffix.lstrip()
