from __future__ import annotations

from uuid import uuid4

from mathforge.harness.schemas import EvidenceRecord
from mathforge.tools.registry import ToolResult
from mathforge.tools.executor import ToolExecutor
from mathforge.harness.schemas import CandidateSolution
import re


class EvidenceLedger:
    def __init__(self, records: list[EvidenceRecord] | None = None) -> None:
        self._records = records if records is not None else []

    @property
    def records(self) -> list[EvidenceRecord]:
        return list(self._records)

    def record_tool_result(
        self,
        *,
        candidate_id: str,
        claim_id: str | None,
        result: ToolResult,
    ) -> EvidenceRecord:
        record = EvidenceRecord(
            evidence_id=f"ev-{uuid4().hex[:12]}",
            candidate_id=candidate_id,
            claim_id=claim_id,
            evidence_type=f"tool:{result.tool_name}",
            status=result.status,
            strength=result.strength,
            description=result.summary,
            payload=result.to_dict()["payload"],
        )
        self._records.append(record)
        return record

    def has_hard_fail(self, candidate_id: str, claim_id: str | None = None) -> bool:
        return any(
            record.candidate_id == candidate_id
            and (claim_id is None or record.claim_id == claim_id)
            and record.strength == "hard"
            and record.status == "fail"
            for record in self._records
        )


class ClaimEvidenceVerifier:
    """Run only checks whose arguments can be derived without model interpretation."""

    def __init__(self, tools: ToolExecutor) -> None:
        self._tools = tools

    def verify(
        self,
        candidate: CandidateSolution,
        ledger: EvidenceLedger,
        *,
        only_claim_ids: list[str] | None = None,
    ) -> list[EvidenceRecord]:
        allowed = set(only_claim_ids) if only_claim_ids is not None else None
        records: list[EvidenceRecord] = []
        for claim in candidate.claims:
            if allowed is not None and claim.claim_id not in allowed:
                continue
            arguments = self._arguments(candidate, claim.check_type, claim.statement)
            if arguments is None:
                continue
            result = self._tools.execute(claim.check_type, arguments)
            record = ledger.record_tool_result(
                candidate_id=candidate.candidate_id,
                claim_id=claim.claim_id,
                result=result,
            )
            records.append(record)
            if result.strength == "hard" and result.status == "pass":
                claim.status = "verified"
            elif result.strength == "hard" and result.status == "fail":
                claim.status = "rejected"
        return records

    @staticmethod
    def _arguments(
        candidate: CandidateSolution,
        check_type: str,
        statement: str,
    ) -> dict | None:
        if check_type in {"symbolic_equivalence", "numerical_residual"}:
            parts = re.split(r"==|(?<![<>!])=(?!=)", statement, maxsplit=1)
            if len(parts) != 2:
                return None
            return {"left": parts[0].strip(), "right": parts[1].strip()}
        if check_type in {"safe_parse_expression", "simplify_expression"}:
            return {"expression": statement}
        if check_type == "matrix_shape_check":
            return {"matrix": statement}
        if check_type == "latex_syntax_check":
            return {"text": statement}
        if check_type == "answer_type_check":
            return {"answer": candidate.final_answer, "answer_type": candidate.answer_type}
        return None
