from __future__ import annotations

import json

import pytest

from mathforge.agents.solver import PrimarySolver, SolverExecutor, SolverRequest
from mathforge.agent_runtime.autonomy import AgentProgressTracker
from mathforge.agent_runtime.protocol import AgentTurnPayload
from mathforge.harness.budget import CallBudget
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.harness.reasoning_state import PublicClaim, ReasoningState, RoundDelta
from mathforge.harness.schemas import RoutePlan
from mathforge.harness.truncation import (
    CheckpointCursor,
    CheckpointStore,
    HostInferredDependencies,
    InformationGainScorer,
    ProofBackbone,
    RecoveredAnswerGate,
    TruncationAssessment,
    TruncationStatus,
    VerifiedFact,
    VerifiedFactBank,
    emergency_allowed,
    rebuild_candidate_from_state,
    resume_prompt_context,
)
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import SolutionParser
from tests.test_f4_autonomous_agents import (
    AutonomousClient,
    _LengthResponse,
    _config,
)
from mathforge.runtime import MathForgeHarness


def _state() -> ReasoningState:
    problem = ProblemParser().parse(
        "For x in R, prove that (x + 1)^2 = x^2 + 2*x + 1."
    )
    return ReasoningState.initialize(
        problem,
        session_id="e4-session",
        branch_id="e4-branch",
        agent_id="PrimarySolver",
    )


def _state_with_claims() -> ReasoningState:
    state = _state()
    first = PublicClaim(
        "c-support",
        "Expand the square with the binomial identity.",
        importance="supporting",
        branch_id=state.branch_id,
    )
    second = PublicClaim(
        "c-critical",
        "The expanded expression equals the requested target.",
        depends_on=("c-support",),
        importance="critical",
        branch_id=state.branch_id,
    )
    state, _ = state.apply(
        RoundDelta(
            1,
            "explore",
            "public expansion",
            "direct-deduction",
            claims=(first, second),
            next_step="verify the equality",
        )
    )
    return state


def test_truncation_assessment_uses_all_public_signals():
    complete = TruncationAssessment.assess(
        json.dumps({"action": "complete", "result_payload": {"x": 2}}),
        required_fields=("action", "result_payload"),
    )
    assert complete.status == TruncationStatus.COMPLETE.value
    assert complete.json_balanced
    assert complete.required_fields_complete

    truncated = TruncationAssessment.assess(
        '<think>unfinished {"action":"continue_reasoning"',
        native_finish_reason="length",
        observed_tokens=64,
        max_tokens=64,
        required_fields=("action", "result_payload"),
        protocol_suffix="</agent_turn>",
    )
    assert truncated.status == TruncationStatus.DEFINITE_TRUNCATION.value
    assert truncated.is_truncated
    assert "json_unbalanced" in truncated.reasons
    assert "think_tag_unclosed" in truncated.reasons
    assert not truncated.protocol_suffix_present


def test_checkpoint_cursor_is_public_and_rolls_back_uncommitted_state():
    state = _state_with_claims()
    store = CheckpointStore(max_checkpoints=2)
    cursor = store.commit(state, plan_version=3)
    assert set(cursor.to_dict()) == {
        "checkpoint_id",
        "state_version",
        "plan_version",
        "branch_id",
        "open_subgoals",
        "open_obligations",
        "critical_claim_ids",
        "next_step",
    }
    advanced, _ = state.apply(
        RoundDelta(
            state.version,
            "continue",
            "uncommitted public delta",
            "direct-deduction",
            claims=(
                PublicClaim(
                    "c-uncommitted",
                    "A delta that must not survive truncation.",
                    branch_id=state.branch_id,
                ),
            ),
        )
    )
    restored = store.discard_uncommitted(cursor)
    assert restored.to_dict() == state.to_dict()
    assert restored.to_dict() != advanced.to_dict()
    assert CheckpointCursor.from_dict(cursor.to_dict()) == cursor


def test_resume_prompt_contains_checkpoint_frontier_and_prior_facts():
    state = _state_with_claims()
    store = CheckpointStore()
    cursor = store.commit(state, plan_version=7, next_step="close equality")
    bank = VerifiedFactBank(
        [
            VerifiedFact(
                "fact-equality",
                "The binomial expansion is exact.",
                "c-support",
                evidence_strength="hard",
            )
        ]
    )
    prompt = resume_prompt_context(
        cursor,
        state,
        verified_facts=bank.values(),
        proof_backbone=ProofBackbone.from_state(state, verified_facts=bank.values()),
    )
    assert "checkpoint_version" in prompt
    assert '"plan_version":7' in prompt
    assert "c-critical" in prompt
    assert "The binomial expansion is exact." in prompt
    assert "chain" not in prompt.casefold()


