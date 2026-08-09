from __future__ import annotations

import ast
import json
import re
from typing import Any

from mathforge.harness.model_candidate_contract import (
    MODEL_CANDIDATE_COMPATIBILITY_FIELDS,
    MODEL_CANDIDATE_HOST_FIELDS,
    MODEL_CANDIDATE_NONEMPTY_FIELDS,
    MODEL_CANDIDATE_REQUIRED_FIELDS,
    PROOF_CANDIDATE_FIELDS,
    SIMPLE_CANDIDATE_FIELDS,
    STANDARD_CANDIDATE_FIELDS,
    MODEL_CLAIM_FIELDS,
    MODEL_CLAIM_HOST_FIELDS,
)
from mathforge.parsing.structured_output import StructuredOutputRecoveryLayer
from mathforge.harness.schemas import (
    MAX_CLAIMS,
    MAX_METHOD_STEPS,
    CandidateParseTier,
    CandidateSolution,
    CandidateSource,
    Claim,
    MethodStep,
    MethodStepKind,
    SchemaValidationError,
)
from mathforge.verification.capabilities import derive_claim_kind


_ANSWER_PATTERNS = (
    re.compile(r"(?:final\s*answer|answer)\s*[:：]\s*(.+)$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"(?:最终答案|答案)\s*[:：]\s*(.+)$", re.MULTILINE),
    re.compile(r"\\boxed\{([^{}]+)\}"),
)
_REQUIRED_MODEL_FIELDS = MODEL_CANDIDATE_REQUIRED_FIELDS
_NONEMPTY_MODEL_FIELDS = MODEL_CANDIDATE_NONEMPTY_FIELDS
_TOP_LEVEL_ALIASES = {
    "structured_method_steps": "method_steps",
    "public_steps": "public_solution_steps",
}
_CLAIM_ALIASES = {
    "id": "claim_id",
    "dependencies": "depends_on",
}
_METHOD_STEP_ALIASES = {
    "id": "step_id",
    "claims": "claim_ids",
}
_ALLOWED_CLAIM_IMPORTANCE = frozenset({"critical", "supporting"})
_ALLOWED_CHECK_TYPES = frozenset(
    {
        "reasoning",
        "definition",
        "theorem_preconditions",
        "necessity",
        "sufficiency",
        "existence",
        "uniqueness",
        "boundary",
        "interchange",
        "safe_parse_expression",
        "symbolic_equivalence",
        "simplify_expression",
        "numerical_residual",
        "matrix_shape_check",
        "density_normalization",
        "small_case_enumeration",
        "latex_syntax_check",
        "answer_type_check",
    }
)


class SolutionParser:
    def parse(
        self,
        response: str,
        *,
        candidate_id: str,
        role: str,
        answer_type: str,
        planned_method_family: str = "",
    ) -> CandidateSolution:
        text = response.strip()
        payload, status = self._payload(text)
        if payload is not None:
            payload, profile_deviations = self._normalize_profile_payload(
                payload,
                planned_method_family=planned_method_family,
            )
            payload, alias_deviations = self._normalize_aliases(payload)
            return self._from_payload(
                payload,
                text,
                candidate_id,
                role,
                answer_type,
                status,
                [*profile_deviations, *alias_deviations],
            )
        answer = self._extract_answer(text)
        parse_status = status or ("regex_answer" if answer != text else "raw_text")
        parse_tier = (
            CandidateParseTier.ANSWER_RECOVERED.value
            if answer and answer != text
            else CandidateParseTier.REJECTED.value
        )
        candidate = CandidateSolution(
            candidate_id=candidate_id,
            role=role,
            method="unspecified",
            final_answer=answer,
            answer_type=answer_type,
            public_solution_steps=self._derive_public_steps(text, answer),
            solution_text=text,
            parse_status=parse_status,
            source=self._candidate_source(candidate_id, role),
            parse_tier=parse_tier,
        )
        candidate.validate()
        return candidate

    @staticmethod
    def _payload(text: str) -> tuple[dict[str, Any] | None, str]:
        try:
            recovered = StructuredOutputRecoveryLayer().parse_object(
                text,
                truncated=SolutionParser._json_failure_status(text) == "truncated_json",
            )
            if recovered.parse_tier == "truncated_prefix":
                fields = set(recovered.value)
                complete_profile = fields in {
                    SIMPLE_CANDIDATE_FIELDS,
                    STANDARD_CANDIDATE_FIELDS,
                    PROOF_CANDIDATE_FIELDS,
                }
                if not complete_profile and not _REQUIRED_MODEL_FIELDS <= fields:
                    return None, "truncated_json"
            status = {
                "strict_json": "strict_json",
                "fenced_json": "fenced_json",
                "outer_object": "outer_json",
                "trailing_repair": "repaired_json",
                "truncated_prefix": "truncated_recovered_json",
            }[recovered.parse_tier]
            return recovered.value, status
        except ValueError:
            decoder = json.JSONDecoder()
            for match in reversed(list(re.finditer(r"\{", text))):
                try:
                    value, _ = decoder.raw_decode(text[match.start() :])
                except json.JSONDecodeError:
                    continue
                if not isinstance(value, dict):
                    continue
                fields = set(value)
                complete_profile = fields in {
                    SIMPLE_CANDIDATE_FIELDS,
                    STANDARD_CANDIDATE_FIELDS,
                    PROOF_CANDIDATE_FIELDS,
                }
                if complete_profile or _REQUIRED_MODEL_FIELDS <= fields:
                    return value, "outer_json"
            repaired = re.sub(r",\s*([}\]])", r"\1", text)
            try:
                value = ast.literal_eval(repaired)
                return (
                    (value, "repaired_json")
                    if isinstance(value, dict)
                    else (None, "")
                )
            except (ValueError, SyntaxError):
                return None, SolutionParser._json_failure_status(text)

    @staticmethod
    def _normalize_profile_payload(
        payload: dict[str, Any],
        *,
        planned_method_family: str,
    ) -> tuple[dict[str, Any], list[str]]:
        fields = set(payload)
        if fields == SIMPLE_CANDIDATE_FIELDS:
            answer = payload.get("answer")
            check = payload.get("check")
            if not isinstance(answer, str) or not isinstance(check, str):
                return payload, []
            statement = check.strip() or f"The stated answer is {answer.strip()}."
            return (
                {
                    "method": planned_method_family or "direct-deduction",
                    "final_answer": answer,
                    "public_solution_steps": [statement],
                    "claims": [
                        {
                            "claim_id": "host-c1",
                            "statement": statement,
                            "depends_on": [],
                            "check_type": "reasoning",
                            "importance": "critical",
                        }
                    ],
                    "solution_text": statement,
                    "assumptions": [],
                    "theorems": [],
                    "unresolved_obligations": [],
                },
                ["model_profile:simple:host_normalized"],
            )
        if fields == STANDARD_CANDIDATE_FIELDS:
            answer = payload.get("answer")
            method = payload.get("method")
            steps = payload.get("steps")
            uncertainties = payload.get("uncertainties")
            if not (
                isinstance(answer, str)
                and isinstance(method, str)
                and isinstance(steps, list)
                and all(isinstance(item, str) for item in steps)
                and isinstance(uncertainties, list)
                and all(isinstance(item, str) for item in uncertainties)
            ):
                return payload, []
            public_steps = [item.strip() for item in steps if item.strip()]
            claims = [
                {
                    "claim_id": f"host-c{index}",
                    "statement": statement,
                    "depends_on": ([f"host-c{index - 1}"] if index > 1 else []),
                    "check_type": "reasoning",
                    "importance": (
                        "critical" if index == len(public_steps) else "supporting"
                    ),
                }
                for index, statement in enumerate(public_steps, start=1)
            ]
            return (
                {
                    "method": method,
                    "final_answer": answer,
                    "public_solution_steps": public_steps,
                    "claims": claims,
                    "solution_text": "\n".join(public_steps),
                    "assumptions": [],
                    "theorems": [],
                    "unresolved_obligations": list(uncertainties),
                },
                ["model_profile:standard:host_normalized"],
            )
        if fields == PROOF_CANDIDATE_FIELDS:
            conclusion = payload.get("conclusion")
            method = payload.get("method")
            proof_steps = payload.get("proof_steps")
            open_conditions = payload.get("open_conditions")
            if not (
                isinstance(conclusion, str)
                and isinstance(method, str)
                and isinstance(proof_steps, list)
                and isinstance(open_conditions, list)
                and all(isinstance(item, str) for item in open_conditions)
            ):
                return payload, []
            statements: list[str] = []
            dependencies: list[list[str]] = []
            for index, item in enumerate(proof_steps):
                if not isinstance(item, dict) or set(item) != {
                    "statement",
                    "depends_on",
                }:
                    return payload, []
                statement = item.get("statement")
                raw_dependencies = item.get("depends_on")
                if not isinstance(statement, str) or not isinstance(
                    raw_dependencies, list
                ):
                    return payload, []
                normalized_dependencies: list[str] = []
                for dependency in raw_dependencies:
                    if type(dependency) is int and 0 <= dependency < index:
                        normalized_dependencies.append(f"host-p{dependency + 1}")
                    elif (
                        isinstance(dependency, str)
                        and re.fullmatch(r"(?:host-)?p\d+", dependency)
                    ):
                        number = int(re.search(r"\d+", dependency).group(0))
                        if 1 <= number <= index:
                            normalized_dependencies.append(f"host-p{number}")
                statements.append(statement.strip())
                dependencies.append(normalized_dependencies)
            claims = [
                {
                    "claim_id": f"host-p{index}",
                    "statement": statement,
                    "depends_on": dependencies[index - 1],
                    "check_type": "reasoning",
                    "importance": (
                        "critical" if index == len(statements) else "supporting"
                    ),
                }
                for index, statement in enumerate(statements, start=1)
            ]
            return (
                {
                    "method": method,
                    "final_answer": conclusion,
                    "public_solution_steps": statements,
                    "claims": claims,
                    "solution_text": "\n".join(statements),
                    "assumptions": [],
                    "theorems": [],
                    "unresolved_obligations": list(open_conditions),
                },
                ["model_profile:proof:host_normalized"],
            )
        return payload, []

    @staticmethod
    def _json_failure_status(text: str) -> str:
        candidate = text.lstrip()
        if not candidate.startswith("{"):
            return ""
        stack: list[str] = []
        in_string = False
        escaped = False
        pairs = {"}": "{", "]": "["}
        for character in candidate:
            if in_string:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    in_string = False
                continue
            if character == '"':
                in_string = True
            elif character in "[{":
                stack.append(character)
            elif character in "]}":
                if not stack or stack.pop() != pairs[character]:
                    return "malformed_json"
        if in_string or stack:
            return "truncated_json"
        return "malformed_json"
    @staticmethod
    def _normalize_aliases(
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        normalized = dict(payload)
        deviations: list[str] = []
        SolutionParser._normalize_object_aliases(
            normalized,
            _TOP_LEVEL_ALIASES,
            deviations,
            prefix="",
        )
        claims = normalized.get("claims")
        if isinstance(claims, list):
            normalized_claims: list[Any] = []
            for index, item in enumerate(claims):
                if isinstance(item, dict):
                    normalized_item = dict(item)
                    SolutionParser._normalize_object_aliases(
                        normalized_item,
                        _CLAIM_ALIASES,
                        deviations,
                        prefix=f"claims[{index}]",
                    )
                    normalized_claims.append(normalized_item)
                else:
                    normalized_claims.append(item)
            normalized["claims"] = normalized_claims
        method_steps = normalized.get("method_steps")
        if isinstance(method_steps, list):
            normalized_steps: list[Any] = []
            for index, item in enumerate(method_steps):
                if isinstance(item, dict):
                    normalized_item = dict(item)
                    SolutionParser._normalize_object_aliases(
                        normalized_item,
                        _METHOD_STEP_ALIASES,
                        deviations,
                        prefix=f"method_steps[{index}]",
                    )
                    normalized_steps.append(normalized_item)
                else:
                    normalized_steps.append(item)
            normalized["method_steps"] = normalized_steps
        return normalized, deviations

    @staticmethod
    def _normalize_object_aliases(
        payload: dict[str, Any],
        aliases: dict[str, str],
        deviations: list[str],
        *,
        prefix: str,
    ) -> None:
        for alias, canonical in aliases.items():
            if alias not in payload:
                continue
            label = f"{prefix}.{alias}" if prefix else alias
            if canonical not in payload:
                payload[canonical] = payload[alias]
                deviations.append(f"{label}:alias_normalized:{canonical}")
            elif payload[canonical] != payload[alias]:
                deviations.append(f"{label}:alias_conflict:{canonical}")
            else:
                deviations.append(f"{label}:alias_duplicate:{canonical}")
            payload.pop(alias, None)

    @staticmethod
    def _from_payload(
        payload: dict[str, Any],
        raw_text: str,
        candidate_id: str,
        role: str,
        answer_type: str,
        status: str,
        initial_deviations: list[str] | None = None,
    ) -> CandidateSolution:
        deviations = list(initial_deviations or [])
        missing_fields = sorted(_REQUIRED_MODEL_FIELDS - set(payload))
        deviations.extend(f"{name}:missing" for name in missing_fields)
        empty_fields = sorted(
            name
            for name in _NONEMPTY_MODEL_FIELDS.intersection(payload)
            if payload[name] is None or payload[name] == "" or payload[name] == []
        )
        deviations.extend(f"{name}:empty" for name in empty_fields)
        if missing_fields or empty_fields:
            status = (
                "incomplete_json"
                if status == "strict_json"
                else f"{status}:incomplete_candidate"
            )
        host_fields = MODEL_CANDIDATE_HOST_FIELDS
        deviations.extend(
            f"{name}:host_owned" for name in sorted(host_fields.intersection(payload))
        )
        allowed_fields = (
            host_fields
            | MODEL_CANDIDATE_REQUIRED_FIELDS
            | MODEL_CANDIDATE_COMPATIBILITY_FIELDS
        )
        deviations.extend(
            f"{name}:ignored" for name in sorted(set(payload) - allowed_fields)
        )
        raw_claims = payload.get("claims", [])
        claims: list[Claim] = []
        if not isinstance(raw_claims, list):
            deviations.append("claims:type")
            raw_claims = []
        if len(raw_claims) > MAX_CLAIMS:
            raise SchemaValidationError(f"claim count exceeds {MAX_CLAIMS}")
        for index, item in enumerate(raw_claims):
            prefix = f"claims[{index}]"
            if not isinstance(item, dict):
                deviations.append(f"{prefix}:type")
                continue
            claim_model_fields = MODEL_CLAIM_FIELDS
            claim_host_fields = MODEL_CLAIM_HOST_FIELDS
            deviations.extend(
                f"{prefix}.{name}:host_owned"
                for name in sorted(claim_host_fields.intersection(item))
            )
            deviations.extend(
                f"{prefix}.{name}:ignored"
                for name in sorted(set(item) - claim_model_fields - claim_host_fields)
            )
            check_suggestion = SolutionParser._model_string(
                item,
                "check_type",
                "reasoning",
                deviations,
                prefix=prefix,
            )
            if check_suggestion not in _ALLOWED_CHECK_TYPES:
                deviations.append(f"{prefix}.check_type:value")
            importance = SolutionParser._model_string(
                item,
                "importance",
                "supporting",
                deviations,
                prefix=prefix,
            )
            if importance not in _ALLOWED_CLAIM_IMPORTANCE:
                deviations.append(f"{prefix}.importance:value")
                importance = "supporting"
            claims.append(
                Claim(
                    claim_id=SolutionParser._model_string(
                        item,
                        "claim_id",
                        f"c{index + 1}",
                        deviations,
                        prefix=prefix,
                    ),
                    statement=SolutionParser._model_string(
                        item,
                        "statement",
                        "",
                        deviations,
                        prefix=prefix,
                    ),
                    depends_on=SolutionParser._model_string_list(
                        item,
                        "depends_on",
                        deviations,
                        prefix=prefix,
                    ),
                    check_type=check_suggestion,
                    importance=importance,
                    claim_kind=derive_claim_kind(check_suggestion),
                )
            )
        raw_method_steps = payload.get("method_steps", [])
        method_steps: list[MethodStep] = []
        if not isinstance(raw_method_steps, list):
            deviations.append("method_steps:type")
            raw_method_steps = []
        if len(raw_method_steps) > MAX_METHOD_STEPS:
            raise SchemaValidationError(
                f"method step count exceeds {MAX_METHOD_STEPS}"
            )
        valid_claim_ids = {claim.claim_id for claim in claims}
        valid_kinds = {item.value for item in MethodStepKind}
        for index, item in enumerate(raw_method_steps):
            prefix = f"method_steps[{index}]"
            if not isinstance(item, dict):
                deviations.append(f"{prefix}:type")
                continue
            allowed_step_fields = {"step_id", "kind", "claim_ids", "theorem"}
            deviations.extend(
                f"{prefix}.{name}:ignored"
                for name in sorted(set(item) - allowed_step_fields)
            )
            step_id = SolutionParser._model_string(
                item,
                "step_id",
                f"s{index + 1}",
                deviations,
                prefix=prefix,
            )
            kind = SolutionParser._model_string(
                item,
                "kind",
                MethodStepKind.OTHER.value,
                deviations,
                prefix=prefix,
            )
            if kind not in valid_kinds:
                deviations.append(f"{prefix}.kind:value")
                kind = MethodStepKind.OTHER.value
            claim_ids = SolutionParser._model_string_list(
                item,
                "claim_ids",
                deviations,
                prefix=prefix,
            )
            unknown_claim_ids = sorted(set(claim_ids) - valid_claim_ids)
            if unknown_claim_ids:
                deviations.append(f"{prefix}.claim_ids:unknown")
                claim_ids = [
                    claim_id
                    for claim_id in claim_ids
                    if claim_id in valid_claim_ids
                ]
            method_steps.append(
                MethodStep(
                    step_id=step_id,
                    kind=kind,
                    claim_ids=claim_ids,
                    theorem=SolutionParser._model_string(
                        item,
                        "theorem",
                        "",
                        deviations,
                        prefix=prefix,
                    ),
                )
            )
        if not method_steps and claims:
            for index, claim in enumerate(claims, start=1):
                method_steps.append(
                    MethodStep(
                        step_id=f"host-s{index}",
                        kind=(
                            MethodStepKind.CONCLUSION.value
                            if claim.importance == "critical"
                            else MethodStepKind.OTHER.value
                        ),
                        claim_ids=[claim.claim_id],
                        theorem="",
                    )
                )
        final_answer = SolutionParser._model_string(
            payload,
            "final_answer",
            "",
            deviations,
        ).strip()
        solution_text = SolutionParser._model_string(
            payload,
            "solution_text",
            raw_text,
            deviations,
        ).strip()
        if SolutionParser._is_json_object_text(solution_text):
            deviations.append("solution_text:json_wrapper")
        if not final_answer:
            final_answer = SolutionParser._extract_answer(solution_text)
        public_solution_steps = SolutionParser._model_string_list(
            payload,
            "public_solution_steps",
            deviations,
        )
        if not public_solution_steps:
            public_solution_steps = SolutionParser._derive_public_steps(
                solution_text,
                final_answer,
                claims=claims,
            )
        candidate = CandidateSolution(
            candidate_id=candidate_id,
            role=role,
            method=SolutionParser._model_string(
                payload,
                "method",
                "unspecified",
                deviations,
            ),
            final_answer=final_answer,
            answer_type=answer_type,
            assumptions=SolutionParser._model_string_list(
                payload,
                "assumptions",
                deviations,
            ),
            theorems=SolutionParser._model_string_list(
                payload,
                "theorems",
                deviations,
            ),
            claims=claims,
            public_solution_steps=public_solution_steps,
            solution_text=solution_text,
            unresolved_obligations=SolutionParser._model_string_list(
                payload,
                "unresolved_obligations",
                deviations,
            ),
            parse_status=status,
            contract_deviations=sorted(set(deviations)),
            method_steps=method_steps,
            source=SolutionParser._candidate_source(candidate_id, role),
            parse_tier=SolutionParser._candidate_parse_tier(
                status,
                deviations,
                final_answer,
                public_solution_steps,
                claims,
            ),
        )
        candidate.validate()
        return candidate

    @staticmethod
    def _derive_public_steps(
        solution_text: str,
        final_answer: str,
        *,
        claims: list[Claim] | None = None,
    ) -> list[str]:
        steps = [
            line.strip()
            for line in solution_text.splitlines()
            if line.strip()
            and not re.fullmatch(
                r"(?:(?:final\s*)?answer|最终答案|答案)\s*[:：].*",
                line.strip(),
                re.IGNORECASE,
            )
        ]
        if not steps:
            steps = [
                claim.statement.strip()
                for claim in claims or []
                if claim.statement.strip()
            ]
        if not steps and final_answer.strip():
            steps = [f"Final answer: {final_answer.strip()}"]
        return steps

    @staticmethod
    def _model_string(
        payload: dict[str, Any],
        name: str,
        default: str,
        deviations: list[str],
        *,
        prefix: str = "",
    ) -> str:
        if name not in payload:
            return default
        value = payload[name]
        if isinstance(value, str):
            return value
        label = f"{prefix}.{name}" if prefix else name
        deviations.append(f"{label}:type")
        return default

    @staticmethod
    def _model_string_list(
        payload: dict[str, Any],
        name: str,
        deviations: list[str],
        *,
        prefix: str = "",
    ) -> list[str]:
        if name not in payload:
            return []
        value = payload[name]
        label = f"{prefix}.{name}" if prefix else name
        if not isinstance(value, list):
            deviations.append(f"{label}:type")
            return []
        result: list[str] = []
        for index, item in enumerate(value):
            if isinstance(item, str):
                result.append(item)
            else:
                deviations.append(f"{label}[{index}]:type")
        return result

    @staticmethod
    def _extract_answer(text: str) -> str:
        for pattern in _ANSWER_PATTERNS:
            matches = pattern.findall(text)
            if matches:
                return str(matches[-1]).strip()
        return text.strip()

    @staticmethod
    def _is_json_object_text(text: str) -> bool:
        try:
            return isinstance(json.loads(text.strip()), dict)
        except (json.JSONDecodeError, TypeError):
            return False

    @staticmethod
    def _candidate_source(candidate_id: str, role: str) -> str:
        if candidate_id.startswith("lemma-round-"):
            return CandidateSource.LEMMA_GUIDED.value
        return {
            "PrimarySolver": CandidateSource.LLM_PRIMARY.value,
            "AlternativeSolver": CandidateSource.LLM_ALTERNATIVE.value,
            "RepairAgent": CandidateSource.LLM_REPAIR.value,
            "LLMFinalizer": CandidateSource.LLM_FINALIZER.value,
        }.get(role, CandidateSource.LLM_PRIMARY.value)

    @staticmethod
    def _candidate_parse_tier(
        status: str,
        deviations: list[str],
        final_answer: str,
        public_solution_steps: list[str],
        claims: list[Claim],
    ) -> str:
        if status == "strict_json" and not deviations:
            return CandidateParseTier.STRICT.value
        if final_answer and public_solution_steps and claims:
            return CandidateParseTier.RECOVERED.value
        if final_answer and public_solution_steps:
            return CandidateParseTier.ANSWER_RECOVERED.value
        return CandidateParseTier.REJECTED.value


def candidate_response_integrity(candidate: CandidateSolution) -> str:
    status = str(candidate.parse_status)
    if (
        status == "raw_text"
        and not candidate.final_answer.strip()
        and not candidate.solution_text.strip()
    ):
        return "empty"
    if status == "truncated_json":
        return "truncated"
    if status == "malformed_json":
        return "malformed"
    if status in {"raw_text", "regex_answer"}:
        return "natural_language"
    if (
        status == "incomplete_json"
        or "incomplete_candidate" in status
        or candidate.contract_deviations
        or status != "strict_json"
    ):
        return "schema_violation"
    return "complete"


def candidate_response_validation(
    candidate: CandidateSolution,
) -> tuple[str, bool]:
    if "solution_text:json_wrapper" in candidate.contract_deviations:
        return "candidate_schema_invalid", True
    if candidate.parse_tier == CandidateParseTier.STRICT.value:
        return "strict_candidate_json", False
    if candidate.parse_tier == CandidateParseTier.RECOVERED.value:
        return "recovered_candidate_json", False
    if candidate.parse_tier == CandidateParseTier.ANSWER_RECOVERED.value:
        return "answer_recovered_candidate", False
    integrity = candidate_response_integrity(candidate)
    if integrity == "empty":
        return "empty_response", True
    if integrity == "truncated":
        return "candidate_json_incomplete", True
    if integrity == "malformed":
        return "candidate_json_invalid", True
    if integrity == "natural_language":
        return "candidate_non_json", True
    if integrity == "schema_violation":
        return "candidate_schema_invalid", True
    if integrity == "complete":
        return "strict_candidate_json", False
    raise ValueError("unknown candidate response integrity")
