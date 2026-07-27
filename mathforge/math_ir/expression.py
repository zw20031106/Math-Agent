from __future__ import annotations

import ast
from dataclasses import dataclass

import sympy

from mathforge.math_ir.domain import (
    DomainContext,
    condition_is_implied,
    parse_domain_context,
)
from mathforge.tools.resource_limits import inspect_expression
from mathforge.tools.safe_parse import parse_expression


@dataclass(frozen=True)
class ExpressionIR:
    source_text: str
    normalized_source: str
    ast: ast.Expression
    sympy_expression: sympy.Expr
    symbols: tuple[str, ...]
    explicit_domains: dict[str, str]
    derived_domain_constraints: tuple[str, ...]
    singularities: tuple[str, ...]
    context_complete: bool
    unresolved_domain_constraints: tuple[str, ...]
    ambiguities: tuple[str, ...]
    domain_conditions: tuple[sympy.Expr, ...]
    domain_context: DomainContext


def build_expression_ir(
    source_text: str,
    *,
    assumptions: list[str] | None = None,
    domains: dict[str, str] | None = None,
) -> ExpressionIR:
    inspection = inspect_expression(source_text)
    expression = parse_expression(inspection.source)
    context = parse_domain_context(assumptions or [], domains or {})
    conditions, singularities, ambiguities = _derive_conditions(
        inspection.tree.body,
        context,
    )
    unresolved = tuple(
        sorted(
            {
                _condition_text(condition)
                for condition in conditions
                if not condition_is_implied(condition, context)
            }
        )
    )
    symbols = tuple(sorted(str(symbol) for symbol in expression.free_symbols))
    sensitive_without_domain = any(
        symbol not in context.domains
        for condition in conditions
        for symbol in (str(item) for item in condition.free_symbols)
    )
    all_ambiguities = tuple(sorted(set((*context.ambiguities, *ambiguities))))
    return ExpressionIR(
        source_text=str(source_text),
        normalized_source=inspection.source,
        ast=inspection.tree,
        sympy_expression=expression,
        symbols=symbols,
        explicit_domains=dict(context.domains),
        derived_domain_constraints=tuple(
            sorted(_condition_text(item) for item in conditions)
        ),
        singularities=tuple(sorted(set(singularities))),
        context_complete=(
            context.context_complete
            and not all_ambiguities
            and not sensitive_without_domain
        ),
        unresolved_domain_constraints=unresolved,
        ambiguities=all_ambiguities,
        domain_conditions=tuple(conditions),
        domain_context=context,
    )


def _derive_conditions(
    tree: ast.AST,
    context: DomainContext,
) -> tuple[list[sympy.Expr], list[str], list[str]]:
    conditions: list[sympy.Expr] = []
    singularities: list[str] = []
    ambiguities: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.Mod)):
            divisor = _expression(node.right)
            condition = sympy.Ne(divisor, 0)
            if condition is not sympy.true:
                conditions.append(condition)
                singularities.append(str(divisor))
            if isinstance(node.op, ast.Mod) and not _integer_context(divisor, context):
                ambiguities.append("modulo_domain")
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            base = _expression(node.left)
            exponent = _expression(node.right)
            if exponent.is_number and exponent.is_negative is True:
                conditions.append(sympy.Ne(base, 0))
                singularities.append(str(base))
            if exponent.is_Rational is True and exponent.is_integer is not True:
                if _has_complex_symbol(base, context):
                    ambiguities.append("complex_fractional_power_branch")
                else:
                    conditions.append(sympy.Ge(base, 0))
            elif exponent.is_number and exponent.is_integer is not True:
                ambiguities.append("non_rational_power_domain")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id.lower()
            argument = _expression(node.args[0])
            if name in {"log", "sqrt", "tan"} and _has_complex_symbol(
                argument,
                context,
            ):
                ambiguities.append(f"complex_{name}_branch")
                continue
            if name == "log":
                conditions.append(sympy.Gt(argument, 0))
            elif name == "sqrt":
                conditions.append(sympy.Ge(argument, 0))
            elif name == "tan":
                condition = sympy.Ne(sympy.cos(argument), 0)
                conditions.append(condition)
                singularities.append(str(sympy.cos(argument)))
            elif name == "zeta":
                ambiguities.append("unsupported_domain:zeta")
    return conditions, singularities, ambiguities


def _expression(node: ast.AST) -> sympy.Expr:
    return parse_expression(ast.unparse(node))


def _has_complex_symbol(expression: sympy.Expr, context: DomainContext) -> bool:
    return any(
        context.domains.get(str(symbol)) == "complex"
        for symbol in expression.free_symbols
    )


def _integer_context(expression: sympy.Expr, context: DomainContext) -> bool:
    return all(
        context.domains.get(str(symbol))
        in {"integer", "natural", "natural_zero", "natural_positive"}
        for symbol in expression.free_symbols
    )


def _condition_text(condition: sympy.Expr) -> str:
    operators = {
        sympy.core.relational.Unequality: "!=",
        sympy.core.relational.StrictGreaterThan: ">",
        sympy.core.relational.GreaterThan: ">=",
        sympy.core.relational.StrictLessThan: "<",
        sympy.core.relational.LessThan: "<=",
        sympy.core.relational.Equality: "==",
    }
    operator = operators.get(type(condition))
    if operator is None:
        return str(condition)
    return f"{condition.lhs} {operator} {condition.rhs}"