def test_stateful_candidate_rebuild_keeps_public_derivation():
    state = _state_with_claims()
    backbone = ProofBackbone.from_state(state)
    candidate = rebuild_candidate_from_state(
        state,
        final_answer="x^2 + 2*x + 1",
        candidate_id="recovered-candidate",
        role="PrimarySolver",
        method="direct-deduction",
        answer_type="expression",
        proof_backbone=backbone,
    )
    assert candidate is not None
    assert candidate.parse_status == "truncated_candidate_rebuilt"
    assert candidate.assurance == "recovered"
    assert candidate.degraded
    assert candidate.public_solution_steps
    assert candidate.claims
    assert candidate.parse_tier == "recovered"


def test_parser_marks_answer_only_salvage_as_provisional_assurance():
    candidate = SolutionParser().recover_answer_candidate(
        '{"result_payload":{"answer":"4","check":"2+2=4"',
        candidate_id="answer-salvage",
        role="PrimarySolver",
        answer_type="integer",
        planned_method_family="direct-deduction",
    )
    assert candidate is not None
    assert candidate.assurance == "answer_salvaged"
    assert candidate.parse_tier == "answer_recovered"


def test_truncated_candidate_turn_rebuilds_from_checkpoint_state():
    class TruncatedCandidateResponse(str):
        finish_reason = "length"

    class Client:
        def chat(self, *, messages, temperature, max_tokens):
            del messages, temperature, max_tokens
            envelope = {
                "protocol_version": "1.0",
                "task_result_type": "CandidateArtifact",
                "action": "publish_candidate",
                "public_state_delta": {},
                "result_payload": {
                    "final_answer": "4",
                    "method": "direct-deduction",
                    "public_solution_steps": ["A public check."],
                    "solution_text": "A public check.",
                    "assumptions": [],
                    "theorems": [],
                    "unresolved_obligations": [],
                    "claims": [],
                },
                "outbound_intents": [],
                "progress_summary": "candidate",
                "stop_reason": "candidate_complete",
            }
            return TruncatedCandidateResponse(json.dumps(envelope)[:-1])

    state = _state_with_claims()
    problem = ProblemParser().parse("Compute 2+2.")
    route = RoutePlan(
        primary_subject="general-math",
        auxiliary_subject=None,
        problem_type="calculation",
        answer_type="integer",
        risk_level="medium",
        candidate_count=1,
    )
    request = SolverRequest(
        "checkpointed-candidate",
        problem,
        route,
        "",
        "direct-deduction",
        reasoning_state_json=json.dumps(state.to_dict()),
    )
    turn = SolverExecutor(
        OfficialClientProvider(Client(), ModelCallGate(2)),
        SolutionParser(),
    ).execute_autonomous_candidate(
        PrimarySolver(),
        request,
        CallBudget(2),
        temperature=0.0,
        max_tokens=2048,
    )
    assert turn.parsed.partial
    assert turn.truncation_assessment is not None
    assert turn.truncation_assessment.status == TruncationStatus.DEFINITE_TRUNCATION.value
    assert turn.candidate is not None
    assert turn.candidate.parse_status == "truncated_candidate_rebuilt"
    assert turn.candidate.assurance == "recovered"
    assert {claim.claim_id for claim in turn.candidate.claims} == {
        "c-support",
        "c-critical",
    }


def test_emergency_answer_is_only_allowed_inside_closure_window():
    assert emergency_allowed(
        remaining_time=20,
        closure_threshold=210,
        usable_candidate=False,
    )
    assert not emergency_allowed(
        remaining_time=300,
        closure_threshold=210,
        usable_candidate=False,
    )
    assert not emergency_allowed(
        remaining_time=10,
        closure_threshold=210,
        usable_candidate=True,
    )


def test_recovered_answer_requires_corroboration_and_is_not_high_risk_winner():
    recovered = rebuild_candidate_from_state(
        _state_with_claims(),
        final_answer="4",
        candidate_id="recovered",
        role="PrimarySolver",
        method="direct-deduction",
        answer_type="integer",
    )
    assert recovered is not None
    recovered.parse_tier = "answer_recovered"
    recovered.assurance = "answer_salvaged"
    missing = RecoveredAnswerGate.evaluate(recovered)
    assert missing.provisional
    assert not missing.admitted
    corroborated = RecoveredAnswerGate.evaluate(
        recovered,
        deterministic_tool_hard_pass=True,
    )
    assert corroborated.admitted
    assert corroborated.winner_allowed
    high_risk = RecoveredAnswerGate.evaluate(
        recovered,
        deterministic_tool_hard_pass=True,
        high_risk=True,
    )
    assert high_risk.admitted
    assert not high_risk.winner_allowed


def test_verified_fact_bank_is_pinned_and_strength_monotonic():
    bank = VerifiedFactBank()
    bank.record(
        fact_id="fact-1",
        statement="x equals x.",
        source_claim_id="c1",
        evidence_strength="medium",
        version=2,
    )
    bank.record(
        fact_id="fact-1",
        statement="x equals x.",
        source_claim_id="c1",
        evidence_strength="hard",
        version=3,
        pinned=True,
    )
    bank.semantic_gc(active_claim_ids=(), current_version=100, max_age=0)
    fact = bank.get("fact-1")
    assert fact is not None
    assert fact.evidence_strength == "hard"
    assert fact.pinned


