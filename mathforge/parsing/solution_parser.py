from __future__ import annotations

import ast
import json
import re
from typing import Any

from mathforge.harness.schemas import (
    MAX_CLAIMS,
    MAX_METHOD_STEPS,
    CandidateSolution,
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


class SolutionParser:
    def parse(
        self,
        response: str,
        *,
        candidate_id: str,
        role: str,
        answer_type: str,
    ) -> CandidateSolution:
        text = response.strip()
        payload, status = self._payload(text)
        if payload is not None:
            return self._from_payload(payload, text, candidate_id, role, answer_type, status)
        answer = self._extract_answer(text)
        parse_status = "regex_answer" if answer != text else "raw_text"
        candidate = CandidateSolution(
            candidate_id=candidate_id,
            role=role,
            method="unspecified",
            final_answer=answer,
            answer_type=answer_type,
            public_solution_steps=self._derive_public_steps(text, answer),
            solution_text=text,
            parse_status=parse_status,
        )
        candidate.validate()
        return candidate

    @staticmethod
    def _payload(text: str) -> tuple[dict[str, Any] | None, str]:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
        try:
            value = json.loads(cleaned)
            return (value, "strict_json") if isinstance(value, dict) else (None, "")
        except (json.JSONDecodeError, TypeError):
            cleaned = cleaned.strip()
        decoder = json.JSONDecoder()
        for match in re.finditer(r"\{", cleaned):
            try:
                value, _ = decoder.raw_decode(cleaned[match.start() :])
                if isinstance(value, dict):
                    return value, "outer_json"
            except json.JSONDecodeError:
                continue
        repaired = re.sub(r",\s*([}\]])", r"\1", cleaned)
        try:
            value = ast.literal_eval(repaired)
            return (value, "repaired_json") if isinstance(value, dict) else (None, "")
        except (ValueError, SyntaxError):
            return None, ""

    @staticmethod
    def _from_payload(
        payload: dict[str, Any],
        raw_text: str,
        candidate_id: str,
        role: str,
        answer_type: str,
        status: str,
    ) -> CandidateSolution:
        deviations: list[str] = []
        host_fields = {
            "candidate_id",
            "role",
            "answer_type",
            "planned_method_family",
            "version",
            "schema_version",
        }
        deviations.extend(
            f"{name}:host_owned" for name in sorted(host_fields.intersection(payload))
        )
        allowed_fields = host_fields | {
            "method",
            "method_steps",
            "public_solution_steps",
            "solution_text",
            "final_answer",
            "assumptions",
            "theorems",
            "claims",
            "unresolved_obligations",
        }
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
            claim_model_fields = {
                "claim_id",
                "statement",
                "depends_on",
                "check_type",
                "importance",
            }
            claim_host_fields = {
                "status",
                "claim_kind",
                "verification_state",
                "schema_version",
            }
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
                    importance=SolutionParser._model_string(
                        item,
                        "importance",
                        "supporting",
                        deviations,
                        prefix=prefix,
                    ),
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
