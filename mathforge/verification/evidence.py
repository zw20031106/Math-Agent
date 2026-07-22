from __future__ import annotations

from hashlib import sha256
import json
import re
from time import perf_counter
from uuid import uuid4

from mathforge.harness.schemas import EvidenceRecord
from mathforge.tools.registry import ToolResult
from mathforge.tools.executor import ToolExecutor
from mathforge.harness.schemas import CandidateSolution


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
        arguments: dict | None = None,
        assumptions: list[str] | None = None,
        domains: dict[str, str] | None = None,
        duration_ms: float | None = None,
        timeout_seconds: float | None = None,
    ) -> EvidenceRecord:
        invocation = _tool_invocation(
            result,
            arguments=arguments,
            assumptions=assumptions,
            domains=domains,
            duration_ms=duration_ms,
            timeout_seconds=timeout_seconds,
        )
        record = EvidenceRecord(
            evidence_id=f"ev-{uuid4().hex[:12]}",
            candidate_id=candidate_id,
            claim_id=claim_id,
            evidence_type=f"tool:{result.tool_name}",
            status=result.status,
            strength=result.strength,
            description=result.summary,
            payload=result.to_dict()["payload"],
            invocation=invocation,
        )
        self._records.append(record)
        return record

    def record_verifier_finding(
        self,
        *,
        candidate_id: str,
        claim_id: str | None,
        obligation_ids: list[str],
        status: str,
        description: str,
    ) -> EvidenceRecord:
        record = EvidenceRecord(
            evidence_id=f"ev-{uuid4().hex[:12]}",
            candidate_id=candidate_id,
            claim_id=claim_id,
            evidence_type="llm:VerifierSkeptic",
            status=status if status in {"pass", "fail", "unknown"} else "unknown",
            strength="soft",
            description=description,
            payload={"obligation_ids": list(obligation_ids)},
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
        domains: dict[str, str] | None = None,
        assumptions: list[str] | None = None,
    ) -> list[EvidenceRecord]:
        allowed = set(only_claim_ids) if only_claim_ids is not None else None
        effective_assumptions = list(
            dict.fromkeys([*(assumptions or []), *candidate.assumptions])
        )
        records: list[EvidenceRecord] = []
        for claim in candidate.claims:
            if allowed is not None and claim.claim_id not in allowed:
                continue
            arguments = self._arguments(
                candidate,
                claim.check_type,
                claim.statement,
                domains=domains,
                assumptions=effective_assumptions,
            )
            if arguments is None:
                continue
            started = perf_counter()
            result = self._tools.execute(claim.check_type, arguments)
            duration_ms = (perf_counter() - started) * 1000
            record = ledger.record_tool_result(
                candidate_id=candidate.candidate_id,
                claim_id=claim.claim_id,
                result=result,
                arguments=arguments,
                assumptions=effective_assumptions,
                domains=domains,
                duration_ms=duration_ms,
                timeout_seconds=self._tools.default_timeout,
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
        *,
        domains: dict[str, str] | None = None,
        assumptions: list[str] | None = None,
    ) -> dict | None:
        if check_type in {"symbolic_equivalence", "numerical_residual"}:
            parts = re.split(r"==|(?<![<>!])=(?!=)", statement, maxsplit=1)
            if len(parts) != 2:
                return None
            arguments = {"left": parts[0].strip(), "right": parts[1].strip()}
            if check_type == "symbolic_equivalence":
                arguments["assumptions"] = list(assumptions or candidate.assumptions)
                arguments["domains"] = dict(domains or {})
            return arguments
        if check_type in {"safe_parse_expression", "simplify_expression"}:
            return {"expression": statement}
        if check_type == "matrix_shape_check":
            return {"matrix": statement}
        if check_type == "latex_syntax_check":
            return {"text": statement}
        if check_type == "answer_type_check":
            return {"answer": candidate.final_answer, "answer_type": candidate.answer_type}
        return None


def _tool_invocation(
    result: ToolResult,
    *,
    arguments: dict | None,
    assumptions: list[str] | None,
    domains: dict[str, str] | None,
    duration_ms: float | None,
    timeout_seconds: float | None,
) -> dict:
    reproducible = _json_safe(
        {
            "tool_name": result.tool_name,
            "tool_version": result.tool_version,
            "arguments": dict(arguments or {}),
            "assumptions": list(assumptions or []),
            "domains": dict(domains or {}),
        }
    )
    canonical = json.dumps(
        reproducible,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        **reproducible,
        "input_digest": sha256(canonical).hexdigest(),
        "timeout_seconds": timeout_seconds,
        "duration_ms": round(max(0.0, float(duration_ms or 0.0)), 3),
    }


def _json_safe(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))
