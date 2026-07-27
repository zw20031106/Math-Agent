from __future__ import annotations

import ast
from dataclasses import dataclass
import re


MAX_EXPRESSION_CHARS = 2048
MAX_AST_NODES = 256
MAX_INTEGER_DIGITS = 256
MAX_ABS_EXPONENT = 256
MAX_NESTING_DEPTH = 64
MAX_ESTIMATED_COST = 4096
MAX_WORKER_REQUEST_BYTES = 32_768
MAX_WORKER_RESPONSE_BYTES = 1_048_576
MAX_WORKER_STDERR_BYTES = 4096
WORKER_ADDRESS_SPACE_BYTES = 768 * 1024 * 1024
WORKER_CPU_SECONDS = 3


class ExpressionLimitError(ValueError):
    """The expression exceeds a deterministic pre-computation resource limit."""


@dataclass(frozen=True)
class ExpressionInspection:
    source: str
    tree: ast.Expression
    node_count: int
    nesting_depth: int
    estimated_cost: int


def inspect_expression(expression: str) -> ExpressionInspection:
    source = str(expression).strip().replace("^", "**")
    if not source:
        raise ExpressionLimitError("expression_chars: expression is empty")
    if len(source) > MAX_EXPRESSION_CHARS:
        raise ExpressionLimitError("expression_chars: expression is too long")
    if _delimiter_depth(source) > MAX_NESTING_DEPTH:
        raise ExpressionLimitError("depth: expression nesting is too deep")
    if any(
        len(match.group(0).lstrip("0") or "0") > MAX_INTEGER_DIGITS
        for match in re.finditer(r"(?<![A-Za-z0-9_.])\d+", source)
    ):
        raise ExpressionLimitError("integer_digits: integer literal is too long")
    try:
        tree = ast.parse(source, mode="eval")
    except (RecursionError, SyntaxError) as error:
        if source.count("+") + source.count("-") > MAX_AST_NODES:
            raise ExpressionLimitError("nodes: expression has too many nodes") from error
        if isinstance(error, SyntaxError):
            raise
        raise ExpressionLimitError("depth: expression nesting is too deep") from error
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_AST_NODES:
        raise ExpressionLimitError("nodes: expression has too many nodes")
    depth = _ast_depth(tree)
    if depth > MAX_NESTING_DEPTH:
        raise ExpressionLimitError("depth: expression nesting is too deep")
    for node in nodes:
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            exponent = _numeric_literal(node.right)
            if exponent is not None and abs(exponent) > MAX_ABS_EXPONENT:
                raise ExpressionLimitError("exponent: absolute exponent is too large")
    cost = sum(_node_cost(node) for node in nodes)
    if cost > MAX_ESTIMATED_COST:
        raise ExpressionLimitError("cost: estimated expression cost is too high")
    return ExpressionInspection(source, tree, len(nodes), depth, cost)


def inspect_tool_arguments(arguments: dict) -> None:
    for key in ("expression", "left", "right", "lower", "upper", "expected"):
        value = arguments.get(key)
        if isinstance(value, str):
            inspect_expression(value)


def _delimiter_depth(source: str) -> int:
    depth = 0
    maximum = 0
    for character in source:
        if character in "([{":
            depth += 1
            maximum = max(maximum, depth)
        elif character in ")]}":
            depth = max(0, depth - 1)
    return maximum


def _ast_depth(node: ast.AST) -> int:
    children = list(ast.iter_child_nodes(node))
    return 1 + max((_ast_depth(child) for child in children), default=0)


def _numeric_literal(node: ast.AST) -> float | None:
    sign = 1.0
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        sign = -1.0 if isinstance(node.op, ast.USub) else 1.0
        node = node.operand
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    ):
        return sign * float(node.value)
    return None


def _node_cost(node: ast.AST) -> int:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
        exponent = _numeric_literal(node.right)
        return 64 if exponent is None else 4 + min(256, int(abs(exponent)))
    if isinstance(node, ast.Call):
        return 16
    if isinstance(node, ast.BinOp):
        return 4
    return 1
