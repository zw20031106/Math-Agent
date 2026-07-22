from __future__ import annotations

from uuid import uuid4

from mathforge.harness.schemas import EvidenceRecord
from mathforge.tools.registry import ToolResult


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
