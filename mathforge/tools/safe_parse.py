from __future__ import annotations

import ast
import re

import sympy


_FUNCTIONS = {
    "abs": sympy.Abs,
    "Abs": sympy.Abs,
    "cos": sympy.cos,
    "exp": sympy.exp,
    "log": sympy.log,
    "sin": sympy.sin,
    "sqrt": sympy.sqrt,
    "tan": sympy.tan,
}
_CONSTANTS = {"E": sympy.E, "pi": sympy.pi}
_BINARY = {
    ast.Add: lambda left, right: left + right,
    ast.Sub: lambda left, right: left - right,
    ast.Mult: lambda left, right: left * right,
    ast.Div: lambda left, right: left / right,
    ast.Pow: lambda left, right: left**right,
    ast.Mod: lambda left, right: left % right,
}


class UnsafeExpression(ValueError):
    pass


def parse_expression(expression: str) -> sympy.Expr:
    source = str(expression).strip().replace("^", "**")
    if not source or len(source) > 2048:
        raise UnsafeExpression("expression is empty or too long")
    tree = ast.parse(source, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 256:
        raise UnsafeExpression("expression is too complex")
    return _convert(tree.body)


def _convert(node: ast.AST) -> sympy.Expr:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return sympy.sympify(node.value)
    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", node.id):
            raise UnsafeExpression("invalid symbol")
        return sympy.Symbol(node.id)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        return _BINARY[type(node.op)](_convert(node.left), _convert(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _convert(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        function = _FUNCTIONS.get(node.func.id)
        if function is None or node.keywords or len(node.args) != 1:
            raise UnsafeExpression("function is not allowed")
        return function(_convert(node.args[0]))
    raise UnsafeExpression(f"unsupported syntax: {type(node).__name__}")
