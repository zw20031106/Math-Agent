from __future__ import annotations

import ast
import json
import re
from typing import Any

from mathforge.harness.model_candidate_contract import (
    MODEL_CANDIDATE_COMPATIBILITY_FIELDS,
    MODEL_CANDIDATE_HOST_FIELDS,
    MODEL_CANDIDATE_NONEMPTY_FIELDS,
    MODEL_CANDIDATE_OPTIONAL_FIELDS,
    MODEL_CANDIDATE_REQUIRED_FIELDS,
    LEGACY_PROOF_CANDIDATE_FIELDS,
    LEGACY_SIMPLE_CANDIDATE_FIELDS,
    LEGACY_STANDARD_CANDIDATE_FIELDS,
    MODEL_CLAIM_KINDS,
    PROOF_CANDIDATE_FIELDS,
    SIMPLE_CANDIDATE_FIELDS,
    STANDARD_CANDIDATE_FIELDS,
    MODEL_CLAIM_FIELDS,
    MODEL_CLAIM_HOST_FIELDS,
    candidate_profile_for_response_mode,
    validate_candidate_profile,
)
from mathforge.parsing.answer_extraction import (
    extract_final_answer_text,
    prepare_model_text,
    unwrap_boxed,
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
    def recover_answer_candidate(
        self,
        response: str,
        *,
        candidate_id: str,
        role: str,
        answer_type: str,
        planned_method_family: str = "",
    ) -> CandidateSolution | None:
        """Recover only a complete public answer from a damaged envelope."""

        model_text = prepare_model_text(response)
        text = (
            model_text.salvage_text
            if model_text.think_truncated
            else model_text.public_text
        )
        fields = StructuredOutputRecoveryLayer().salvage_top_level_fields(
            text,
            ("final_answer", "answer", "conclusion", "check"),
        )
        answer = next(
            (
                fields[name].strip()
                for name in ("final_answer", "answer", "conclusion")
                if isinstance(fields.get(name), str) and fields[name].strip()
            ),
            "",
        )
        if not answer:
            answer = self._extract_answer(text)
        answer = unwrap_boxed(answer)
        if not answer or len(answer) > 4096:
            return None
        check = fields.get("check")
        if isinstance(check, dict):
            check = check.get("statement")
        public_check = check.strip() if isinstance(check, str) else ""
        candidate = CandidateSolution(
            candidate_id=candidate_id,
            role=role,
            method=planned_method_family or "direct-deduction",
            final_answer=answer,
            answer_type=answer_type,
            public_solution_steps=([public_check] if public_check else []),
            solution_text=public_check,
            parse_status="semantic_answer_salvage",
            planned_method_family=planned_method_family,
            contract_deviations=[
                "protocol_envelope_unusable",
                "answer_only_salvage",
            ],
            source=self._candidate_source(candidate_id, role),
            parse_tier=CandidateParseTier.ANSWER_RECOVERED.value,
            degraded=bool(
                getattr(response, "output_budget_exceeded", False)
                or str(getattr(response, "truncation_status", "")).casefold()
                == "truncated"
                or str(getattr(response, "finish_reason", "")).casefold()
                in {"length", "length_inferred"}
            ),
            assurance="answer_salvaged",
        )
        candidate.validate()
        return candidate

    def parse(
        self,
        response: str,
        *,
        candidate_id: str,
        role: str,
        answer_type: str,
        planned_method_family: str = "",
        response_mode: str | None = None,
    ) -> CandidateSolution:
        model_text = prepare_model_text(response)
        text = model_text.public_text
        if model_text.think_truncated:
            recovered = self.recover_answer_candidate(
                model_text.salvage_text,
                candidate_id=candidate_id,
                role=role,
                answer_type=answer_type,
                planned_method_family=planned_method_family,
            )
            if recovered is not None:
                recovered.parse_status = "truncated_think_answer_salvage"
                recovered.degraded = True
                return recovered
        payload, status = self._payload(text)
        if payload is not None:
            payload, profile_deviations = self._normalize_profile_payload(
                payload,
                planned_method_family=planned_method_family,
                response_mode=response_mode,
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
                planned_method_family,
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
            assurance=(
                "answer_salvaged"
                if parse_tier == CandidateParseTier.ANSWER_RECOVERED.value
                else "standard"
            ),
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
                has_answer = bool(
                    fields.intersection({"final_answer", "answer", "conclusion"})
                )
                if (
                    not complete_profile
                    and not _REQUIRED_MODEL_FIELDS <= fields
                    and not has_answer
                ):
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
        response_mode: str | None,
    ) -> tuple[dict[str, Any], list[str]]:
        fields = set(payload)
        official_profiles = {
            frozenset(SIMPLE_CANDIDATE_FIELDS): "answer_only",
            frozenset(STANDARD_CANDIDATE_FIELDS): "worked_solution",
            frozenset(PROOF_CANDIDATE_FIELDS): "proof_full",
        }
        profile = official_profiles.get(frozenset(fields))
        if profile is not None:
            if response_mode is not None:
                expected = candidate_profile_for_response_mode(response_mode)
                if profile != expected:
                    return payload, [f"response_profile:{profile}:expected:{expected}"]
            try:
                validate_candidate_profile(payload, profile)
            except ValueError:
                return payload, [f"response_profile:{profile}:invalid"]
            return SolutionParser._host_normalize_profile(
                payload,
                profile=profile,
                planned_method_family=planned_method_family,
            ), []

        if fields == LEGACY_SIMPLE_CANDIDATE_FIELDS:
            answer = payload.get("answer")
            check = payload.get("check")
            if isinstance(answer, str) and isinstance(check, str):
                return (
                    SolutionParser._host_normalize_profile(
                        {
                            "final_answer": answer,
                            "check": {
                                "statement": check or answer,
                                "claim_kind": "reasoning",
                            },
                        },
                        profile="answer_only",
                        planned_method_family=planned_method_family,
                    ),
                    ["legacy_profile:answer_check"],
                )
        if fields == LEGACY_STANDARD_CANDIDATE_FIELDS:
            answer = payload.get("answer")
            method = payload.get("method")
            steps = payload.get("steps")
            uncertainties = payload.get("uncertainties")
            if (
                isinstance(answer, str)
                and isinstance(method, str)
                and isinstance(steps, list)
                and all(isinstance(item, str) for item in steps)
                and isinstance(uncertainties, list)
                and all(isinstance(item, str) for item in uncertainties)
            ):
                semantic_steps = [
                    {
                        "statement": statement,
                        "claim_kind": "reasoning",
                        "depends_on": ([index - 1] if index else []),
                    }
                    for index, statement in enumerate(steps)
                ]
                return (
                    SolutionParser._host_normalize_profile(
                        {
                            "final_answer": answer,
                            "method": method,
                            "steps": semantic_steps,
                            "uncertainties": uncertainties,
                        },
                        profile="worked_solution",
                        planned_method_family=planned_method_family,
                    ),
                    ["legacy_profile:answer_steps"],
                )
        if fields == LEGACY_PROOF_CANDIDATE_FIELDS:
            conclusion = payload.get("conclusion")
            method = payload.get("method")
            proof_steps = payload.get("proof_steps")
            open_conditions = payload.get("open_conditions")
            if (
                isinstance(conclusion, str)
                and isinstance(method, str)
                and isinstance(proof_steps, list)
                and isinstance(open_conditions, list)
                and all(isinstance(item, str) for item in open_conditions)
            ):
                semantic_steps = []
                for index, item in enumerate(proof_steps):
                    if not isinstance(item, dict):
                        return payload, ["legacy_profile:proof:invalid"]
                    statement = item.get("statement")
                    dependencies = item.get("depends_on", [])
                    if not isinstance(statement, str) or not isinstance(
                        dependencies,
                        list,
                    ):
                        return payload, ["legacy_profile:proof:invalid"]
                    semantic_steps.append(
                        {
                            "statement": statement,
                            "claim_kind": "reasoning",
                            "depends_on": [
                                dependency
                                for dependency in dependencies
                                if type(dependency) is int and dependency < index
                            ],
                        }
                    )
                if len(semantic_steps) >= 2:
                    return (
                        SolutionParser._host_normalize_profile(
                            {
                                "final_answer": conclusion,
                                "method": method,
                                "proof_steps": semantic_steps,
                                "open_conditions": open_conditions,
                            },
                            profile="proof_full",
                            planned_method_family=planned_method_family,
                        ),
                        ["legacy_profile:conclusion_proof_steps"],
                    )
        return payload, []

    @staticmethod
    def _host_normalize_profile(
        payload: dict[str, Any],
        *,
        profile: str,
        planned_method_family: str,
    ) -> dict[str, Any]:
        if profile == "answer_only":
            check = payload["check"]
            statement = str(check["statement"]).strip()
            claim_kind = str(check["claim_kind"])
            method = planned_method_family or "direct-deduction"
            steps = [(statement, claim_kind, [])]
            unresolved: list[str] = []
        else:
            field = "steps" if profile == "worked_solution" else "proof_steps"
            method = str(payload["method"]).strip()
            steps = [
                (
                    str(item["statement"]).strip(),
                    str(item["claim_kind"]),
                    [f"host-c{dependency + 1}" for dependency in item["depends_on"]],
                )
                for item in payload[field]
            ]
            unresolved = list(
                payload[
                    "uncertainties"
                    if profile == "worked_solution"
                    else "open_conditions"
                ]
            )
        statements = [statement for statement, _, _ in steps]
        claims = [
            {
                "statement": statement,
                "depends_on": dependencies,
                "check_type": SolutionParser._check_type_for_claim_kind(claim_kind),
                "claim_kind": claim_kind,
                "importance": (
                    "critical" if index == len(steps) else "supporting"
                ),
            }
            for index, (statement, claim_kind, dependencies) in enumerate(
                steps,
                start=1,
            )
        ]
        return {
            "_host_normalized_profile": profile,
            "method": method,
            "final_answer": payload["final_answer"],
            "public_solution_steps": statements,
            "claims": claims,
            "solution_text": "\n".join(statements),
            "assumptions": [],
            "theorems": [],
            "unresolved_obligations": unresolved,
        }

    @staticmethod
    def _check_type_for_claim_kind(claim_kind: str) -> str:
        return {
            "equality": "symbolic_equivalence",
            "matrix_shape": "matrix_shape_check",
            "probability_normalization": "density_normalization",
            "finite_case": "small_case_enumeration",
            "answer_shape": "answer_type_check",
        }.get(claim_kind, claim_kind if claim_kind in _ALLOWED_CHECK_TYPES else "reasoning")

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
        planned_method_family: str = "",
    ) -> CandidateSolution:
        deviations = list(initial_deviations or [])
        host_normalized_profile = str(
            payload.pop("_host_normalized_profile", "")
        ).strip()
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
        if not host_normalized_profile:
            deviations.extend(
                f"{name}:host_owned"
                for name in sorted(host_fields.intersection(payload))
            )
        allowed_fields = (
            host_fields
            | MODEL_CANDIDATE_REQUIRED_FIELDS
            | MODEL_CANDIDATE_OPTIONAL_FIELDS
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
        model_claim_ids = {
            str(item.get("claim_id", "")).strip(): f"host-c{index + 1}"
            for index, item in enumerate(raw_claims)
            if isinstance(item, dict) and str(item.get("claim_id", "")).strip()
        }
        for index, item in enumerate(raw_claims):
            prefix = f"claims[{index}]"
            if not isinstance(item, dict):
                deviations.append(f"{prefix}:type")
                continue
            claim_model_fields = MODEL_CLAIM_FIELDS
            claim_host_fields = MODEL_CLAIM_HOST_FIELDS
            if not host_normalized_profile:
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
                check_suggestion = "reasoning"
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
            claim_kind = SolutionParser._model_string(
                item,
                "claim_kind",
                derive_claim_kind(check_suggestion),
                deviations,
                prefix=prefix,
            )
            if claim_kind not in MODEL_CLAIM_KINDS:
                deviations.append(f"{prefix}.claim_kind:value")
                claim_kind = derive_claim_kind(check_suggestion)
            raw_dependencies = SolutionParser._model_string_list(
                item,
                "depends_on",
                deviations,
                prefix=prefix,
            )
            dependencies = [
                model_claim_ids.get(dependency, dependency)
                for dependency in raw_dependencies
            ]
            claims.append(
                Claim(
                    claim_id=f"host-c{index + 1}",
                    statement=SolutionParser._model_string(
                        item,
                        "statement",
                        "",
                        deviations,
                        prefix=prefix,
                    ),
                    depends_on=dependencies,
                    check_type=check_suggestion,
                    importance=importance,
                    claim_kind=claim_kind,
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
        if raw_method_steps and not host_normalized_profile:
            deviations.append("method_steps:host_owned")
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
        final_answer = unwrap_boxed(final_answer)
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
        if not claims:
            claims = [
                Claim(
                    claim_id=f"host-c{index}",
                    statement=statement,
                    depends_on=([f"host-c{index - 1}"] if index > 1 else []),
                    check_type="reasoning",
                    importance=(
                        "critical"
                        if index == len(public_solution_steps)
                        else "supporting"
                    ),
                    claim_kind=derive_claim_kind("reasoning"),
                )
                for index, statement in enumerate(public_solution_steps, start=1)
            ]
        if not method_steps and claims:
            method_steps = [
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
                for index, claim in enumerate(claims, start=1)
            ]
        parse_tier = SolutionParser._candidate_parse_tier(
            status,
            deviations,
            final_answer,
            public_solution_steps,
            claims,
        )
        candidate = CandidateSolution(
            candidate_id=candidate_id,
            role=role,
            method=SolutionParser._model_string(
                payload,
                "method",
                planned_method_family or "unspecified",
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
            planned_method_family=planned_method_family,
            contract_deviations=sorted(set(deviations)),
            method_steps=method_steps,
            source=SolutionParser._candidate_source(candidate_id, role),
            parse_tier=parse_tier,
            degraded="truncated" in status,
            assurance=(
                "answer_salvaged"
                if parse_tier == CandidateParseTier.ANSWER_RECOVERED.value
                else "standard"
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
        return extract_final_answer_text(text, fallback_last_line=False)

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
    if "truncated" in status:
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
    integrity = candidate_response_integrity(candidate)
    if integrity == "truncated":
        return "candidate_json_incomplete", not bool(candidate.final_answer.strip())
    if candidate.parse_tier == CandidateParseTier.STRICT.value:
        return "strict_candidate_json", False
    if candidate.parse_tier == CandidateParseTier.RECOVERED.value:
        return "recovered_candidate_json", False
    if candidate.parse_tier == CandidateParseTier.ANSWER_RECOVERED.value:
        return "answer_recovered_candidate", False
    if integrity == "empty":
        return "empty_response", True
    if integrity == "malformed":
        return "candidate_json_invalid", True
    if integrity == "natural_language":
        return "candidate_non_json", True
    if integrity == "schema_violation":
        return "candidate_schema_invalid", True
    if integrity == "complete":
        return "strict_candidate_json", False
    raise ValueError("unknown candidate response integrity")
