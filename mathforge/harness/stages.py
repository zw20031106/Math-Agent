from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from mathforge.agents.router_planner import RouterPlanner
from mathforge.agent_runtime.router_protocol import (
    AuthoritativePlan,
    RouterPlanningOutcome,
)
from mathforge.context.assembler import RawContextStore
from mathforge.context.role_views import RoleContextFactory
from mathforge.context.snapshots import RoleContextView
from mathforge.harness.budget import CallBudget
from mathforge.harness.schemas import (
    CandidateSolution,
    EvidenceRecord,
    ProblemIR,
    ProofObligation,
    RoutePlan,
)
from mathforge.memory.blackboard import MemoryBlackboard
from mathforge.tools.executor import ToolExecutor
from mathforge.verification.admission import (
    CandidateAdmissionDecision,
    CandidateAdmissionGate,
)
from mathforge.verification.completion import (
    CompletionDecision,
    ProofCompletionGate,
)
from mathforge.verification.evidence import (
    ClaimEvidenceVerifier,
    EvidenceLedger,
)
from mathforge.verification.proof_obligations import ProofObligationEngine


@dataclass(frozen=True)
class EvidenceGateResult:
    accepted: list[CandidateSolution]
    rejected_candidate_ids: list[str]


class CandidateStage:
    """Typed boundary for deterministic Candidate admission."""

    def __init__(self, gate: CandidateAdmissionGate) -> None:
        self._gate = gate

    def evaluate(
        self,
        candidate: CandidateSolution,
        problem: ProblemIR,
        *,
        answer_shape_status: str | None = None,
    ) -> CandidateAdmissionDecision:
        return self._gate.evaluate(
            candidate,
            problem,
            answer_shape_status=answer_shape_status,
        )


class EvidenceStage:
    """Typed boundary for claim checks and the hard-evidence gate."""

    def __init__(self, tools: ToolExecutor) -> None:
        self._verifier = ClaimEvidenceVerifier(tools)

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
        return self._verifier.verify(
            candidate,
            ledger,
            only_claim_ids=only_claim_ids,
            domains=domains,
            assumptions=assumptions,
            budget=budget,
            selected_tools=selected_tools,
        )

    @staticmethod
    def hard_gate(
        candidates: list[CandidateSolution],
        ledger: EvidenceLedger,
        *,
        enabled: bool,
    ) -> EvidenceGateResult:
        accepted = (
            [
                candidate
                for candidate in candidates
                if not ledger.has_hard_fail(candidate.candidate_id)
            ]
            if enabled
            else list(candidates)
        )
        accepted_ids = {candidate.candidate_id for candidate in accepted}
        return EvidenceGateResult(
            accepted=accepted,
            rejected_candidate_ids=[
                candidate.candidate_id
                for candidate in candidates
                if candidate.candidate_id not in accepted_ids
            ],
        )


class ProofStage:
    """Typed boundary for obligation generation and completion decisions."""

    def __init__(self) -> None:
        self._engine = ProofObligationEngine()
        self._completion_gate = ProofCompletionGate()

    def generate(
        self,
        problem: ProblemIR,
        candidate: CandidateSolution,
        problem_obligations: list[ProofObligation] | None = None,
    ) -> list[ProofObligation]:
        return self._engine.generate(
            problem,
            candidate,
            problem_obligations=problem_obligations,
        )

    def plan_problem(
        self,
        problem: ProblemIR,
    ) -> list[ProofObligation]:
        return self._engine.plan_problem(problem)

    def evaluate(
        self,
        candidate: CandidateSolution,
        evidence: list[EvidenceRecord],
        obligations: list[ProofObligation],
        *,
        response_mode: str = "answer_only",
        audits=(),
        repaired: bool = False,
        repair_lineage=(),
    ) -> CompletionDecision:
        return self._completion_gate.evaluate(
            candidate,
            evidence,
            obligations,
            response_mode=response_mode,
            audits=audits,
            repaired=repaired,
            repair_lineage=repair_lineage,
        )


class ContextRouteStage:
    """Typed boundary for deterministic role views and route selection."""

    def __init__(
        self,
        router: RouterPlanner,
        contexts: RoleContextFactory,
    ) -> None:
        self._router = router
        self._contexts = contexts

    def plan(
        self,
        problem: ProblemIR,
        *,
        llm_chat: Callable[..., str] | None = None,
        consume_call: Callable[[], None] | None = None,
        max_tokens: int = 0,
        context_view: RoleContextView | None = None,
        record_prompt_chars: Callable[[int], None] | None = None,
        record_protocol_telemetry: Callable[
            [int | None, str, str, str], None
        ]
        | None = None,
    ) -> RoutePlan:
        return self._router.plan(
            problem,
            llm_chat=llm_chat,
            consume_call=consume_call,
            max_tokens=max_tokens,
            context_view=context_view,
            record_prompt_chars=record_prompt_chars,
            record_protocol_telemetry=record_protocol_telemetry,
        )

    def plan_authoritative(
        self,
        problem: ProblemIR,
        *,
        llm_chat: Callable[..., str] | None = None,
        consume_call: Callable[[], None] | None = None,
        max_tokens: int = 0,
        context_view: RoleContextView | None = None,
        record_prompt_chars: Callable[[int], None] | None = None,
        record_protocol_telemetry: Callable[
            [int | None, str, str, str], None
        ]
        | None = None,
        previous_plan: AuthoritativePlan | None = None,
        verified_fact_ids: tuple[str, ...] = (),
    ) -> RouterPlanningOutcome:
        return self._router.plan_authoritative(
            problem,
            llm_chat=llm_chat,
            consume_call=consume_call,
            max_tokens=max_tokens,
            context_view=context_view,
            record_prompt_chars=record_prompt_chars,
            record_protocol_telemetry=record_protocol_telemetry,
            previous_plan=previous_plan,
            verified_fact_ids=verified_fact_ids,
        )

    def routing_reasons(
        self,
        problem: ProblemIR,
        plan: RoutePlan | None = None,
    ) -> list[str]:
        return self._router.routing_reasons(problem, plan)

    def build_context(
        self,
        *,
        problem: ProblemIR,
        candidates: list[CandidateSolution],
        evidence: list[EvidenceRecord],
        obligations: dict[str, list[ProofObligation]],
        blackboard: MemoryBlackboard,
        role: str,
        max_chars: int,
        focus_claim_ids: list[str] | None = None,
        final_answer: str = "",
        raw_store: RawContextStore | None = None,
        memory_categories: set[str] | frozenset[str] | None = None,
        public_metadata: dict | None = None,
    ) -> RoleContextView:
        return self._contexts.build(
            problem=problem,
            candidates=candidates,
            evidence=evidence,
            obligations=obligations,
            blackboard=blackboard,
            role=role,
            max_chars=max_chars,
            focus_claim_ids=focus_claim_ids,
            final_answer=final_answer,
            raw_store=raw_store,
            memory_categories=memory_categories,
            public_metadata=public_metadata,
        )
