from __future__ import annotations

import ast
import json
import re
from typing import Any

from mathforge.harness.schemas import CandidateSolution, Claim
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
            solution_text=solution_text,
            unresolved_obligations=SolutionParser._model_string_list(
                payload,
                "unresolved_obligations",
                deviations,
            ),
            parse_status=status,
            contract_deviations=sorted(set(deviations)),
        )
        candidate.validate()
        return candidate

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
