from __future__ import annotations

import ast
from dataclasses import dataclass
import re
from typing import Any

from mathforge.harness.schemas import CandidateSolution, CheckSpec, Claim
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

    def to_check_spec(self) -> CheckSpec:
        spec = CheckSpec(
            tool_name=self.tool_name,
            arguments=dict(self.arguments),
            status=self.status,
            reason_code={
                "ready": "host_arguments_constructed",
                "unsupported": "unsupported_check_suggestion",
                "route_not_selected": "tool_not_selected_by_route",
                "argument_unavailable": "host_argument_reconstruction_unavailable",
                "schema_invalid": "tool_schema_validation_failed",
            }[self.status],
        )
        spec.validate()
        return spec

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
        request = self.build_fields(
            claim_id=claim.claim_id,
            check_suggestion=claim.check_type,
            statement=claim.statement,
            final_answer=candidate.final_answer,
            answer_type=candidate.answer_type,
            candidate_assumptions=candidate.assumptions,
            domains=domains,
            assumptions=assumptions,
            selected_tools=selected_tools,
        )
        claim.check_spec = request.to_check_spec()
        return request

    def build_fields(
        self,
        *,
        claim_id: str,
        check_suggestion: str,
        statement: str,
        final_answer: str = "",
        answer_type: str = "",
        candidate_assumptions: list[str] | None = None,
        domains: dict[str, str] | None = None,
        assumptions: list[str] | None = None,
        selected_tools: list[str] | None = None,
    ) -> ClaimToolRequest:
        check = str(check_suggestion).strip().lower()
        if check not in self._tools.claimable_tools:
            return ClaimToolRequest(
                claim_id,
                check,
                "",
                "unsupported",
                {},
                [],
            )
        if selected_tools is not None and check not in set(selected_tools):
            return ClaimToolRequest(
                claim_id,
                check,
                check,
                "route_not_selected",
                {},
                [],
            )
        arguments = self._arguments(
            check,
            statement,
            final_answer=final_answer,
            answer_type=answer_type,
            candidate_assumptions=candidate_assumptions,
            domains=domains,
            assumptions=assumptions,
        )
        if arguments is None:
            return ClaimToolRequest(
                claim_id,
                check,
                check,
                "argument_unavailable",
                {},
                [],
            )
        validation_errors = self._tools.validate_arguments(check, arguments)
        return ClaimToolRequest(
            claim_id,
            check,
            check,
            "schema_invalid" if validation_errors else "ready",
            arguments,
            validation_errors,
        )

    @staticmethod
    def _arguments(
        check_type: str,
        statement: str,
        *,
        final_answer: str = "",
        answer_type: str = "",
        candidate_assumptions: list[str] | None = None,
        domains: dict[str, str] | None = None,
        assumptions: list[str] | None = None,
    ) -> dict[str, Any] | None:
        if check_type in {"symbolic_equivalence", "numerical_residual"}:
            parts = _equality_parts(statement)
            if len(parts) != 2 or not all(part.strip() for part in parts):
                return None
            arguments: dict[str, Any] = {
                "left": parts[0].strip(),
                "right": parts[1].strip(),
            }
            if check_type == "symbolic_equivalence":
                arguments["assumptions"] = list(
                    dict.fromkeys(
                        [*(assumptions or []), *(candidate_assumptions or [])]
                    )
                )
                arguments["domains"] = dict(domains or {})
            elif domains:
                arguments["domains"] = dict(domains)
            return arguments
        if check_type == "safe_parse_expression":
            expression = _between(
                statement,
                r"\bexpression\s+",
                r"\s+uses\b|\s+is\b|\s+has\b|[.]$",
            )
            if not expression:
                expression = statement.strip()
            return {"expression": expression} if expression else None
        if check_type == "simplify_expression":
            expression = _between(
                statement,
                r"\bexpression\s+",
                r"\s+simplifies?\s+to\b|[.]$",
            )
            return {"expression": expression} if expression else None
        if check_type == "matrix_shape_check":
            matched = re.search(r"(\[\s*\[.*?\]\s*\])", statement)
            if matched is None:
                return None
            try:
                matrix = ast.literal_eval(matched.group(1))
            except (SyntaxError, ValueError):
                return None
            return {"matrix": matrix}
        if check_type == "latex_syntax_check":
            text = _between(
                statement,
                r"\bexpression\s+",
                r"\s+has\b|\s+uses\b|[.]$",
            )
            if not text:
                text = statement
            return {"text": text} if text else None
        if check_type == "answer_type_check":
            if not final_answer.strip() or not answer_type.strip():
                return None
            return {
                "answer": final_answer,
                "answer_type": answer_type,
            }
        if check_type == "density_normalization":
            matched = re.fullmatch(
                r"\s*density\[\s*expression=(?P<expression>[^;]+);\s*"
                r"variable=(?P<variable>[A-Za-z][A-Za-z0-9_]*);\s*"
                r"lower=(?P<lower>[^;]+);\s*upper=(?P<upper>[^\]]+)\]\s*",
                statement,
            )
            if matched is None:
                natural = re.fullmatch(
                    r"\s*The\s+density\s+(?P<expression>.+?)\s+on\s+"
                    r"\[(?P<lower>[^,\]]+),(?P<upper>[^\]]+)\]\s+"
                    r"integrates\s+to\s+one[.]?\s*",
                    statement,
                    re.I,
                )
                if natural is None:
                    return None
                variable = next(iter((domains or {"x": "R"}).keys()), "x")
                return {
                    "expression": natural.group("expression").strip(),
                    "variable": variable,
                    "lower": natural.group("lower").strip(),
                    "upper": natural.group("upper").strip(),
                }
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
                natural = re.fullmatch(
                    r"\s*(?P<expression>.+?)\s+equals\s+"
                    r"(?P<expected>.+?)\s+for\s+"
                    r"(?P<variable>[A-Za-z][A-Za-z0-9_]*)\s+in\s+"
                    r"\{(?P<values>-?\d+(?:\s*,\s*-?\d+)*)\}[.]?\s*",
                    statement,
                    re.I,
                )
                if natural is None:
                    return None
                return {
                    "variable": natural.group("variable"),
                    "values": [
                        int(value.strip())
                        for value in natural.group("values").split(",")
                    ],
                    "expression": natural.group("expression").strip(),
                    "expected": _number_word(
                        natural.group("expected").strip()
                    ),
                }
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


