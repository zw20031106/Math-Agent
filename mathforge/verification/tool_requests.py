from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from mathforge.harness.schemas import CandidateSolution, Claim
from mathforge.tools.executor import ToolExecutor


@dataclass(frozen=True)
class ClaimToolRequest:
    claim_id: str
    check_suggestion: str
    tool_name: str
    status: str
    arguments: dict[str, Any]
    validation_errors: list[str]

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    @property
    def schema_valid(self) -> bool:
        return self.ready and not self.validation_errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "check_suggestion": self.check_suggestion,
            "tool_name": self.tool_name,
            "status": self.status,
            "arguments": dict(self.arguments),
            "validation_errors": list(self.validation_errors),
            "schema_valid": self.schema_valid,
        }


class ClaimToolRequestBuilder:
    """Build and validate host-owned tool requests from structured Claim IR."""

    def __init__(self, tools: ToolExecutor) -> None:
        self._tools = tools

    def build(
        self,
        candidate: CandidateSolution,
        claim: Claim,
        *,
        domains: dict[str, str] | None = None,
        assumptions: list[str] | None = None,
        selected_tools: list[str] | None = None,
    ) -> ClaimToolRequest:
        check = str(claim.check_type).strip().lower()
        if check not in self._tools.registered_tools:
            return ClaimToolRequest(
                claim.claim_id,
                check,
                "",
                "unsupported",
                {},
                [],
            )
        if selected_tools is not None and check not in set(selected_tools):
            return ClaimToolRequest(
                claim.claim_id,
                check,
                check,
                "route_not_selected",
                {},
                [],
            )
        arguments = self._arguments(
            candidate,
            check,
            claim.statement,
            domains=domains,
            assumptions=assumptions,
        )
        if arguments is None:
            return ClaimToolRequest(
                claim.claim_id,
                check,
                check,
                "argument_unavailable",
                {},
                [],
            )
        validation_errors = self._tools.validate_arguments(check, arguments)
        return ClaimToolRequest(
            claim.claim_id,
            check,
            check,
            "schema_invalid" if validation_errors else "ready",
            arguments,
            validation_errors,
        )

    @staticmethod
    def _arguments(
        candidate: CandidateSolution,
        check_type: str,
        statement: str,
        *,
        domains: dict[str, str] | None = None,
        assumptions: list[str] | None = None,
    ) -> dict[str, Any] | None:
        if check_type in {"symbolic_equivalence", "numerical_residual"}:
            parts = re.split(r"==|(?<![<>!])=(?!=)", statement, maxsplit=1)
            if len(parts) != 2 or not all(part.strip() for part in parts):
                return None
            arguments: dict[str, Any] = {
                "left": parts[0].strip(),
                "right": parts[1].strip(),
            }
            if check_type == "symbolic_equivalence":
                arguments["assumptions"] = list(
                    dict.fromkeys([*(assumptions or []), *candidate.assumptions])
                )
                arguments["domains"] = dict(domains or {})
            return arguments
        if check_type in {"safe_parse_expression", "simplify_expression"}:
            return {"expression": statement.strip()} if statement.strip() else None
        if check_type == "matrix_shape_check":
            return {"matrix": statement.strip()} if statement.strip() else None
        if check_type == "latex_syntax_check":
            return {"text": statement}
        if check_type == "answer_type_check":
            return {
                "answer": candidate.final_answer,
                "answer_type": candidate.answer_type,
            }
        if check_type == "density_normalization":
            matched = re.fullmatch(
                r"\s*density\[\s*expression=(?P<expression>[^;]+);\s*"
                r"variable=(?P<variable>[A-Za-z][A-Za-z0-9_]*);\s*"
                r"lower=(?P<lower>[^;]+);\s*upper=(?P<upper>[^\]]+)\]\s*",
                statement,
            )
            if matched is None:
                return None
            return {
                key: value.strip()
                for key, value in matched.groupdict().items()
            }
        if check_type == "small_case_enumeration":
            matched = re.fullmatch(
                r"\s*cases\[\s*variable=(?P<variable>[A-Za-z][A-Za-z0-9_]*);\s*"
                r"values=(?P<values>-?\d+(?:\s*,\s*-?\d+)*);\s*"
                r"expression=(?P<expression>[^;]+);\s*"
                r"expected=(?P<expected>[^\]]+)\]\s*",
                statement,
            )
            if matched is None:
                return None
            return {
                "variable": matched.group("variable"),
                "values": [
                    int(value.strip())
                    for value in matched.group("values").split(",")
                ],
                "expression": matched.group("expression").strip(),
                "expected": matched.group("expected").strip(),
            }
        return None


def claim_tool_statistics(records: list) -> dict[str, int | float]:
    requests = [
        record
        for record in records
        if (
            str(getattr(record, "evidence_type", "")).startswith("tool:")
            or getattr(record, "evidence_type", "") == "host:check_type_resolution"
        )
        and getattr(record, "claim_id", None) is not None
    ]
    ready = sum(
        record.invocation.get("request_status") == "ready"
        for record in requests
    )
    schema_valid = sum(
        record.invocation.get("schema_valid") is True
        for record in requests
    )
    executed = sum(
        str(record.evidence_type).startswith("tool:")
        for record in requests
    )
    total = len(requests)
    return {
        "requests": total,
        "argument_ready": ready,
        "schema_valid": schema_valid,
        "executed": executed,
        "pass": sum(record.status == "pass" for record in requests),
        "fail": sum(record.status == "fail" for record in requests),
        "unknown": sum(record.status == "unknown" for record in requests),
        "error": sum(record.status == "error" for record in requests),
        "argument_success_rate": ready / total if total else 0.0,
        "schema_success_rate": schema_valid / total if total else 0.0,
        "unknown_rate": (
            sum(record.status == "unknown" for record in requests) / total
            if total
            else 0.0
        ),
        "error_rate": (
            sum(record.status == "error" for record in requests) / total
            if total
            else 0.0
        ),
    }
