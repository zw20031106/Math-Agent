from __future__ import annotations

from hashlib import sha256
import json
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
    capability_applies_to_claim,
    derive_claim_kind,
    fatal_capability_applies,
)
from mathforge.verification.tool_requests import ClaimToolRequestBuilder


class EvidenceLedger:
    def __init__(
        self,
        records: list[EvidenceRecord] | None = None,
        budget: CallBudget | None = None,
        candidates: list[CandidateSolution] | None = None,
    ) -> None:
        self._records = records if records is not None else []
        self._budget = budget
        self._candidate_claims: dict[str, set[str]] = {}
        for candidate in candidates or []:
            self.register_candidate(candidate)

    def register_candidate(self, candidate: CandidateSolution) -> None:
        claim_ids = {claim.claim_id for claim in candidate.claims}
        if candidate.candidate_id in self._candidate_claims:
            if self._candidate_claims[candidate.candidate_id] != claim_ids:
                raise ValueError("candidate evidence identity changed")
            return
        self._candidate_claims[candidate.candidate_id] = claim_ids

    def _validate_reference(
        self,
        candidate_id: str,
        claim_id: str | None,
    ) -> None:
        if not self._candidate_claims:
            return
        if candidate_id not in self._candidate_claims:
            raise ValueError("evidence references an unknown candidate")
        if (
            claim_id is not None
            and claim_id not in self._candidate_claims[candidate_id]
        ):
            raise ValueError("evidence references an unknown claim")

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
        claim_kind: str = "unknown",
        input_complete: bool = False,
        context_complete: bool = False,
        request_status: str = "untracked",
        schema_valid: bool = False,
    ) -> EvidenceRecord:
        self._validate_reference(candidate_id, claim_id)
        self._reserve_record()
        invocation = _tool_invocation(
            result,
            arguments=arguments,
            assumptions=assumptions,
            domains=domains,
            duration_ms=duration_ms,
            timeout_seconds=timeout_seconds,
            claim_kind=claim_kind,
            input_complete=input_complete,
            context_complete=context_complete,
            request_status=request_status,
            schema_valid=schema_valid,
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
        missing_condition: str = "",
        counterexample_summary: str = "",
    ) -> EvidenceRecord:
        self._validate_reference(candidate_id, claim_id)
        self._reserve_record()
        record = EvidenceRecord(
            evidence_id=f"ev-{uuid4().hex[:12]}",
            candidate_id=candidate_id,
            claim_id=claim_id,
            evidence_type="llm:VerifierSkeptic",
            status=status if status in {"pass", "fail", "unknown"} else "unknown",
            strength="soft",
            description=description,
            payload={
                "obligation_ids": list(obligation_ids),
                "missing_condition": str(missing_condition),
                "counterexample_summary": str(counterexample_summary),
            },
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
        reason: str = "unsupported check suggestion",
        tool_name: str = "",
        request_status: str = "unsupported",
        validation_errors: list[str] | None = None,
    ) -> EvidenceRecord:
        self._validate_reference(candidate_id, claim_id)
        self._reserve_record()
        record = EvidenceRecord(
            evidence_id=f"ev-{uuid4().hex[:12]}",
            candidate_id=candidate_id,
            claim_id=claim_id,
            evidence_type="host:check_type_resolution",
            status="unknown",
            strength="soft",
            description=str(reason),
            payload={
                "check_suggestion": str(check_suggestion),
                "reason": str(reason),
                "tool_name": str(tool_name),
                "request_status": str(request_status),
                "validation_errors": list(validation_errors or []),
            },
            invocation={
                "resolver": "host_capability_matrix",
                "tool_name": str(tool_name),
                "request_status": str(request_status),
                "schema_valid": False,
                "fatal_eligible": False,
            },
            capability=VerificationCapability.NONE.value,
        )
        self._records.append(record)
        return record

    def has_hard_fail(self, candidate_id: str, claim_id: str | None = None) -> bool:
        return any(
            record.candidate_id == candidate_id
            and (claim_id is None or record.claim_id == claim_id)
            and record.transaction_status == "active"
            and is_fatal_hard_failure(record)
            for record in self._records
        )


