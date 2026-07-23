from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from mathforge.harness.fingerprints import (
    content_tree_fingerprint,
    semantic_fingerprint,
)
from mathforge.tools.formatting import answer_type_check, latex_syntax_check
from mathforge.tools.linear_algebra import matrix_shape_check
from mathforge.tools.numerical import density_normalization, numerical_residual, small_case_enumeration
from mathforge.tools.symbolic import safe_parse_expression, simplify_expression, symbolic_equivalence
from mathforge.verification.capabilities import (
    ClaimVerificationState,
    VerificationCapability,
)


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
    tool_version: str = "1"
    capability: str = VerificationCapability.NONE.value
    claim_state: str = ClaimVerificationState.UNKNOWN.value

    def to_dict(self) -> dict:
        return {
            "tool_name": self.tool_name,
            "status": self.status,
            "strength": self.strength,
            "summary": self.summary,
            "payload": _json_value(self.payload),
            "tool_version": self.tool_version,
            "capability": self.capability,
            "claim_state": self.claim_state,
        }


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    function: Callable[..., dict]
    isolated: bool
    proves: str
    limitations: str
    version: str = "1"
    capability: str = VerificationCapability.NONE.value
    claim_state: str = ClaimVerificationState.UNKNOWN.value


_DEFINITIONS = (
    ToolDefinition(
        "safe_parse_expression",
        safe_parse_expression,
        False,
        "restricted syntax acceptance",
        "does not prove a formula",
        capability=VerificationCapability.SYNTAX_RESTRICTED_PARSE.value,
        claim_state=ClaimVerificationState.SYNTAX_CHECKED.value,
    ),
    ToolDefinition(
        "symbolic_equivalence",
        symbolic_equivalence,
        True,
        "exact equality or a domain-valid exact counterexample",
        "unparseable assumptions make non-equivalence unknown",
        "2",
        VerificationCapability.EQUALITY_SYMBOLIC_UNDER_DOMAIN.value,
        ClaimVerificationState.SEMANTICALLY_VERIFIED.value,
    ),
    ToolDefinition(
        "simplify_expression",
        simplify_expression,
        True,
        "an exact algebraic simplification",
        "does not establish theorem conditions",
        capability=VerificationCapability.ALGEBRA_SIMPLIFICATION.value,
    ),
    ToolDefinition(
        "numerical_residual",
        numerical_residual,
        True,
        "finite-sample residual evidence",
        "cannot prove universal equality",
        capability=VerificationCapability.EQUALITY_NUMERICAL_SAMPLES.value,
        claim_state=ClaimVerificationState.NUMERICALLY_SUPPORTED.value,
    ),
    ToolDefinition(
        "matrix_shape_check",
        matrix_shape_check,
        False,
        "matrix rectangularity and dimensions",
        "does not prove matrix identities",
        capability=VerificationCapability.MATRIX_SHAPE.value,
        claim_state=ClaimVerificationState.SEMANTICALLY_VERIFIED.value,
    ),
    ToolDefinition(
        "density_normalization",
        density_normalization,
        True,
        "an exact integral normalization check",
        "does not prove nonnegativity",
        capability=VerificationCapability.PROBABILITY_NORMALIZATION.value,
        claim_state=ClaimVerificationState.SEMANTICALLY_VERIFIED.value,
    ),
    ToolDefinition(
        "small_case_enumeration",
        small_case_enumeration,
        True,
        "the supplied finite cases",
        "cannot prove untested cases",
        capability=VerificationCapability.FINITE_CASE_EXACT.value,
        claim_state=ClaimVerificationState.SEMANTICALLY_VERIFIED.value,
    ),
    ToolDefinition(
        "latex_syntax_check",
        latex_syntax_check,
        False,
        "brace balance",
        "does not validate mathematical meaning",
        capability=VerificationCapability.SYNTAX_LATEX_BRACE_BALANCE.value,
        claim_state=ClaimVerificationState.SYNTAX_CHECKED.value,
    ),
    ToolDefinition(
        "answer_type_check",
        answer_type_check,
        False,
        "basic answer-shape conformance",
        "does not prove correctness",
        capability=VerificationCapability.ANSWER_SHAPE.value,
    ),
)

