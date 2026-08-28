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


def _run_shadow_probe(**arguments: Any) -> dict[str, Any]:
    """Load the optional shadow implementation only when explicitly invoked."""
    from mathforge.tools.shadow_solver import run_shadow_probe

    return run_shadow_probe(**arguments)


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

    @property
    def failure_taxonomy(self) -> str:
        """Canonical E6 evidence status while retaining legacy ``status``."""

        from mathforge.verification.e6 import evidence_status

        return evidence_status(self.status, reason=self.summary)

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
    model_claimable: bool = True


_DEFINITIONS = (
    ToolDefinition(
        "deterministic_shadow_probe",
        _run_shadow_probe,
        True,
        "an exact answer for an allowlisted deterministic problem shape",
        "unsupported shapes return unknown and never form a candidate",
        "1",
        capability=VerificationCapability.EQUALITY_SYMBOLIC_UNDER_DOMAIN.value,
        claim_state=ClaimVerificationState.SEMANTICALLY_VERIFIED.value,
        model_claimable=False,
    ),
    ToolDefinition(
        "safe_parse_expression",
        safe_parse_expression,
        True,
        "restricted syntax acceptance",
        "does not prove a formula",
        "2",
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
        "2",
        capability=VerificationCapability.ALGEBRA_SIMPLIFICATION.value,
    ),
    ToolDefinition(
        "numerical_residual",
        numerical_residual,
        True,
        "finite-sample residual evidence",
        "cannot prove universal equality",
        "2",
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
        "2",
        capability=VerificationCapability.PROBABILITY_NORMALIZATION.value,
        claim_state=ClaimVerificationState.SEMANTICALLY_VERIFIED.value,
    ),
    ToolDefinition(
        "small_case_enumeration",
        small_case_enumeration,
        True,
        "the supplied finite cases",
        "cannot prove untested cases",
        "2",
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
    "deterministic_shadow_probe": {
        "problem_ir": {"type": "object", "additionalProperties": {}},
        "time_budget_seconds": {"type": "number"},
    },
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
        "domains": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
        "max_samples": {"type": "integer"},
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
        "values": {
            "type": "array",
            "items": {"type": "integer"},
            "minItems": 1,
            "maxItems": 128,
        },
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
    "deterministic_shadow_probe": {"time_budget_seconds"},
    "symbolic_equivalence": {"assumptions", "domains"},
    "numerical_residual": {
        "right",
        "tolerance",
        "samples",
        "domains",
        "max_samples",
    },
    "small_case_enumeration": {"expected"},
}

class ToolRegistry:
    def __init__(self) -> None:
        self._definitions = {definition.name: definition for definition in _DEFINITIONS}

    def names(self) -> list[str]:
        return sorted(self._definitions)

    def claimable_names(self) -> list[str]:
        return sorted(
            name
            for name, definition in self._definitions.items()
            if definition.model_claimable
        )

    def is_model_claimable(self, name: str) -> bool:
        return self.get(name).model_claimable

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
                "exposure": (
                    "model_claimable"
                    if definition.model_claimable
                    else "host_only"
                ),
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

    def validate_arguments(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> list[str]:
        self.get(name)
        if not isinstance(arguments, dict):
            return ["arguments:not_object"]
        properties = _INPUT_SCHEMAS[name]
        required = {
            key
            for key in properties
            if key not in _OPTIONAL_ARGUMENTS.get(name, set())
        }
        errors = [
            f"{key}:missing"
            for key in sorted(required - set(arguments))
        ]
        errors.extend(
            f"{key}:unexpected"
            for key in sorted(set(arguments) - set(properties))
        )
        for key in sorted(set(arguments).intersection(properties)):
            if not _matches_schema(arguments[key], properties[key]):
                errors.append(f"{key}:invalid_type")
        return errors

    def claim_prompt_examples(
        self,
        names: list[str] | tuple[str, ...],
        *,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        from mathforge.tool_prompt_examples import claim_prompt_examples

        allowed = set(self.claimable_names())
        return claim_prompt_examples(
            (name for name in names if name in allowed),
            limit=limit,
        )

    def mcp_schemas(self) -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []
        for definition in sorted(
            (
                item
                for item in self._definitions.values()
                if item.model_claimable
            ),
            key=lambda item: item.name,
        ):
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


def _matches_schema(value: Any, schema: dict[str, Any]) -> bool:
    alternatives = schema.get("anyOf")
    if isinstance(alternatives, list):
        return any(_matches_schema(value, item) for item in alternatives)
    expected = schema.get("type")
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "array":
        return (
            isinstance(value, list)
            and len(value) >= int(schema.get("minItems", 0))
            and len(value) <= int(schema.get("maxItems", len(value)))
            and all(
                _matches_schema(item, schema.get("items", {}))
                for item in value
            )
        )
    if expected == "object":
        if not isinstance(value, dict):
            return False
        additional = schema.get("additionalProperties", {})
        return all(
            isinstance(key, str) and _matches_schema(item, additional)
            for key, item in value.items()
        )
    return True