class ClaimEvidenceVerifier:
    """Run only checks whose arguments can be derived without model interpretation."""

    def __init__(self, tools: ToolExecutor) -> None:
        self._tools = tools
        self._requests = ClaimToolRequestBuilder(tools)

    def verify(
        self,
        candidate: CandidateSolution,
        ledger: EvidenceLedger,
        *,
        only_claim_ids: list[str] | None = None,
        domains: dict[str, str] | None = None,
        assumptions: list[str] | None = None,
        budget: CallBudget | None = None,
        selected_tools: list[str] | None = None,
    ) -> list[EvidenceRecord]:
        allowed = set(only_claim_ids) if only_claim_ids is not None else None
        effective_assumptions = list(
            dict.fromkeys([*(assumptions or []), *candidate.assumptions])
        )
        records: list[EvidenceRecord] = []
        for claim in candidate.claims:
            if allowed is not None and claim.claim_id not in allowed:
                continue
            if claim.claim_kind == "unknown":
                claim.claim_kind = derive_claim_kind(claim.check_type)
            request = self._requests.build(
                candidate,
                claim,
                domains=domains,
                assumptions=assumptions,
                selected_tools=selected_tools,
            )
            if not request.ready:
                claim.verification_state = ClaimVerificationState.UNKNOWN.value
                if request.status != "unsupported" or claim.check_type.strip().lower() != "reasoning":
                    try:
                        record = ledger.record_unknown_check(
                            candidate_id=candidate.candidate_id,
                            claim_id=claim.claim_id,
                            check_suggestion=claim.check_type,
                            tool_name=request.tool_name,
                            request_status=request.status,
                            validation_errors=request.validation_errors,
                            reason={
                                "route_not_selected": "check not selected by route",
                                "argument_unavailable": (
                                    "safe argument reconstruction unavailable"
                                ),
                                "schema_invalid": "tool input schema invalid",
                            }.get(
                                request.status,
                                "unsupported check suggestion",
                            ),
                        )
                    except BudgetExceeded:
                        break
                    records.append(record)
                continue
            tool_name = request.tool_name
            arguments = request.arguments
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
                    claim_kind=claim.claim_kind,
                    input_complete=True,
                    context_complete=(
                        tool_name != "symbolic_equivalence"
                        or (
                            "assumptions" in arguments
                            and "domains" in arguments
                        )
                    ),
                    request_status=request.status,
                    schema_valid=request.schema_valid,
                )
            except BudgetExceeded:
                break
            records.append(record)
            if result.status == "pass":
                claim.verification_state = result.claim_state
            if (
                result.strength == "hard"
                and result.status == "pass"
                and capability_applies_to_claim(
                    result.capability,
                    claim.claim_kind,
                )
            ):
                claim.status = "verified"
                claim.verification_state = ClaimVerificationState.SEMANTICALLY_VERIFIED.value
            elif (
                result.strength == "hard"
                and result.status == "fail"
                and fatal_capability_applies(
                    result.capability,
                    claim.claim_kind,
                    input_complete=True,
                    context_complete=(
                        tool_name != "symbolic_equivalence"
                        or (
                            "assumptions" in arguments
                            and "domains" in arguments
                        )
                    ),
                )
            ):
                claim.status = "rejected"
                claim.verification_state = ClaimVerificationState.REJECTED.value
        return records

def _tool_invocation(
    result: ToolResult,
    *,
    arguments: dict | None,
    assumptions: list[str] | None,
    domains: dict[str, str] | None,
    duration_ms: float | None,
    timeout_seconds: float | None,
    claim_kind: str,
    input_complete: bool,
    context_complete: bool,
    request_status: str,
    schema_valid: bool,
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
        "claim_kind": str(claim_kind),
        "input_complete": bool(input_complete),
        "context_complete": bool(context_complete),
        "request_status": str(request_status),
        "schema_valid": bool(schema_valid),
        "fatal_eligible": fatal_capability_applies(
            result.capability,
            claim_kind,
            input_complete=input_complete and schema_valid,
            context_complete=context_complete,
        ),
        "input_digest": sha256(canonical).hexdigest(),
        "timeout_seconds": timeout_seconds,
        "duration_ms": round(max(0.0, float(duration_ms or 0.0)), 3),
    }


def _json_safe(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def is_fatal_hard_failure(record: EvidenceRecord) -> bool:
    return (
        record.transaction_status == "active"
        and record.strength == "hard"
        and record.status == "fail"
        and record.invocation.get("fatal_eligible") is True
        and capability_applies_to_claim(
            record.capability,
            str(record.invocation.get("claim_kind", "unknown")),
        )
    )


def is_semantic_hard_pass(record: EvidenceRecord) -> bool:
    return (
        record.transaction_status == "active"
        and record.strength == "hard"
        and record.status == "pass"
        and record.invocation.get("schema_valid") is True
        and capability_applies_to_claim(
            record.capability,
            str(record.invocation.get("claim_kind", "unknown")),
        )
    )