_INPUT_SCHEMAS: dict[str, dict[str, dict[str, Any]]] = {
    "safe_parse_expression": {
        "expression": {"type": "string"},
    },
    "symbolic_equivalence": {
        "left": {"type": "string"},
        "right": {"type": "string"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "domains": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
    },
    "simplify_expression": {
        "expression": {"type": "string"},
    },
    "numerical_residual": {
        "left": {"type": "string"},
        "right": {"type": "string"},
        "tolerance": {"type": "number"},
        "samples": {"type": "array", "items": {"type": "number"}},
    },
    "matrix_shape_check": {
        "matrix": {
            "anyOf": [
                {"type": "array", "items": {"type": "array"}},
                {"type": "string"},
            ]
        },
    },
    "density_normalization": {
        "expression": {"type": "string"},
        "variable": {"type": "string"},
        "lower": {"type": "string"},
        "upper": {"type": "string"},
    },
    "small_case_enumeration": {
        "expression": {"type": "string"},
        "variable": {"type": "string"},
        "values": {"type": "array", "items": {"type": "integer"}},
        "expected": {"type": "string"},
    },
    "latex_syntax_check": {
        "text": {"type": "string"},
    },
    "answer_type_check": {
        "answer": {"type": "string"},
        "answer_type": {"type": "string"},
    },
}

_OPTIONAL_ARGUMENTS: dict[str, set[str]] = {
    "symbolic_equivalence": {"assumptions", "domains"},
    "numerical_residual": {"right", "tolerance", "samples"},
    "small_case_enumeration": {"expected"},
}


class ToolRegistry:
    def __init__(self) -> None:
        self._definitions = {definition.name: definition for definition in _DEFINITIONS}

    def names(self) -> list[str]:
        return sorted(self._definitions)

    @property
    def fingerprint(self) -> str:
        return semantic_fingerprint(
            {
                "registry": self.mcp_schemas(),
                "source_tree": content_tree_fingerprint(
                    Path(__file__).resolve().parent,
                    "*.py",
                ),
            }
        )

    @property
    def manifest(self) -> list[dict[str, str]]:
        return [
            {
                "name": definition.name,
                "version": definition.version,
                "capability": definition.capability,
                "claim_state": definition.claim_state,
                "limitations_sha256": semantic_fingerprint(
                    {
                        "proves": definition.proves,
                        "limitations": definition.limitations,
                    }
                ),
            }
            for definition in sorted(
                self._definitions.values(),
                key=lambda item: item.name,
            )
        ]

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._definitions[name]
        except KeyError as error:
            raise KeyError(f"unknown tool: {name}") from error

    def mcp_schemas(self) -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []
        for definition in sorted(self._definitions.values(), key=lambda item: item.name):
            properties = _INPUT_SCHEMAS[definition.name]
            required = [
                name
                for name in properties
                if name not in _OPTIONAL_ARGUMENTS.get(definition.name, set())
            ]
            schemas.append(
                {
                    "name": definition.name,
                    "description": (
                        f"Version {definition.version}. Can establish: {definition.proves}. "
                        f"Limitation: {definition.limitations}."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            name: {
                                **schema,
                                "description": f"Argument {name}",
                            }
                            for name, schema in properties.items()
                        },
                        "required": required,
                        "additionalProperties": False,
                    },
                }
            )
        return schemas


def run_tool_direct(name: str, arguments: dict[str, Any]) -> ToolResult:
    definition = ToolRegistry().get(name)
    raw = definition.function(**arguments)
    return ToolResult(
        tool_name=name,
        status=str(raw["status"]),
        strength=str(raw["strength"]),
        summary=str(raw["summary"]),
        payload=_json_value(raw.get("payload", {})),
        tool_version=definition.version,
        capability=definition.capability,
        claim_state=definition.claim_state,
    )
