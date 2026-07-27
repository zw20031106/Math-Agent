from __future__ import annotations

import math
from itertools import islice, product

import sympy

from mathforge.math_ir.domain import normalize_domain
from mathforge.tools.safe_parse import parse_expression
from mathforge.tools.resource_limits import MAX_INTEGER_DIGITS


def numerical_residual(
    *,
    left: str,
    right: str = "0",
    tolerance: float = 1e-9,
    samples: list[float] | None = None,
    domains: dict[str, str] | None = None,
    max_samples: int = 64,
) -> dict:
    difference = parse_expression(left) - parse_expression(right)
    symbols = sorted(difference.free_symbols, key=str)
    domain_rules = {
        str(symbol): normalize_domain(str(domain))
        for symbol, domain in (domains or {}).items()
    }
    pools = [
        _sample_pool(
            domain_rules.get(str(symbol)),
            samples,
        )
        for symbol in symbols
    ]
    assignments = product(*pools) if symbols else [()]
    residuals: list[float] = []
    attempted = 0
    rejected = 0
    for assigned in islice(assignments, max(1, min(int(max_samples), 256))):
        attempted += 1
        substitutions = dict(zip(symbols, assigned))
        try:
            value = complex(sympy.N(difference.subs(substitutions)))
        except (TypeError, ValueError, ZeroDivisionError, OverflowError):
            rejected += 1
            continue
        if math.isfinite(value.real) and math.isfinite(value.imag):
            residuals.append(abs(value))
        else:
            rejected += 1
    payload = {
        "symbol_count": len(symbols),
        "attempted_samples": attempted,
        "valid_samples": len(residuals),
        "rejected_samples": rejected,
        "sample_strategy": "deterministic_independent_product",
    }
    if not residuals:
        return _result("unknown", "medium", "no finite numerical samples", payload)
    maximum = max(residuals)
    status = "pass" if maximum <= tolerance else "fail"
    payload["max_residual"] = maximum
    return _result(
        status,
        "medium",
        "deterministic independent numerical residual check",
        payload,
    )


def density_normalization(*, expression: str, variable: str, lower: str, upper: str) -> dict:
    density = parse_expression(expression)
    symbol = sympy.Symbol(variable)
    integral = sympy.simplify(
        sympy.integrate(density, (symbol, parse_expression(lower), parse_expression(upper)))
    )
    if integral == 1:
        return _result(
            "pass",
            "hard",
            "density integral equals one",
            {"integral": "1"},
        )
    if integral.has(sympy.Integral) or integral.is_finite is not True:
        return _result(
            "unknown",
            "medium",
            "density integral could not be decided exactly",
            {"integral": str(integral)},
        )
    return _result(
        "fail",
        "hard",
        "density integral is exactly different from one",
        {"integral": str(integral)},
    )


def small_case_enumeration(
    *, expression: str, variable: str, values: list[int], expected: str = "0"
) -> dict:
    input_count = len(values)
    if input_count == 0 or input_count > 128:
        return _result(
            "unknown",
            "hard",
            "finite enumeration requires between 1 and 128 explicit values",
            {
                "input_count": input_count,
                "checked_count": 0,
                "truncated": False,
                "counterexamples": [],
            },
        )
    if any(len(str(abs(value))) > MAX_INTEGER_DIGITS for value in values):
        return _result(
            "unknown",
            "hard",
            "finite enumeration contains an oversized integer",
            {
                "input_count": input_count,
                "checked_count": 0,
                "truncated": False,
                "counterexamples": [],
            },
        )
    parsed = parse_expression(expression)
    expected_value = parse_expression(expected)
    symbol = sympy.Symbol(variable)
    failures: list[dict[str, str]] = []
    checked_count = 0
    for value in values:
        checked_count += 1
        actual = sympy.simplify(parsed.subs(symbol, int(value)))
        if sympy.simplify(actual - expected_value) != 0:
            failures.append({"value": str(value), "actual": str(actual)})
            break
    status = "fail" if failures else "pass"
    return _result(
        status,
        "hard",
        "finite cases enumerated exactly",
        {
            "input_count": input_count,
            "checked_count": checked_count,
            "truncated": False,
            "counterexamples": failures,
        },
    )


def _result(status: str, strength: str, summary: str, payload: dict) -> dict:
    return {"status": status, "strength": strength, "summary": summary, "payload": payload}


def _sample_pool(
    domain: str | None,
    samples: list[float] | None,
) -> tuple[sympy.Expr, ...]:
    if samples:
        return tuple(sympy.sympify(value) for value in samples[:16])
    if domain == "integer":
        return tuple(sympy.Integer(value) for value in (-2, -1, 0, 1, 2))
    if domain == "rational":
        return (
            sympy.Rational(-2),
            sympy.Rational(-1, 2),
            sympy.Rational(0),
            sympy.Rational(1, 2),
            sympy.Rational(2),
        )
    if domain == "natural_positive":
        return tuple(sympy.Integer(value) for value in (1, 2, 3, 4))
    if domain in {"natural", "natural_zero"}:
        return tuple(sympy.Integer(value) for value in (0, 1, 2, 3))
    if domain == "complex":
        return (
            sympy.Rational(1, 2) + sympy.I / 2,
            1 + sympy.I,
            -1 + 2 * sympy.I,
            2 - sympy.I,
        )
    return tuple(
        sympy.Rational(value)
        for value in (-2, -1, sympy.Rational(-1, 2), 0, sympy.Rational(1, 2), 1, 2)
    )
