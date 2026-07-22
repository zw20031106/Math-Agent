from __future__ import annotations

import math

import sympy

from mathforge.tools.safe_parse import parse_expression


def numerical_residual(
    *,
    left: str,
    right: str = "0",
    tolerance: float = 1e-9,
    samples: list[float] | None = None,
) -> dict:
    difference = parse_expression(left) - parse_expression(right)
    symbols = sorted(difference.free_symbols, key=str)
    points = samples or [0.5, 1.0, 2.0, -1.0]
    residuals: list[float] = []
    for point in points[:16]:
        try:
            value = complex(sympy.N(difference.subs({symbol: point for symbol in symbols})))
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if math.isfinite(value.real) and math.isfinite(value.imag):
            residuals.append(abs(value))
    if not residuals:
        return _result("unknown", "medium", "no finite numerical samples", {})
    maximum = max(residuals)
    status = "pass" if maximum <= tolerance else "fail"
    return _result(status, "medium", "deterministic numerical residual check", {"max_residual": maximum})


def density_normalization(*, expression: str, variable: str, lower: str, upper: str) -> dict:
    density = parse_expression(expression)
    symbol = sympy.Symbol(variable)
    integral = sympy.simplify(
        sympy.integrate(density, (symbol, parse_expression(lower), parse_expression(upper)))
    )
    status = "pass" if integral == 1 else "fail"
    return _result(status, "hard", "density integral compared with one", {"integral": str(integral)})


def small_case_enumeration(
    *, expression: str, variable: str, values: list[int], expected: str = "0"
) -> dict:
    parsed = parse_expression(expression)
    expected_value = parse_expression(expected)
    symbol = sympy.Symbol(variable)
    failures: list[dict[str, str]] = []
    for value in values[:128]:
        actual = sympy.simplify(parsed.subs(symbol, int(value)))
        if sympy.simplify(actual - expected_value) != 0:
            failures.append({"value": str(value), "actual": str(actual)})
            break
    status = "fail" if failures else "pass"
    return _result(status, "hard", "finite cases enumerated exactly", {"counterexamples": failures})


def _result(status: str, strength: str, summary: str, payload: dict) -> dict:
    return {"status": status, "strength": strength, "summary": summary, "payload": payload}
