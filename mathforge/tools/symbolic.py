from __future__ import annotations

import sympy

from mathforge.tools.safe_parse import parse_expression


def safe_parse_expression(*, expression: str) -> dict:
    parsed = parse_expression(expression)
    return _result("pass", "hard", "expression parsed by the restricted grammar", {"expression": str(parsed)})


def simplify_expression(*, expression: str) -> dict:
    simplified = sympy.simplify(parse_expression(expression))
    return _result("pass", "hard", "restricted expression simplified", {"simplified": str(simplified)})


def symbolic_equivalence(*, left: str, right: str) -> dict:
    difference = sympy.simplify(parse_expression(left) - parse_expression(right))
    if difference == 0:
        return _result("pass", "hard", "symbolic difference simplifies to zero", {"difference": "0"})
    counterexample = _counterexample(difference)
    if counterexample is not None:
        return _result(
            "fail",
            "hard",
            "a valid substitution gives a nonzero difference",
            {"difference": str(difference), "counterexample": counterexample},
        )
    return _result(
        "unknown",
        "medium",
        "symbolic simplification was inconclusive",
        {"difference": str(difference)},
    )


def _counterexample(expression: sympy.Expr) -> dict[str, str] | None:
    symbols = sorted(expression.free_symbols, key=str)
    for value in (0, 1, 2, -1):
        substitutions = {symbol: value for symbol in symbols}
        try:
            evaluated = sympy.simplify(expression.subs(substitutions))
            if evaluated.is_finite and evaluated != 0:
                return {str(symbol): str(value) for symbol in symbols}
        except (TypeError, ValueError, ZeroDivisionError):
            continue
    if not symbols and expression.is_finite and expression != 0:
        return {}
    return None


def _result(status: str, strength: str, summary: str, payload: dict) -> dict:
    return {"status": status, "strength": strength, "summary": summary, "payload": payload}
