from __future__ import annotations

import json

from mathforge.agents.skill_selector import DynamicSkillSelector
from mathforge.agents.registry import SkillRegistry
from mathforge.config import (
    HarnessConfig,
    load_competition_config,
)
from mathforge.harness.lemma_loop import VerifiedLemmaLoop
from mathforge.harness.reasoning_state import ReasoningState
from mathforge.harness.schemas import (
    CandidateSolution,
    CheckSpec,
    Claim,
    ProofObligation,
    RoutePlan,
)
from mathforge.memory.lemma_memory import LemmaMemory
from mathforge.memory.session_memory import SessionMemory
from mathforge.output.judge_trace import project_judge_trace
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.resources import resource_path
from mathforge.retrieval.method_card_store import ReviewedMethodCardStore
from mathforge.runtime import MathForgeHarness
from mathforge.tool_prompt_examples import claim_prompt_examples
from mathforge.tools.executor import ToolExecutor
from mathforge.tools.registry import ToolRegistry
from mathforge.verification.capabilities import ClaimVerificationState
from mathforge.verification.evidence import (
    ClaimEvidenceVerifier,
    EvidenceLedger,
    is_fatal_hard_failure,
)


FEEDBACK_PROBLEM = (
    "For x in R, prove that the correct expansion of (x+1)^2 is x^2+2*x+1."
)


def _config(*, enable_tools: bool = True) -> HarnessConfig:
    return HarnessConfig(
        profile="phase5-test",
        status="test",
        max_model_calls=4,
        enable_router=False,
        enable_skills=True,
        enable_alternatives=False,
        enable_tools=enable_tools,
        enable_evidence=False,
        enable_proof_obligations=False,
        enable_verifier=False,
        enable_memory=False,
        enable_lemma_loop=False,
        enable_rag=False,
        enable_repair=False,
        enable_finalizer=False,
        enable_shadow=False,
        enable_frozen_lemma_store=False,
        enable_long_horizon=True,
    )


def _progress(*, corrected: bool = False) -> str:
    claim = {
        "claim_id": "r2-fixed" if corrected else "r1-bad",
        "statement": (
            "(x+1)**2 equals x**2+2*x+1 for real x."
            if corrected
            else "(x+1)**2 equals x**2+2*x+2 for real x."
        ),
        "depends_on": [],
        "subgoal_ids": ["g1"],
        "importance": "critical",
        "check_type": "symbolic_equivalence",
    }
    return json.dumps(
        {
            "public_summary": (
                "The failed equality was replaced by a checked expansion."
                if corrected
                else "A proposed expansion is ready for a local equality check."
            ),
            "strategy": (
                "expand-and-collect"
                if corrected
                else "test-proposed-expansion"
            ),
            "subgoals": [
                {
                    "subgoal_id": "g1",
                    "statement": "Establish the exact polynomial expansion.",
                    "depends_on": [],
                    "exit_condition": "The equality has exact local evidence.",
                    "status": "closed" if corrected else "active",
                }
            ],
            "claims": [claim],
            "open_obligations": (
                []
                if corrected
                else [
                    {
                        "obligation_id": "o1",
                        "statement": "Check the proposed polynomial equality.",
                        "depends_on": ["r1-bad"],
                    }
                ]
            ),
            "closed_obligation_ids": ["o1"] if corrected else [],
            "contradictions": [],
            "next_step": (
                "Synthesize the corrected proof."
                if corrected
                else "Run the Host-owned symbolic equality check."
            ),
            "stop_reason": "",
        }
    )


def _candidate(*, corrected: bool) -> str:
    answer = "x^2+2*x+1" if corrected else "x^2+2*x+2"
    return json.dumps(
        {
            "method": "direct-deduction",
            "final_answer": answer,
            "public_solution_steps": [
                "Expand the square and collect like terms.",
                f"The result is {answer}.",
            ],
            "claims": [
                {
                    "claim_id": "c1",
                    "statement": f"(x+1)**2 equals {answer} for real x.",
                    "depends_on": [],
                    "check_type": "symbolic_equivalence",
                    "importance": "critical",
                }
            ],
            "solution_text": f"Direct expansion gives {answer}.",
            "assumptions": ["x is real"],
            "theorems": [],
            "unresolved_obligations": [],
        }
    )


