from __future__ import annotations

import json

import pytest

import mathforge.runtime as runtime_module
from mathforge.agents.verifier import VerifierSkepticAgent
from mathforge.config import HarnessConfig
from mathforge.harness.budget import CallBudget
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.harness.schemas import (
    CandidateSolution,
    Claim,
    ProblemIR,
    ProofObligation,
)
from mathforge.harness.trace import TraceBuilder
from mathforge.output.public_result import build_public_result
from mathforge.runtime import MathForgeHarness
from mathforge.verification.admission import (
    CandidateAdmissionDecision,
    CandidateAdmissionGate,
)
from scripts.formal_smoke_fixture import FormalSmokeClient


def _raise_runtime_bug(*args, **kwargs):
    del args, kwargs
    raise TypeError("private terminalization fault detail")


@pytest.mark.parametrize(
    "fault",
    [
        "close_trace_invariants",
        "proof_graph",
        "case_summary",
        "token_count",
        "budget_summary",
        "run_event",
        "metrics",
        "trace_build",
    ],
)
def test_terminalization_faults_never_escape_or_expose_raw_errors(
    monkeypatch,
    fault,
):
    harness = MathForgeHarness(FormalSmokeClient())
    if fault == "close_trace_invariants":
        monkeypatch.setattr(
            MathForgeHarness,
            "_close_trace_invariants",
            _raise_runtime_bug,
        )
    elif fault == "proof_graph":
        monkeypatch.setattr(
            runtime_module,
            "build_claim_evidence_graph",
            _raise_runtime_bug,
        )
    elif fault == "case_summary":
        monkeypatch.setattr(
            runtime_module,
            "build_case_trace_summary",
            _raise_runtime_bug,
        )
    elif fault == "token_count":
        monkeypatch.setattr(
            harness._context_budget,
            "ensure_text_within_window",
            _raise_runtime_bug,
        )
    elif fault == "budget_summary":
        monkeypatch.setattr(CallBudget, "to_dict", _raise_runtime_bug)
    elif fault == "run_event":
        original_add = TraceBuilder.add

        def fail_terminal_event(self, event, **details):
            if event == "run_completed":
                return _raise_runtime_bug()
            return original_add(self, event, **details)

        monkeypatch.setattr(TraceBuilder, "add", fail_terminal_event)
    elif fault == "metrics":
        monkeypatch.setattr(runtime_module, "collect_run_metrics", _raise_runtime_bug)
    else:
        monkeypatch.setattr(TraceBuilder, "build", _raise_runtime_bug)

    internal = harness.solve("Calculate the integer 1+1", {})
    result = build_public_result("terminalizer", internal)

    assert set(result) == {"id", "status", "final_response", "trace"}
    assert result["final_response"].strip()
    assert isinstance(result["trace"], list)
    assert "private terminalization fault detail" not in json.dumps(
        result,
        ensure_ascii=False,
    )


def test_debug_sink_fault_is_contained_by_terminalizer(monkeypatch):
    class RaisingDebugSink:
        def record(self, payload):
            del payload
            raise OSError("private debug sink path")

    harness = MathForgeHarness(
        FormalSmokeClient(),
        debug_sink=RaisingDebugSink(),
    )
    monkeypatch.setattr(harness._problem_parser, "parse", _raise_runtime_bug)

    result = harness.solve("Calculate the integer 1+1", {})

    assert result["final_response"].strip()
    assert isinstance(result["trace"], list)
    assert "private debug sink path" not in json.dumps(result)


def test_candidate_admission_rejects_fatal_answer_contract_errors():
    problem = ProblemIR(
        raw_problem="Return an integer.",
        normalized_problem="Return an integer.",
        problem_type="calculation",
        answer_type="integer",
    )
    invalid = CandidateSolution(
        "candidate",
        "PrimarySolver",
        "direct-deduction",
        "2.5",
        "integer",
        claims=[Claim("c1", "2.5 is the answer")],
    )

    decision = CandidateAdmissionGate().evaluate(invalid, problem)

    assert decision.accepted is False
    assert "invalid_integer" in decision.rejection_codes