def _equality_parts(statement: str) -> list[str]:
    normalized = str(statement).strip()
    symbolic = re.split(r"==|(?<![<>!])=(?!=)", normalized, maxsplit=1)
    if len(symbolic) == 2:
        return [item.strip() for item in symbolic]
    natural = re.fullmatch(
        r"\s*(?P<left>.+?)\s+(?:equals|is\s+equivalent\s+to|and)\s+"
        r"(?P<right>.+?)"
        r"(?:\s+for\s+.+?|\s+have\s+zero\s+residual\s+at.+?)?[.]?\s*",
        normalized,
        re.I,
    )
    if natural is None:
        return []
    left = natural.group("left").strip()
    right = natural.group("right").strip()
    right = re.sub(
        r"\s+have\s+zero\s+residual\s+at.*$",
        "",
        right,
        flags=re.I,
    ).strip()
    return [left, right]


def _between(statement: str, start: str, end: str) -> str:
    matched = re.search(
        f"(?:{start})(?P<value>.+?)(?:{end})",
        str(statement).strip(),
        re.I,
    )
    return matched.group("value").strip() if matched is not None else ""


def _number_word(value: str) -> str:
    return {
        "zero": "0",
        "one": "1",
        "minus one": "-1",
    }.get(value.casefold(), value)


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
