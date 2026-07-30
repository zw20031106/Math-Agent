from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from time import perf_counter
from typing import Any

from mathforge.harness.budget import CallBudget
from mathforge.harness.errors import BudgetExceeded
from mathforge.harness.reasoning_state import PublicClaim, PublicToolResult
from mathforge.harness.schemas import CheckSpec
from mathforge.tools.executor import ToolExecutor
from mathforge.verification.tool_requests import ClaimToolRequestBuilder


@dataclass(frozen=True)
class ToolWorkItem:
    work_item_id: str
    claim_id: str
    check_spec: CheckSpec

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_item_id": self.work_item_id,
            "claim_id": self.claim_id,
            "check_spec": self.check_spec.to_dict(),
        }


@dataclass(frozen=True)
class ToolFeedbackBatch:
    work_items: tuple[ToolWorkItem, ...]
    results: tuple[PublicToolResult, ...]

    @property
    def constructible_count(self) -> int:
        return sum(item.check_spec.status == "ready" for item in self.work_items)

    @property
    def constructibility_rate(self) -> float:
        if not self.work_items:
            return 0.0
        return self.constructible_count / len(self.work_items)

    @property
    def failure_codes(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                item.reason_code
                for item in self.results
                if item.status in {"fail", "unknown", "error"}
            )
        )

    def to_trace_dict(self) -> dict[str, Any]:
        return {
            "work_items": [item.to_dict() for item in self.work_items],
            "results": [item.to_dict() for item in self.results],
            "constructible_count": self.constructible_count,
            "work_item_count": len(self.work_items),
            "constructibility_rate": self.constructibility_rate,
            "failure_codes": list(self.failure_codes),
            "strategy_changed": any(
                item.impact == "switch_strategy" for item in self.results
            ),
        }


class ToolFeedbackController:
    """Host-mediated public Claim -> local tool -> feedback pipeline."""

    def __init__(self, tools: ToolExecutor) -> None:
        self._tools = tools
        self._requests = ClaimToolRequestBuilder(tools)

    def run(
        self,
        claims: tuple[PublicClaim, ...],
        *,
        domains: dict[str, str],
        assumptions: list[str],
        selected_tools: list[str],
        budget: CallBudget | None = None,
    ) -> ToolFeedbackBatch:
        work_items = tuple(
            self._work_item(
                claim,
                domains=domains,
                assumptions=assumptions,
                selected_tools=selected_tools,
            )
            for claim in claims
            if claim.check_type != "reasoning"
        )
        results = tuple(
            self._execute(item, budget=budget)
            for item in work_items
        )
        return ToolFeedbackBatch(work_items, results)

    def _work_item(
        self,
        claim: PublicClaim,
        *,
        domains: dict[str, str],
        assumptions: list[str],
        selected_tools: list[str],
    ) -> ToolWorkItem:
        request = self._requests.build_fields(
            claim_id=claim.claim_id,
            check_suggestion=claim.check_type,
            statement=claim.statement,
            domains=domains,
            assumptions=assumptions,
            selected_tools=selected_tools,
        )
        spec = request.to_check_spec()
        digest = sha256(
            json.dumps(
                {
                    "claim_id": claim.claim_id,
                    "check_spec": spec.to_dict(),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16]
        return ToolWorkItem(
            work_item_id=f"wi-{digest}",
            claim_id=claim.claim_id,
            check_spec=spec,
        )

    def _execute(
        self,
        item: ToolWorkItem,
        *,
        budget: CallBudget | None,
    ) -> PublicToolResult:
        spec = item.check_spec
        if spec.status != "ready":
            payload = {
                "check_spec_status": spec.status,
                "reason_code": spec.reason_code,
            }
            return _public_result(
                item,
                status="unknown",
                strength="soft",
                summary="Host could not construct an executable local-tool request.",
                payload=payload,
                impact=(
                    "request_clarification"
                    if spec.status in {"argument_unavailable", "schema_invalid"}
                    else "no_change"
                ),
                reason_code=f"tool_{spec.status}",
            )

        timeout = self._tools.default_timeout
        if budget is not None:
            try:
                timeout = budget.begin_tool_call(
                    isolated=self._tools.is_isolated(spec.tool_name),
                    default_timeout=self._tools.default_timeout,
                )
            except BudgetExceeded:
                return _public_result(
                    item,
                    status="unknown",
                    strength="soft",
                    summary="The local-tool budget was unavailable.",
                    payload={"check_spec_status": spec.status},
                    impact="no_change",
                    reason_code="tool_budget_unavailable",
                )
        started = perf_counter()
        try:
            result = self._tools.execute(
                spec.tool_name,
                spec.arguments,
                timeout=timeout,
            )
        finally:
            if budget is not None:
                budget.finish_tool_call(perf_counter() - started)
        impact = {
            "pass": "confirm_strategy",
            "fail": "switch_strategy",
            "unknown": "request_clarification",
            "error": "request_clarification",
        }.get(result.status, "no_change")
        status = (
            result.status
            if result.status in {"pass", "fail", "unknown", "error"}
            else "unknown"
        )
        return _public_result(
            item,
            status=status,
            strength=(
                result.strength
                if result.strength in {"none", "soft", "medium", "hard"}
                else "soft"
            ),
            summary=result.summary,
            payload=result.to_dict()["payload"],
            impact=impact,
            reason_code=f"tool_{status}",
        )


def _public_result(
    item: ToolWorkItem,
    *,
    status: str,
    strength: str,
    summary: str,
    payload: dict[str, Any],
    impact: str,
    reason_code: str,
) -> PublicToolResult:
    canonical = json.dumps(
        {
            "work_item_id": item.work_item_id,
            "claim_id": item.claim_id,
            "tool_name": item.check_spec.tool_name or "unavailable",
            "status": status,
            "strength": strength,
            "summary": summary,
            "payload": payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    result = PublicToolResult(
        work_item_id=item.work_item_id,
        claim_id=item.claim_id,
        tool_name=item.check_spec.tool_name or "unavailable",
        status=status,
        strength=strength,
        summary=summary,
        public_payload=dict(payload),
        result_digest=sha256(canonical.encode("utf-8")).hexdigest(),
        impact=impact,
        reason_code=reason_code,
    )
    result.validate()
    return result
