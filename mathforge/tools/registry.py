from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from mathforge.tools.formatting import answer_type_check, latex_syntax_check
from mathforge.tools.linear_algebra import matrix_shape_check
from mathforge.tools.numerical import density_normalization, numerical_residual, small_case_enumeration
from mathforge.tools.symbolic import safe_parse_expression, simplify_expression, symbolic_equivalence


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    status: str
    strength: str
    summary: str
    payload: dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "tool_name": self.tool_name,
            "status": self.status,
            "strength": self.strength,
            "summary": self.summary,
            "payload": _json_value(self.payload),
        }


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    function: Callable[..., dict]
    isolated: bool
    proves: str
    limitations: str


_DEFINITIONS = (
    ToolDefinition("safe_parse_expression", safe_parse_expression, False, "restricted syntax acceptance", "does not prove a formula"),
    ToolDefinition("symbolic_equivalence", symbolic_equivalence, True, "exact equality or an exact counterexample", "depends on declared domains"),
    ToolDefinition("simplify_expression", simplify_expression, True, "an exact algebraic simplification", "does not establish theorem conditions"),
    ToolDefinition("numerical_residual", numerical_residual, True, "finite-sample residual evidence", "cannot prove universal equality"),
    ToolDefinition("matrix_shape_check", matrix_shape_check, False, "matrix rectangularity and dimensions", "does not prove matrix identities"),
    ToolDefinition("density_normalization", density_normalization, True, "an exact integral normalization check", "does not prove nonnegativity"),
    ToolDefinition("small_case_enumeration", small_case_enumeration, True, "the supplied finite cases", "cannot prove untested cases"),
    ToolDefinition("latex_syntax_check", latex_syntax_check, False, "brace balance", "does not validate mathematical meaning"),
    ToolDefinition("answer_type_check", answer_type_check, False, "basic answer-shape conformance", "does not prove correctness"),
)


class ToolRegistry:
    def __init__(self) -> None:
        self._definitions = {definition.name: definition for definition in _DEFINITIONS}

    def names(self) -> list[str]:
        return sorted(self._definitions)

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._definitions[name]
        except KeyError as error:
            raise KeyError(f"unknown tool: {name}") from error


def run_tool_direct(name: str, arguments: dict[str, Any]) -> ToolResult:
    definition = ToolRegistry().get(name)
    raw = definition.function(**arguments)
    return ToolResult(
        tool_name=name,
        status=str(raw["status"]),
        strength=str(raw["strength"]),
        summary=str(raw["summary"]),
        payload=_json_value(raw.get("payload", {})),
    )
