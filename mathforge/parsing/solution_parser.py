from __future__ import annotations

import ast
import json
import re
from typing import Any

from mathforge.harness.schemas import CandidateSolution, Claim


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
        return CandidateSolution(
            candidate_id=candidate_id,
            role=role,
            method="unspecified",
            final_answer=answer,
            answer_type=answer_type,
            solution_text=text,
            parse_status=parse_status,
        )

    @staticmethod
    def _payload(text: str) -> tuple[dict[str, Any] | None, str]:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
        try:
            value = json.loads(cleaned)
            return (value, "strict_json") if isinstance(value, dict) else (None, "")
        except (json.JSONDecodeError, TypeError):
            pass
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
        raw_claims = payload.get("claims", [])
        claims: list[Claim] = []
        if isinstance(raw_claims, list):
            for index, item in enumerate(raw_claims):
                if isinstance(item, dict):
                    claims.append(
                        Claim(
                            claim_id=str(item.get("claim_id", f"c{index + 1}")),
                            statement=str(item.get("statement", "")),
                            depends_on=[str(value) for value in item.get("depends_on", [])],
                            check_type=str(item.get("check_type", "reasoning")),
                            importance=str(item.get("importance", "supporting")),
                        )
                    )
        final_answer = str(payload.get("final_answer", "")).strip()
        solution_text = str(payload.get("solution_text", raw_text)).strip()
        if not final_answer:
            final_answer = SolutionParser._extract_answer(solution_text)
        return CandidateSolution(
            candidate_id=candidate_id,
            role=str(payload.get("role", role)),
            method=str(payload.get("method", "unspecified")),
            final_answer=final_answer,
            answer_type=str(payload.get("answer_type", answer_type)),
            assumptions=[str(value) for value in payload.get("assumptions", [])],
            theorems=[str(value) for value in payload.get("theorems", [])],
            claims=claims,
            solution_text=solution_text,
            unresolved_obligations=[
                str(value) for value in payload.get("unresolved_obligations", [])
            ],
            parse_status=status,
        )

    @staticmethod
    def _extract_answer(text: str) -> str:
        for pattern in _ANSWER_PATTERNS:
            matches = pattern.findall(text)
            if matches:
                return str(matches[-1]).strip()
        return text.strip()
