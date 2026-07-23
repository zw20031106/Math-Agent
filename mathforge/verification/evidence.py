from __future__ import annotations

from hashlib import sha256
import json
import re
from time import perf_counter
from uuid import uuid4

from mathforge.harness.budget import CallBudget
from mathforge.harness.errors import BudgetExceeded
from mathforge.harness.schemas import EvidenceRecord
from mathforge.tools.registry import ToolResult
from mathforge.tools.executor import ToolExecutor
from mathforge.harness.schemas import CandidateSolution
from mathforge.verification.capabilities import (
    ClaimVerificationState,
    VerificationCapability,
    capability_verifies_claim,
)


class EvidenceLedger:
    def __init__(
        self,
        records: list[EvidenceRecord] | None = None,
        budget: CallBudget | None = None,
    ) -> None:
        self._records = records if records is not None else []
        self._budget = budget

    def _reserve_record(self) -> None:
        if self._budget is not None:
            self._budget.record_evidence()

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
        self._reserve_record()
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
            capability=result.capability,
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
        self._reserve_record()
        record = EvidenceRecord(
            evidence_id=f"ev-{uuid4().hex[:12]}",
            candidate_id=candidate_id,
            claim_id=claim_id,
            evidence_type="llm:VerifierSkeptic",
            status=status if status in {"pass", "fail", "unknown"} else "unknown",
            strength="soft",
            description=description,
            payload={"obligation_ids": list(obligation_ids)},
            invocation={
                "role": "VerifierSkeptic",
                "obligation_ids": list(obligation_ids),
            },
            capability=VerificationCapability.PROOF_OBLIGATION_REVIEW.value,
        )
        self._records.append(record)
        return record

    def record_unknown_check(
        self,
        *,
        candidate_id: str,
        claim_id: str,
        check_suggestion: str,
    ) -> EvidenceRecord:
        self._reserve_record()
        record = EvidenceRecord(
            evidence_id=f"ev-{uuid4().hex[:12]}",
            candidate_id=candidate_id,
            claim_id=claim_id,
            evidence_type="host:check_type_resolution",
            status="unknown",
            strength="soft",
            description="unsupported check suggestion",
            payload={"check_suggestion": str(check_suggestion)},
            invocation={"resolver": "host_capability_matrix"},
            capability=VerificationCapability.NONE.value,
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
        budget: CallBudget | None = None,
    ) -> list[EvidenceRecord]:
        allowed = set(only_claim_ids) if only_claim_ids is not None else None
        effective_assumptions = list(
            dict.fromkeys([*(assumptions or []), *candidate.assumptions])
        )
        records: list[EvidenceRecord] = []
        for claim in candidate.claims:
            if allowed is not None and claim.claim_id not in allowed:
                continue
            tool_name = self._tool_name(claim.check_type)
            if tool_name is None:
                claim.verification_state = ClaimVerificationState.UNKNOWN.value
                if claim.check_type.strip().lower() != "reasoning":
                    try:
                        record = ledger.record_unknown_check(
                            candidate_id=candidate.candidate_id,
                            claim_id=claim.claim_id,
                            check_suggestion=claim.check_type,
                        )
                    except BudgetExceeded:
                        break
                    records.append(record)
                continue
            arguments = self._arguments(
                candidate,
                tool_name,
                claim.statement,
                domains=domains,
                assumptions=effective_assumptions,
            )
            if arguments is None:
                claim.verification_state = ClaimVerificationState.UNKNOWN.value
                continue
            timeout = self._tools.default_timeout
            if budget is not None:
                try:
                    timeout = budget.begin_tool_call(
                        isolated=self._tools.is_isolated(tool_name),
                        default_timeout=self._tools.default_timeout,
                    )
                except BudgetExceeded:
                    break
            started = perf_counter()
            try:
                result = self._tools.execute(
                    tool_name,
                    arguments,
                    timeout=timeout,
                )
            finally:
                duration_seconds = perf_counter() - started
                if budget is not None:
                    budget.finish_tool_call(duration_seconds)
            try:
                record = ledger.record_tool_result(
                    candidate_id=candidate.candidate_id,
                    claim_id=claim.claim_id,
                    result=result,
                    arguments=arguments,
                    assumptions=effective_assumptions,
                    domains=domains,
                    duration_ms=duration_seconds * 1000,
                    timeout_seconds=timeout,
                )
            except BudgetExceeded:
                break
            records.append(record)
            if result.status == "pass":
                claim.verification_state = result.claim_state
            if (
                result.strength == "hard"
                and result.status == "pass"
                and capability_verifies_claim(result.capability)
            ):
                claim.status = "verified"
                claim.verification_state = ClaimVerificationState.SEMANTICALLY_VERIFIED.value
            elif (
                result.strength == "hard"
                and result.status == "fail"
                and capability_verifies_claim(result.capability)
            ):
                claim.status = "rejected"
                claim.verification_state = ClaimVerificationState.REJECTED.value
        return records

    @staticmethod
    def _tool_name(check_suggestion: str) -> str | None:
        normalized = str(check_suggestion).strip().lower()
        if normalized in {
            "safe_parse_expression",
            "symbolic_equivalence",
            "simplify_expression",
            "numerical_residual",
            "matrix_shape_check",
            "latex_syntax_check",
            "answer_type_check",
        }:
            return normalized
        return None

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
            "capability": result.capability,
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