def test_candidate_admission_rejects_overlong_recovered_answer_at_low_confidence():
    problem = ProblemIR(
        raw_problem="Return an expression.",
        normalized_problem="Return an expression.",
        problem_type="calculation",
        answer_type="expression",
        answer_type_confidence=0.78,
    )
    candidate = CandidateSolution(
        "candidate",
        "PrimarySolver",
        "direct-deduction",
        "x" * 5000,
        "expression",
        claims=[Claim("c1", "The expression is the answer")],
        parse_status="regex_answer",
        parse_tier="answer_recovered",
    )

    decision = CandidateAdmissionGate().evaluate(candidate, problem)

    assert decision.accepted is False
    assert "recovered_answer_too_long" in decision.rejection_codes


def test_candidate_admission_treats_method_text_deviation_as_diversity_signal():
    problem = ProblemIR(
        raw_problem="Return an integer.",
        normalized_problem="Return an integer.",
        problem_type="calculation",
        answer_type="integer",
    )
    candidate = CandidateSolution(
        "candidate",
        "PrimarySolver",
        "wrong-method",
        "2",
        "integer",
        claims=[Claim("c1", "2 is the answer")],
        contract_deviations=["method:planned_method_family"],
    )

    decision = CandidateAdmissionGate().evaluate(candidate, problem)

    assert decision.accepted is True
    assert decision.rejection_codes == []


class _InvalidIntegerClient(FormalSmokeClient):
    def chat(self, *, messages, temperature, max_tokens) -> str:
        payload = json.loads(super().chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        ))
        payload["final_answer"] = "2.5"
        return json.dumps(payload)


def test_invalid_candidate_cannot_reach_arbitration_when_tools_are_disabled():
    config = HarnessConfig(
        max_model_calls=1,
        model_max_concurrency=1,
        enable_router=False,
        enable_skills=False,
        enable_alternatives=False,
        enable_tools=False,
        enable_evidence=False,
        enable_proof_obligations=False,
        enable_verifier=False,
        enable_memory=False,
        enable_lemma_loop=False,
        enable_rag=False,
        enable_repair=False,
        enable_finalizer=False,
    )

    result = MathForgeHarness(_InvalidIntegerClient(), config).solve(
        "Which of the following is correct?\nA. 1+1=2\nB. 1+1=3",
        {},
    )

    assert result["run_metrics"]["outcome"] == "fallback"
    assert not any(
        event["event"] == "candidate_arbitrated"
        for event in result["trace"]
    )


def test_post_arbitration_admission_failure_forces_fallback(monkeypatch):
    config = HarnessConfig(
        max_model_calls=1,
        model_max_concurrency=1,
        enable_router=False,
        enable_skills=False,
        enable_alternatives=False,
        enable_tools=False,
        enable_evidence=False,
        enable_proof_obligations=False,
        enable_verifier=False,
        enable_memory=False,
        enable_lemma_loop=False,
        enable_rag=False,
        enable_repair=False,
        enable_finalizer=False,
    )
    harness = MathForgeHarness(FormalSmokeClient(), config)
    original_evaluate = harness._candidate_stage.evaluate
    evaluations = 0

    def reject_post_selection(*args, **kwargs):
        nonlocal evaluations
        evaluations += 1
        decision = original_evaluate(*args, **kwargs)
        if evaluations == 2:
            return CandidateAdmissionDecision(
                decision.candidate_id,
                False,
                ["post_selection_contract_failure"],
            )
        return decision

    monkeypatch.setattr(
        harness._candidate_stage,
        "evaluate",
        reject_post_selection,
    )

    result = harness.solve("Calculate 1+1.", {})

    assert result["run_metrics"]["outcome"] == "fallback"
    assert any(event["event"] == "fallback_used" for event in result["trace"])


def _verifier_inputs():
    problem = ProblemIR(
        raw_problem="Prove x=x.",
        normalized_problem="Prove x=x.",
        problem_type="proof",
        answer_type="text",
    )
    candidate = CandidateSolution(
        "candidate",
        "PrimarySolver",
        "direct-deduction",
        "QED",
        "text",
        claims=[Claim("c1", "x=x", check_type="sufficiency")],
    )
    return problem, candidate


