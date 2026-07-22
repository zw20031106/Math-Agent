from __future__ import annotations

from itertools import islice, product
import re

import sympy

from mathforge.tools.safe_parse import parse_expression


def safe_parse_expression(*, expression: str) -> dict:
    parsed = parse_expression(expression)
    return _result(
        "pass",
        "hard",
        "expression parsed by the restricted grammar",
        {"expression": str(parsed)},
    )


def simplify_expression(*, expression: str) -> dict:
    simplified = sympy.simplify(parse_expression(expression))
    return _result(
        "pass",
        "hard",
        "restricted expression simplified",
        {"simplified": str(simplified)},
    )


def symbolic_equivalence(
    *,
    left: str,
    right: str,
    assumptions: list[str] | None = None,
    domains: dict[str, str] | None = None,
) -> dict:
    difference = sympy.simplify(parse_expression(left) - parse_expression(right))
    if difference == 0:
        return _result(
            "pass",
            "hard",
            "symbolic difference simplifies to zero",
            {"difference": "0", "context_complete": True},
        )

    constraints, domain_rules, context_complete = _parse_context(
        assumptions or [], domains or {}
    )
    counterexample = _counterexample(difference, constraints, domain_rules)
    if counterexample is not None and context_complete:
        return _result(
            "fail",
            "hard",
            "a domain-valid substitution gives a nonzero difference",
            {
                "difference": str(difference),
                "counterexample": counterexample,
                "context_complete": True,
            },
        )
    payload = {
        "difference": str(difference),
        "context_complete": context_complete,
    }
    if counterexample is not None:
        payload["provisional_counterexample"] = counterexample
    return _result(
        "unknown",
        "medium",
        (
            "assumptions or domains could not be fully parsed"
            if not context_complete
            else "no domain-valid counterexample was found"
        ),
        payload,
    )


def _parse_context(
    assumptions: list[str],
    domains: dict[str, str],
) -> tuple[list[sympy.Expr], dict[sympy.Symbol, str], bool]:
    constraints: list[sympy.Expr] = []
    domain_rules: dict[sympy.Symbol, str] = {}
    complete = True
    for symbol_name, raw_domain in domains.items():
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", str(symbol_name)):
            complete = False
            continue
        domain = _normalize_domain(str(raw_domain))
        if domain is None:
            complete = False
            continue
        domain_rules[sympy.Symbol(str(symbol_name))] = domain
    for raw_assumption in assumptions:
        pieces = [
            piece.strip()
            for piece in re.split(r"\s*(?:&&|\band\b|;|；)\s*", str(raw_assumption))
            if piece.strip()
        ]
        if not pieces:
            complete = False
            continue
        for piece in pieces:
            parsed = _parse_constraint(piece)
            if parsed is None:
                complete = False
            elif isinstance(parsed, tuple):
                symbol, domain = parsed
                domain_rules[symbol] = domain
            else:
                constraints.append(parsed)
    return constraints, domain_rules, complete


def _parse_constraint(source: str):
    normalized = (
        source.strip().strip("$")
        .replace(r"\geq", ">=")
        .replace(r"\ge", ">=")
        .replace("≥", ">=")
        .replace(r"\leq", "<=")
        .replace(r"\le", "<=")
        .replace("≤", "<=")
        .replace(r"\ne", "!=")
        .replace("≠", "!=")
    )
    membership = re.fullmatch(
        r"([A-Za-z][A-Za-z0-9_]{0,31})\s*(?:\\in|∈|\bin\b)\s*(.+)",
        normalized,
        re.IGNORECASE,
    )
    if membership:
        domain = _normalize_domain(membership.group(2))
        return (sympy.Symbol(membership.group(1)), domain) if domain else None
    relation = re.fullmatch(r"(.+?)\s*(>=|<=|!=|==|=|>|<)\s*(.+)", normalized)
    if relation is None:
        return None
    try:
        left = parse_expression(relation.group(1).strip())
        right = parse_expression(relation.group(3).strip())
    except (SyntaxError, TypeError, ValueError):
        return None
    operator = relation.group(2)
    constructors = {
        ">=": sympy.Ge,
        "<=": sympy.Le,
        ">": sympy.Gt,
        "<": sympy.Lt,
        "=": sympy.Eq,
        "==": sympy.Eq,
        "!=": sympy.Ne,
    }
    return constructors[operator](left, right)


def _normalize_domain(value: str) -> str | None:
    normalized = (
        value.strip()
        .replace(r"\mathbb", "")
        .replace("{", "")
        .replace("}", "")
        .replace(" ", "")
        .lower()
    )
    aliases = {
        "r": "real",
        "real": "real",
        "reals": "real",
        "z": "integer",
        "integer": "integer",
        "integers": "integer",
        "q": "rational",
        "rational": "rational",
        "rationals": "rational",
        "n": "natural",
        "natural": "natural",
        "naturals": "natural",
        "c": "complex",
        "complex": "complex",
    }
    return aliases.get(normalized)


def _counterexample(
    expression: sympy.Expr,
    constraints: list[sympy.Expr],
    domain_rules: dict[sympy.Symbol, str],
) -> dict[str, str] | None:
    symbols = sorted(
        expression.free_symbols
        | {symbol for constraint in constraints for symbol in constraint.free_symbols}
        | set(domain_rules),
        key=str,
    )
    values = (0, 1, 2, -1, -2, sympy.Rational(1, 2))
    assignments = product(values, repeat=len(symbols)) if symbols else [()]
    for assigned in islice(assignments, 256):
        substitutions = dict(zip(symbols, assigned))
        if not _context_satisfied(substitutions, constraints, domain_rules):
            continue
        try:
            evaluated = sympy.simplify(expression.subs(substitutions))
            if evaluated.is_finite is True and evaluated != 0:
                return {
                    str(symbol): str(substitutions[symbol])
                    for symbol in symbols
                    if symbol in expression.free_symbols
                }
        except (TypeError, ValueError, ZeroDivisionError):
            continue
    return None


def _context_satisfied(
    substitutions: dict[sympy.Symbol, sympy.Expr],
    constraints: list[sympy.Expr],
    domain_rules: dict[sympy.Symbol, str],
) -> bool:
    for symbol, domain in domain_rules.items():
        value = sympy.sympify(substitutions[symbol])
        if domain == "real" and value.is_real is not True:
            return False
        if domain == "integer" and value.is_integer is not True:
            return False
        if domain == "rational" and value.is_rational is not True:
            return False
        if domain == "natural" and not (value.is_integer is True and value >= 0):
            return False
        if domain == "complex" and value.is_finite is not True:
            return False
    for constraint in constraints:
        try:
            if constraint.subs(substitutions) is not sympy.true:
                return False
        except (TypeError, ValueError):
            return False
    return True


def _result(status: str, strength: str, summary: str, payload: dict) -> dict:
    return {"status": status, "strength": strength, "summary": summary, "payload": payload}
