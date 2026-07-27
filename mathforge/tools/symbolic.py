from __future__ import annotations

from itertools import islice, product

import sympy

from mathforge.math_ir.domain import context_satisfied
from mathforge.math_ir.expression import ExpressionIR, build_expression_ir


def safe_parse_expression(*, expression: str) -> dict:
    parsed = build_expression_ir(expression)
    return _result(
        "pass",
        "hard",
        "expression parsed by the restricted grammar",
        {
            "expression": str(parsed.sympy_expression),
            "domain_constraints": list(parsed.derived_domain_constraints),
            "singularities": list(parsed.singularities),
            "context_complete": parsed.context_complete,
        },
    )


def simplify_expression(*, expression: str) -> dict:
    parsed = build_expression_ir(expression)
    simplified = sympy.simplify(parsed.sympy_expression)
    return _result(
        "pass",
        "hard",
        "restricted expression simplified without discarding source domains",
        {
            "simplified": str(simplified),
            "domain_constraints": list(parsed.derived_domain_constraints),
            "singularities": list(parsed.singularities),
            "context_complete": parsed.context_complete,
        },
    )


def symbolic_equivalence(
    *,
    left: str,
    right: str,
    assumptions: list[str] | None = None,
    domains: dict[str, str] | None = None,
) -> dict:
    supplied_assumptions = assumptions or []
    supplied_domains = domains or {}
    left_ir = build_expression_ir(
        left,
        assumptions=supplied_assumptions,
        domains=supplied_domains,
    )
    right_ir = build_expression_ir(
        right,
        assumptions=supplied_assumptions,
        domains=supplied_domains,
    )
    context_complete = left_ir.context_complete and right_ir.context_complete
    difference = sympy.simplify(
        left_ir.sympy_expression - right_ir.sympy_expression
    )
    if context_complete and difference.has(sympy.log):
        difference = sympy.simplify(sympy.expand_log(difference, force=True))
    if difference != 0 and left_ir.domain_context.predicate is not None:
        difference = sympy.simplify(
            sympy.refine(difference, left_ir.domain_context.predicate)
        )
    if difference == 0:
        if (
            context_complete
            and left_ir.unresolved_domain_constraints
            == right_ir.unresolved_domain_constraints
        ):
            return _result(
                "pass",
                "hard",
                "symbolic difference and source domains are equivalent",
                {
                    "difference": "0",
                    "context_complete": True,
                    "conditional": bool(supplied_assumptions or supplied_domains),
                    **_domain_payload(left_ir, right_ir),
                },
            )
        return _conditional_unknown(difference, left_ir, right_ir)

    counterexample = _counterexample(difference, left_ir, right_ir)
    if counterexample is not None and context_complete:
        return _result(
            "fail",
            "hard",
            "a source-domain-valid substitution gives a nonzero difference",
            {
                "difference": str(difference),
                "counterexample": counterexample,
                "context_complete": True,
                **_domain_payload(left_ir, right_ir),
            },
        )
    payload = {
        "difference": str(difference),
        "context_complete": False,
        **_domain_payload(left_ir, right_ir),
    }
    if counterexample is not None:
        payload["provisional_counterexample"] = counterexample
    return _result(
        "unknown",
        "medium",
        (
            "assumptions, domain conventions, or function branches are incomplete"
            if not context_complete
            else "no source-domain-valid exact conclusion was established"
        ),
        payload,
    )


def _conditional_unknown(
    difference: sympy.Expr,
    left: ExpressionIR,
    right: ExpressionIR,
) -> dict:
    required_conditions = sorted(
        set(left.unresolved_domain_constraints)
        ^ set(right.unresolved_domain_constraints)
    )
    return _result(
        "unknown",
        "medium",
        "expressions are only conditionally equal because source domains differ",
        {
            "difference": str(difference),
            "context_complete": False,
            "conditional": True,
            "required_conditions": required_conditions,
            **_domain_payload(left, right),
        },
    )


def _domain_payload(left: ExpressionIR, right: ExpressionIR) -> dict:
    ambiguities = sorted(set((*left.ambiguities, *right.ambiguities)))
    return {
        "domain_sensitive": bool(
            left.derived_domain_constraints
            or right.derived_domain_constraints
            or ambiguities
        ),
        "left_domain_constraints": list(left.derived_domain_constraints),
        "right_domain_constraints": list(right.derived_domain_constraints),
        "left_singularities": list(left.singularities),
        "right_singularities": list(right.singularities),
        "domain_ambiguities": ambiguities,
    }


def _counterexample(
    expression: sympy.Expr,
    left: ExpressionIR,
    right: ExpressionIR,
) -> dict[str, str] | None:
    context = left.domain_context
    constraints = (*left.domain_conditions, *right.domain_conditions)
    symbols = sorted(
        expression.free_symbols
        | {symbol for item in constraints for symbol in item.free_symbols}
        | {sympy.Symbol(name) for name in context.domains},
        key=str,
    )
    pools = [_sample_values(context.domains.get(str(symbol), "")) for symbol in symbols]
    assignments = product(*pools) if symbols else [()]
    for assigned in islice(assignments, 256):
        substitutions = dict(zip(symbols, assigned))
        if not context_satisfied(substitutions, context, constraints):
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


def _sample_values(domain: str) -> tuple[sympy.Expr, ...]:
    if domain == "natural_positive":
        return (sympy.Integer(1), sympy.Integer(2), sympy.Integer(3))
    if domain in {"natural", "natural_zero"}:
        return (sympy.Integer(0), sympy.Integer(1), sympy.Integer(2))
    if domain == "complex":
        return (
            sympy.Integer(0),
            sympy.Integer(1),
            sympy.I,
            1 + sympy.I,
            -1 + sympy.I,
        )
    return (
        sympy.Integer(0),
        sympy.Integer(1),
        sympy.Integer(2),
        sympy.Integer(-1),
        sympy.Integer(-2),
        sympy.Rational(1, 2),
    )


def _result(status: str, strength: str, summary: str, payload: dict) -> dict:
    return {
        "status": status,
        "strength": strength,
        "summary": summary,
        "payload": payload,
    }