class FeedbackAwareClient:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, *, messages, temperature, max_tokens) -> str:
        del temperature, max_tokens
        self.calls.append(messages)
        system = messages[0]["content"]
        user = messages[-1]["content"]
        if "Public protocol mode is explore" in system:
            return _progress()
        if "Public protocol mode is continue" in system:
            corrected = (
                '"status":"fail"' in user
                and '"impact":"switch_strategy"' in user
                and "r1-bad" in user
            )
            return _progress(corrected=corrected)
        return _candidate(corrected="r2-fixed" in user)


def test_prompt_examples_use_production_check_specs_and_exceed_90_percent():
    registry = ToolRegistry()
    examples = claim_prompt_examples(registry.names(), limit=99)

    assert len(examples) == 9
    assert (
        sum(
            not registry.validate_arguments(
                item["tool"],
                item["host_arguments"],
            )
            for item in examples
        )
        / len(examples)
        >= 0.9
    )
    assert all(item["check_spec"]["status"] == "ready" for item in examples)


def test_host_owned_check_spec_and_unconstructible_request_remain_unknown():
    claim = Claim(
        "c1",
        "These forms look equivalent.",
        check_type="symbolic_equivalence",
        importance="critical",
    )
    candidate = CandidateSolution(
        "candidate",
        "PrimarySolver",
        "direct",
        "x",
        "expression",
        claims=[claim],
    )
    ledger = EvidenceLedger(candidates=[candidate])
    records = ClaimEvidenceVerifier(ToolExecutor(use_mcp=False)).verify(
        candidate,
        ledger,
        selected_tools=["symbolic_equivalence"],
    )

    assert isinstance(claim.check_spec, CheckSpec)
    assert claim.check_spec.status == "argument_unavailable"
    assert records[0].status == "unknown"
    assert records[0].strength == "soft"
    assert not is_fatal_hard_failure(records[0])


def test_tool_result_changes_continue_strategy_and_corrects_the_answer():
    enabled_client = FeedbackAwareClient()
    enabled = MathForgeHarness(enabled_client, _config()).solve(
        FEEDBACK_PROBLEM,
        {},
    )
    disabled_client = FeedbackAwareClient()
    disabled = MathForgeHarness(
        disabled_client,
        _config(enable_tools=False),
    ).solve(FEEDBACK_PROBLEM, {})

    feedback = next(
        event
        for event in enabled["trace"]
        if event["event"] == "tool_feedback_completed"
    )
    continue_prompt = enabled_client.calls[1][-1]["content"]

    assert feedback["constructibility_rate"] == 1.0
    assert feedback["strategy_changed"]
    assert feedback["next_protocol"] == "continue"
    assert feedback["results"][0]["status"] == "fail"
    assert '"impact":"switch_strategy"' in continue_prompt
    assert "r1-bad" in continue_prompt
    assert "x^2+2*x+1" in enabled["final_response"]
    assert "x^2+2*x+2" in disabled["final_response"]


def test_dynamic_skill_fragments_trace_rank_reason_and_omission():
    problem = ProblemParser().parse(FEEDBACK_PROBLEM)
    state = ReasoningState.initialize(problem)
    selector = DynamicSkillSelector(SkillRegistry())
    composition = selector.compose_for_role(
        problem,
        role="PrimarySolver",
        route_skill_names=[
            "general-math",
            "proof-obligation",
            "symbolic-equivalence",
        ],
        max_chars=3000,
        state=state,
        failure_codes=["tool_fail"],
        selection_context="tool_feedback_round_1",
    )
    trace = composition.to_trace_dict()

    assert composition.included
    assert "symbolic-equivalence" in {
        item.name for item in composition.included
    }
    assert all(item.rank >= 1 and item.reasons for item in composition.included)
    assert any(item.omitted_sections for item in composition.included)
    assert trace["selection_context"] == "tool_feedback_round_1"
    assert "included" in trace and "omitted" in trace


