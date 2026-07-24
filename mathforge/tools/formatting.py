from __future__ import annotations

import re

from mathforge.parsing.latex import braces_balanced


def latex_syntax_check(*, text: str) -> dict:
    status = "pass" if braces_balanced(str(text)) else "fail"
    return _result(status, "hard", "LaTeX brace balance checked", {})


def answer_type_check(*, answer: str, answer_type: str) -> dict:
    value = str(answer).strip()
    valid = bool(value)
    if answer_type == "choice":
        valid = bool(re.fullmatch(r"[A-H](?:\s*[,、]\s*[A-H])*", value, re.I))
    elif answer_type == "integer":
        valid = bool(re.fullmatch(r"[+-]?\d+", value))
    elif answer_type == "fraction":
        valid = bool(
            re.fullmatch(r"[+-]?\d+\s*/\s*\d+", value)
            or re.fullmatch(r"\\frac\{[+-]?\d+\}\{\d+\}", value)
        )
    elif answer_type == "vector":
        valid = "," in value and bool(
            re.match(r"^\s*[\[(]", value)
            or re.search(r"\^(?:\{?T\}?|\\top)\s*$", value, re.I)
        )
    elif answer_type == "tuple":
        valid = "," in value
    elif answer_type == "interval":
        valid = bool(re.match(r"^\s*[\[(].*[\])]\s*$", value))
    elif answer_type == "set":
        valid = (
            ("{" in value and "}" in value)
            or (r"\{" in value and r"\}" in value)
        )
    elif answer_type == "matrix":
        valid = r"\begin" in value or bool(
            re.match(r"^\s*\[\s*[\[(]", value)
        )
    status = "pass" if valid else "fail"
    return _result(status, "hard", "answer checked against requested type", {"answer_type": answer_type})


def _result(status: str, strength: str, summary: str, payload: dict) -> dict:
    return {"status": status, "strength": strength, "summary": summary, "payload": payload}