def test_proof_backbone_and_host_dependency_inference_are_relation_complete():
    state = _state_with_claims()
    backbone = ProofBackbone.from_state(state).extend(
        support_claim_ids=("c-support",),
        hard_evidence_ids=("ev-1",),
    )
    inference = HostInferredDependencies.infer(
        state.claim_ledger.items,
        proof_backbone=backbone,
        terminal_claim_ids=("c-critical",),
    )
    assert "c-support" in inference.dependencies["c-critical"]
    assert "explicit_claim_depends_on" in inference.sources["c-critical"]
    assert "proof_backbone_relation" in inference.sources["c-critical"] or "terminal_conclusion_reference" in inference.sources["c-critical"]
    assert backbone.hard_evidence_ids == ("ev-1",)
    assert backbone.to_prompt_json()


def test_proof_backbone_keeps_only_terminal_dependency_closure():
    state = _state_with_claims()
    state, _ = state.apply(
        RoundDelta(
            state.version,
            "continue",
            "an unrelated public fact",
            "direct-deduction",
            claims=(
                PublicClaim(
                    "c-unrelated",
                    "This fact is not used by the conclusion.",
                    branch_id=state.branch_id,
                ),
            ),
        )
    )
    backbone = ProofBackbone.from_state(state)
    assert backbone.critical_claim_ids == ("c-critical",)
    assert backbone.necessary_support_claim_ids == ("c-support",)
    inferred = HostInferredDependencies.infer(
        {"claims": [item.to_dict() for item in state.claim_ledger.items]},
        obligations={
            "items": [
                {
                    "source_claim_ids": ["c-critical", "c-support"],
                }
            ]
        },
    )
    assert "c-support" in inferred.dependencies["c-critical"]


def test_information_gain_scores_semantics_and_tracker_resets_after_rollback():
    score = InformationGainScorer.score(
        {
            "claims": [{"importance": "critical"}, {"status": "verified"}],
            "closed_obligation_ids": ["o1"],
            "closed_subgoal_ids": ["g1"],
            "evidence": [{"evidence_id": "ev1", "strength": "hard"}],
            "strategy_changed": True,
        }
    )
    assert score.components["new_critical_claim"] == 4
    assert score.components["verified_claim"] == 5
    assert score.components["closed_obligation"] == 5
    assert score.components["closed_subgoal"] == 5
    assert score.components["new_hard_evidence"] == 5
    assert score.components["strategy_switch"] == 2
    tracker = AgentProgressTracker()
    payload = AgentTurnPayload(
        protocol_version="1.0",
        task_result_type="ProgressArtifact",
        action="continue_reasoning",
        public_state_delta={"public_summary": "new public step"},
        result_payload={},
        outbound_intents=(),
        progress_summary="public progress",
        stop_reason="",
    )
    assert tracker.observe("solver", payload).continue_allowed
    tracker.clear_agent("solver")
    assert tracker.observe("solver", payload).continue_allowed


def test_truncated_progress_restores_checkpoint_and_resumes_public_frontier():
    class TruncatedProgressClient(AutonomousClient):
        def __init__(self) -> None:
            super().__init__(primary_continues=2)
            self._truncated = False

        def chat(self, *, messages, temperature, max_tokens):
            response = super().chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            role = self.calls[-1]["role"]
            system = self.calls[-1]["system"]
            if role != "PrimarySolver" or not (
                "Public protocol mode is explore" in system
                or "Public protocol mode is continue" in system
            ):
                return response
            index = self.progress_counts["PrimarySolver"]
            payload = json.loads(response)
            if index == 1:
                payload["public_state_delta"]["claims"][0]["importance"] = "critical"
                return json.dumps(payload)
            if index == 2 and not self._truncated:
                self._truncated = True
                return _LengthResponse(response[:-1])
            return response

    client = TruncatedProgressClient()
    result = MathForgeHarness(
        client,
        _config(
            enable_alternatives=False,
            enable_simple_direct_candidate=False,
        ),
    ).solve("Compute 2+2.", {})
    assert client.progress_counts["PrimarySolver"] == 3
    assert any(item["event"] == "checkpoint_restored" for item in result["trace"])
    assert any(
        item["event"] == "truncation_assessed"
        and item["status"] == TruncationStatus.DEFINITE_TRUNCATION.value
        for item in result["trace"]
    )
    primary_progress = [
        item
        for item in client.calls
        if item["role"] == "PrimarySolver"
        and "Public protocol mode" in item["system"]
    ]
    assert any('"checkpoint_version"' in item["user"] for item in primary_progress[1:])
    assert any('"prior_critical_claims"' in item["user"] for item in primary_progress[2:])
    assert result["final_response"].strip()
