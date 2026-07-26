from __future__ import annotations

from mathforge.parsing.latex import braces_balanced
from mathforge.verification.answer_normalization import answer_shape_valid


def latex_syntax_check(*, text: str) -> dict:
    status = "pass" if braces_balanced(str(text)) else "fail"
    return _result(status, "hard", "LaTeX brace balance checked", {})


def answer_type_check(*, answer: str, answer_type: str) -> dict:
    valid = answer_shape_valid(answer, answer_type)
    status = "pass" if valid else "fail"
    return _result(status, "hard", "answer checked against requested type", {"answer_type": answer_type})


def _result(status: str, strength: str, summary: str, payload: dict) -> dict:
    return {"status": status, "strength": strength, "summary": summary, "payload": payload}