def test_verifier_expected_transport_failure_is_fail_closed():
    class FailingClient:
        def chat(self, *, messages, temperature, max_tokens):
            del messages, temperature, max_tokens
            raise TimeoutError("private transport detail")

    provider = OfficialClientProvider(FailingClient(), ModelCallGate(1))
    verifier = VerifierSkepticAgent(provider)
    problem, candidate = _verifier_inputs()

    result = verifier.review(
        problem,
        [candidate],
        {
            "candidate": [
                ProofObligation(
                    "candidate:sufficiency",
                    "sufficiency",
                    "prove the conclusion",
                    source_claim_ids=["c1"],
                )
            ]
        },
        CallBudget(1),
        max_tokens=1024,
    )

    assert result.reason == "verifier_unavailable"
    assert result.findings == []


@pytest.mark.parametrize(
    "programming_error",
    [
        TypeError("private verifier type bug"),
        AssertionError("private verifier assertion"),
        AttributeError("private verifier attribute bug"),
    ],
)
def test_verifier_programming_error_propagates_to_runtime_fallback(
    monkeypatch,
    programming_error,
):
    harness = MathForgeHarness(
        FormalSmokeClient(),
        HarnessConfig(
            max_model_calls=2,
            model_max_concurrency=1,
            enable_router=False,
            enable_skills=False,
            enable_alternatives=False,
            enable_tools=True,
            enable_evidence=True,
            enable_proof_obligations=True,
            enable_verifier=True,
            enable_memory=False,
            enable_lemma_loop=False,
            enable_rag=False,
            enable_repair=False,
            enable_finalizer=False,
        ),
    )
    def raise_programming_error(*args, **kwargs):
        del args, kwargs
        raise programming_error

    monkeypatch.setattr(
        harness._verifier_agent,
        "review",
        raise_programming_error,
    )

    result = harness.solve("Prove that 1+1=2.", {})

    assert result["run_metrics"]["outcome"] == "primary"
    assert result["run_metrics"]["error_code"] == "degraded_candidate_salvage"
    assert any(event["event"] == "candidate_salvaged" for event in result["trace"])
    assert not any(event["event"] == "fallback_used" for event in result["trace"])
    assert not any(
        event.get("reason") == "verifier_unavailable"
        for event in result["trace"]
    )


class _PostVerifierRepairClient:
    def __init__(self) -> None:
        self.roles: list[str] = []

    @staticmethod
    def _candidate(*, repaired: bool) -> str:
        return json.dumps(
            {
                "method": "direct-deduction",
                "final_answer": "QED",
                "public_solution_steps": [
                    "Use the definitions and conclude the identity.",
                ],
                "claims": [
                    {
                        "claim_id": "definition",
                        "statement": "Equality is reflexive.",
                        "depends_on": [],
                        "check_type": "definition",
                        "importance": "critical",
                    },
                    {
                        "claim_id": "sufficiency",
                        "statement": (
                            "Therefore x equals x."
                            if repaired
                            else "The conclusion is asserted without support."
                        ),
                        "depends_on": ["definition"],
                        "check_type": "sufficiency",
                        "importance": "critical",
                    },
                    {
                        "claim_id": "boundary",
                        "statement": "The identity holds for every admissible x.",
                        "depends_on": ["sufficiency"],
                        "check_type": "boundary",
                        "importance": "critical",
                    },
                ],
                "method_steps": [
                    {
                        "step_id": "s1",
                        "kind": "conclusion",
                        "claim_ids": [
                            "definition",
                            "sufficiency",
                            "boundary",
                        ],
                        "theorem": "",
                    }
                ],
                "solution_text": (
                    "Equality is reflexive, so x=x."
                    if repaired
                    else "The conclusion is asserted without support."
                ),
                "assumptions": [],
                "theorems": [],
                "unresolved_obligations": [],
            }
        )

    @staticmethod
    def _verifier(candidate_id: str, *, repaired: bool) -> str:
        statuses = {
            "definition": "pass",
            "sufficiency": "pass" if repaired else "fail",
            "boundary": "pass",
        }
        return json.dumps(
            {
                "findings": [
                    {
                        "candidate_id": candidate_id,
                        "claim_id": claim_id,
                        "obligation_ids": [
                            f"{candidate_id}:{claim_id}",
                        ],
                        "status": status,
                        "public_rationale": f"{claim_id}:{status}",
                        "missing_condition": (
                            "justify the conclusion"
                            if status == "fail"
                            else ""
                        ),
                        "counterexample_summary": "",
                    }
                    for claim_id, status in statuses.items()
                ]
            }
        )

    def chat(self, *, messages, temperature, max_tokens) -> str:
        del temperature, max_tokens
        system = messages[0]["content"]
        if system.startswith("You are VerifierSkeptic"):
            role = "VerifierSkeptic"
            repaired = "primary-1-v2" in messages[-1]["content"]
            response = self._verifier(
                "primary-1-v2" if repaired else "primary-1",
                repaired=repaired,
            )
        elif system.startswith("You are RepairAgent"):
            role = "RepairAgent"
            response = self._candidate(repaired=True)
        else:
            role = "PrimarySolver"
            response = self._candidate(repaired=False)
        self.roles.append(role)
        return response