def test_typed_claim_reuse_targets_named_obligation_only():
    check_spec = CheckSpec(
        tool_name="symbolic_equivalence",
        arguments={
            "left": "(x+1)**2",
            "right": "x**2+2*x+1",
            "assumptions": [],
            "domains": {"x": "R"},
        },
        status="ready",
        reason_code="host_arguments_constructed",
    )
    candidate = CandidateSolution(
        "candidate",
        "PrimarySolver",
        "direct",
        "x^2+2*x+1",
        "expression",
        claims=[
            Claim(
                "c1",
                "The expansion equality is exact.",
                check_type="symbolic_equivalence",
                importance="critical",
                status="verified",
                claim_kind="equality",
                verification_state=(
                    ClaimVerificationState.SEMANTICALLY_VERIFIED.value
                ),
                check_spec=check_spec,
            ),
            Claim(
                "c2",
                "An unrelated parity observation.",
                status="verified",
                verification_state=(
                    ClaimVerificationState.SEMANTICALLY_VERIFIED.value
                ),
            ),
        ],
    )
    obligation = ProofObligation(
        "o1",
        "equality",
        "Prove the expansion equality.",
        source_claim_ids=["c1"],
    )
    route = RoutePlan(
        problem_type="proof",
        answer_type="expression",
        primary_subject="algebra",
        auxiliary_subject=None,
        risk_level="high",
        candidate_count=1,
        max_reasoning_rounds=2,
        use_rag=False,
        use_lemma_loop=True,
        use_llm_finalizer=False,
        selected_skills=["algebra"],
        selected_tools=["symbolic_equivalence"],
        method_families=["direct"],
    )
    result = VerifiedLemmaLoop().run(
        route,
        [candidate],
        [],
        {"candidate": [obligation]},
        LemmaMemory(SessionMemory()),
        target="Prove the expansion equality.",
    )

    assert [item.source_claim_id for item in result.lemmas] == ["c1"]
    assert result.lemmas[0].claim_kind == "equality"
    assert result.lemmas[0].check_spec == check_spec
    assert result.lemmas[0].target_obligation_ids == ["o1"]
    assert obligation.status == "satisfied"


def test_reviewed_method_cards_are_hash_bound_read_only_and_disabled_before_ab():
    store = ReviewedMethodCardStore(
        resource_path("data", "knowledge_cards.json"),
        resource_path("data", "method_cards_manifest.json"),
    )

    assert len(store.cards) == 8
    assert len(store.store_hash) == 64
    assert store.library_version == "mathforge-reviewed-methods-2026-07-30"
    assert not load_competition_config().enable_rag
    assert not load_competition_config().enable_frozen_lemma_store
    balanced = HarnessConfig.from_json(resource_path("config", "balanced.json"))
    assert not balanced.enable_rag
    assert not balanced.enable_frozen_lemma_store


def test_judge_trace_projects_safe_tool_feedback_and_solve_state_isolated():
    client = FeedbackAwareClient()
    harness = MathForgeHarness(client, _config())
    first = harness.solve(FEEDBACK_PROBLEM, {})
    call_boundary = len(client.calls)
    second = harness.solve("Compute 2+2.", {})
    second_calls = client.calls[call_boundary:]
    projected = project_judge_trace(
        first["trace"],
        final_response=first["final_response"],
    )
    serialized = json.dumps(projected, ensure_ascii=False).casefold()

    assert any(
        event["event"] == "tool_feedback_completed"
        for event in projected
    )
    assert "scratchpad" not in serialized
    assert "chain_of_thought" not in serialized
    assert not any(
        event["event"] == "tool_feedback_completed"
        for event in second["trace"]
    )
    assert all(
        "r1-bad" not in message["content"]
        for call in second_calls
        for message in call
    )
