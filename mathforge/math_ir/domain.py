from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

import sympy

from mathforge.tools.safe_parse import parse_expression


_DOMAIN_ALIASES = {
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
    "n0": "natural_zero",
    "naturalzero": "natural_zero",
    "nonnegativeinteger": "natural_zero",
    "n+": "natural_positive",
    "positiveinteger": "natural_positive",
    "naturalpositive": "natural_positive",
    "c": "complex",
    "complex": "complex",
}


@dataclass(frozen=True)
class DomainContext:
    domains: dict[str, str]
    constraints: tuple[sympy.Expr, ...]
    context_complete: bool
    ambiguities: tuple[str, ...]

    @property
    def predicate(self):
        predicates: list[sympy.Expr] = []
        factories = {
            "real": sympy.Q.real,
            "integer": sympy.Q.integer,
            "rational": sympy.Q.rational,
            "natural": sympy.Q.nonnegative,
            "natural_zero": sympy.Q.nonnegative,
            "natural_positive": sympy.Q.positive,
            "complex": sympy.Q.complex,
        }
        for name, domain in self.domains.items():
            symbol = sympy.Symbol(name)
            predicates.append(factories[domain](symbol))
            if domain in {"natural", "natural_zero", "natural_positive"}:
                predicates.append(sympy.Q.integer(symbol))
        relation_factories = {
            sympy.core.relational.GreaterThan: sympy.Q.nonnegative,
            sympy.core.relational.StrictGreaterThan: sympy.Q.positive,
            sympy.core.relational.LessThan: sympy.Q.nonpositive,
            sympy.core.relational.StrictLessThan: sympy.Q.negative,
            sympy.core.relational.Unequality: sympy.Q.nonzero,
        }
        for constraint in self.constraints:
            factory = relation_factories.get(type(constraint))
            if (
                factory is not None
                and isinstance(constraint.lhs, sympy.Symbol)
                and constraint.rhs == 0
            ):
                predicates.append(factory(constraint.lhs))
        return sympy.And(*predicates) if predicates else None


def parse_domain_context(
    assumptions: Iterable[str],
    domains: dict[str, str],
) -> DomainContext:
    parsed_domains: dict[str, str] = {}
    constraints: list[sympy.Expr] = []
    ambiguities: list[str] = []
    complete = True
    for symbol_name, raw_domain in domains.items():
        name = str(symbol_name)
        domain = normalize_domain(str(raw_domain))
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", name) or domain is None:
            complete = False
            ambiguities.append(f"invalid_domain:{name}")
            continue
        parsed_domains[name] = domain
        if domain == "natural":
            complete = False
            ambiguities.append(f"natural_convention:{name}")
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
            parsed = parse_constraint(piece)
            if parsed is None:
                complete = False
                ambiguities.append("unparsed_assumption")
            elif isinstance(parsed, tuple):
                symbol, domain = parsed
                parsed_domains[str(symbol)] = domain
                if domain == "natural":
                    complete = False
                    ambiguities.append(f"natural_convention:{symbol}")
            else:
                constraints.append(parsed)
    return DomainContext(
        parsed_domains,
        tuple(constraints),
        complete,
        tuple(sorted(set(ambiguities))),
    )


def normalize_domain(value: str) -> str | None:
    normalized = (
        value.strip()
        .replace(r"\mathbb", "")
        .replace("{", "")
        .replace("}", "")
        .replace(" ", "")
        .replace("_", "")
        .lower()
    )
    return _DOMAIN_ALIASES.get(normalized)


def parse_constraint(source: str):
    normalized = (
        source.strip()
        .strip("$")
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
        domain = normalize_domain(membership.group(2))
        return (sympy.Symbol(membership.group(1)), domain) if domain else None
    relation = re.fullmatch(r"(.+?)\s*(>=|<=|!=|==|=|>|<)\s*(.+)", normalized)
    if relation is None:
        return None
    try:
        left = parse_expression(relation.group(1).strip())
        right = parse_expression(relation.group(3).strip())
    except (SyntaxError, TypeError, ValueError):
        return None
    constructors = {
        ">=": sympy.Ge,
        "<=": sympy.Le,
        ">": sympy.Gt,
        "<": sympy.Lt,
        "=": sympy.Eq,
        "==": sympy.Eq,
        "!=": sympy.Ne,
    }
    return constructors[relation.group(2)](left, right)


def condition_is_implied(condition: sympy.Expr, context: DomainContext) -> bool:
    if condition is sympy.true:
        return True
    predicate = context.predicate
    if predicate is None:
        return False
    try:
        return sympy.ask(condition, predicate) is True
    except (TypeError, ValueError):
        return False


def context_satisfied(
    substitutions: dict[sympy.Symbol, sympy.Expr],
    context: DomainContext,
    extra_constraints: Iterable[sympy.Expr] = (),
) -> bool:
    for name, domain in context.domains.items():
        symbol = sympy.Symbol(name)
        if symbol not in substitutions:
            return False
        value = sympy.sympify(substitutions[symbol])
        if domain == "real" and value.is_real is not True:
            return False
        if domain == "integer" and value.is_integer is not True:
            return False
        if domain == "rational" and value.is_rational is not True:
            return False
        if domain in {"natural", "natural_zero"} and not (
            value.is_integer is True and value >= 0
        ):
            return False
        if domain == "natural_positive" and not (
            value.is_integer is True and value > 0
        ):
            return False
        if domain == "complex" and value.is_finite is not True:
            return False
    for constraint in (*context.constraints, *tuple(extra_constraints)):
        try:
            if constraint.subs(substitutions) is not sympy.true:
                return False
        except (TypeError, ValueError):
            return False
    return True