def test_one_post_verifier_repair_is_reverified_and_strictly_improves_proof():
    client = _PostVerifierRepairClient()
    config = HarnessConfig(
        max_model_calls=4,
        model_max_concurrency=1,
        enable_router=False,
        enable_skills=False,
        enable_alternatives=False,
        enable_tools=True,
        enable_evidence=True,
        enable_proof_obligations=True,
        enable_verifier=True,
        enable_memory=False,
        enable_lemma_loop=False,
        enable_rag=False,
        enable_repair=True,
        enable_finalizer=False,
    )

    result = MathForgeHarness(client, config).solve(
        "Prove that x equals x.",
        {},
    )

    post_repair = next(
        event
        for event in result["trace"]
        if event["event"] == "repair_completed"
        and event.get("repair_stage") == "post_verifier"
    )
    transitions = [
        event["to_phase"]
        for event in result["trace"]
        if event["event"] == "phase_transition"
    ]
    assert post_repair["rolled_back"] is False
    assert post_repair["reason"] == "accepted_post_verifier"
    assert client.roles.count("RepairAgent") == 1
    assert client.roles.count("VerifierSkeptic") == 2
    assert "reverified" in transitions
    assert result["run_metrics"]["outcome"] == "primary"
    verifier_evidence = [
        node
        for event in result["trace"]
        if event["event"] == "proof_graph_completed"
        for node in event["graph"]["nodes"]
        if node.get("evidence_type") == "llm:VerifierSkeptic"
    ]
    assert verifier_evidence
    assert all(node["strength"] == "soft" for node in verifier_evidence)


class _NoImprovementRepairClient(_PostVerifierRepairClient):
    @staticmethod
    def _verifier(candidate_id: str, *, repaired: bool) -> str:
        del repaired
        return _PostVerifierRepairClient._verifier(
            candidate_id,
            repaired=False,
        )


def test_post_verifier_repair_rolls_back_without_strict_improvement():
    client = _NoImprovementRepairClient()
    config = HarnessConfig(
        max_model_calls=4,
        model_max_concurrency=1,
        enable_router=False,
        enable_skills=False,
        enable_alternatives=False,
        enable_tools=True,
        enable_evidence=True,
        enable_proof_obligations=True,
        enable_verifier=True,
        enable_memory=False,
        enable_lemma_loop=False,
        enable_rag=False,
        enable_repair=True,
        enable_finalizer=False,
    )

    result = MathForgeHarness(client, config).solve(
        "Prove that x equals x.",
        {},
    )

    repair = next(
        event
        for event in result["trace"]
        if event["event"] == "repair_completed"
        and event.get("repair_stage") == "post_verifier"
    )
    assert repair["rolled_back"] is True
    assert repair["reason"] == "post_repair_proof_incomplete"
    assert client.roles.count("RepairAgent") == 1
    assert result["run_metrics"]["outcome"] == "primary"
