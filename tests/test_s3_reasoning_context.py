from __future__ import annotations

from dataclasses import replace
import json
import re

import pytest

from mathforge.agents.lemma_curator import LemmaCurator
from mathforge.context.assembler import ContextAssembler, RawContextStore
from mathforge.context.claim_graph import ClaimGraph
from mathforge.context.role_views import RoleContextFactory
from mathforge.harness.repair import ClaimRepairService
from mathforge.harness.schemas import (
    CandidateSolution,
    Claim,
    EvidenceRecord,
    LemmaCard,
    MethodStep,
    ProblemIR,
    RoutePlan,
    SchemaValidationError,
)
from mathforge.memory.blackboard import MemoryBlackboard
from mathforge.memory.session_memory import SessionMemory
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import SolutionParser
from mathforge.runtime import MathForgeHarness
from mathforge.verification.arbitration import ArbitrationPolicy
from mathforge.verification.evidence import EvidenceLedger
from mathforge.verification.methods import candidate_method_signature


def _candidate(
    candidate_id: str,
    answer: str,
    *,
    claims: list[Claim] | None = None,
    method: str = "free text",
    method_steps: list[MethodStep] | None = None,
) -> CandidateSolution:
    return CandidateSolution(
        candidate_id,
        "PrimarySolver",
        method,
        answer,
        "expression",
        claims=claims or [],
        method_steps=method_steps or [],
    )


def _evidence(candidate_id: str, claim_id: str, status: str) -> EvidenceRecord:
    return EvidenceRecord(
        f"ev-{candidate_id}-{claim_id}",
        candidate_id,
        claim_id,
        "tool:symbolic_equivalence",
        status,
        "hard",
        "check",
        capability="equality.symbolic_under_domain",
    )


def test_claim_graph_namespaces_same_claim_ids_across_candidates_and_round_trips():
    first = _candidate("primary", "1", claims=[Claim("step", "first")])
    second = _candidate("alternative", "1", claims=[Claim("step", "second")])

    graph = ClaimGraph.from_candidates([first, second])
    assert graph.to_dict()["nodes"] == {
        "alternative::step": [],
        "primary::step": [],
    }
    assert ClaimGraph.from_dict(graph.to_dict()).to_dict() == graph.to_dict()


def test_context_assembler_keeps_cross_candidate_claim_namespaces():
    first = _candidate(
        "primary",
        "1",
        claims=[Claim("base", "first"), Claim("result", "done", ["base"])],
    )
    second = _candidate(
        "alternative",
        "1",
        claims=[Claim("base", "second"), Claim("result", "done", ["base"])],
    )
    snapshot = ContextAssembler(RawContextStore(2000)).assemble(
        ProblemParser().parse("solve x=1"),
        [first, second],
        [],
        {},
    )
    assert snapshot.claim_graph == {
        "alternative::base": [],
        "alternative::result": ["alternative::base"],
        "primary::base": [],
        "primary::result": ["primary::base"],
    }


def test_repair_dependency_changes_recompute_union_impact_closure():
    candidate = _candidate(
        "candidate",
        "1",
        claims=[
            Claim("base", "old base", status="verified"),
            Claim("new_base", "new base", status="verified"),
            Claim("failed", "bad", ["base"], status="rejected"),
            Claim("consumer", "uses result", ["failed"], status="verified"),
        ],
    )
    evidence = [_evidence("candidate", "failed", "fail")]
    observed: list[str] = []

    def repair(*_):
        return CandidateSolution(
            "patch",
            "RepairAgent",
            "local",
            "1",
            "expression",
            claims=[Claim("failed", "fixed", ["new_base"])],
        )

    def reverify(proposed, affected):
        observed.extend(affected)
        return [
            _evidence(proposed.candidate_id, claim_id, "pass")
            for claim_id in affected
        ]

    result = ClaimRepairService().attempt(
        candidate,
        evidence,
        repair=repair,
        reverify=reverify,
    )
    assert not result.rolled_back
    assert observed == ["base", "consumer", "failed", "new_base"]
    assert result.affected_claim_ids == observed


def test_rolled_back_repair_evidence_is_a_rejected_transaction():
    candidate = _candidate(
        "candidate",
        "1",
        claims=[Claim("failed", "bad", status="rejected")],
    )
    evidence = [_evidence("candidate", "failed", "fail")]

    result = ClaimRepairService().attempt(
        candidate,
        evidence,
        repair=lambda *_: CandidateSolution(
            "patch",
            "RepairAgent",
            "local",
            "1",
            "expression",
            claims=[Claim("failed", "still bad")],
        ),
        reverify=lambda proposed, _: [
            _evidence(proposed.candidate_id, "failed", "fail")
        ],
    )

    assert result.rolled_back
    assert result.new_evidence[0].transaction_status == "rejected"
    assert not EvidenceLedger(result.new_evidence).has_hard_fail(
        result.new_evidence[0].candidate_id
    )


def test_repair_rejects_a_new_dangling_dependency_before_reverification():
    candidate = _candidate(
        "candidate",
        "1",
        claims=[Claim("failed", "bad", status="rejected")],
    )
    evidence = [_evidence("candidate", "failed", "fail")]
    reverified = False

    def reverify(*_):
        nonlocal reverified
        reverified = True
        return []

    result = ClaimRepairService().attempt(
        candidate,
        evidence,
        repair=lambda *_: CandidateSolution(
            "patch",
            "RepairAgent",
            "local",
            "1",
            "expression",
            claims=[Claim("failed", "fixed", ["missing"])],
        ),
        reverify=reverify,
    )

    assert result.rolled_back
    assert result.reason == "invalid_repair_graph"
    assert not reverified


def test_assumption_aware_equivalence_uses_host_problem_type_and_domain():
    problem = ProblemIR(
        raw_problem="For x in R and x >= 0, simplify sqrt(x^2)",
        normalized_problem="For x in R and x >= 0, simplify sqrt(x^2)",
        problem_type="calculation",
        answer_type="expression",
        assumptions=["x >= 0"],
        domains={"x": "R"},
    )
    left = _candidate("left", "sqrt(x^2)")
    right = _candidate("right", "x")
    left.answer_type = right.answer_type = "text"

    result = ArbitrationPolicy().select([left, right], [], {}, problem=problem)

    assert result.clusters == [["left", "right"]]
    assert result.unknown_pairs == []
    assert result.disagreement_pairs == []


def test_high_risk_equivalence_without_domain_is_unknown_not_disagreement():
    problem = ProblemParser().parse("Simplify the radical sqrt(x^2)")
    first = _candidate("first", "sqrt(x^2)")
    second = _candidate("second", "x")

    result = ArbitrationPolicy().select([first, second], [], {}, problem=problem)

    assert result.clusters == [["first"], ["second"]]
    assert result.unknown_pairs == [("first", "second")]
    assert result.disagreement_pairs == []


def test_method_signature_ignores_free_text_and_uses_structured_steps():
    claims = [Claim("base", "premise"), Claim("finish", "result", ["base"])]
    same_topology_a = _candidate("a", "1", claims=claims, method="substitution")
    same_topology_b = _candidate("b", "1", claims=claims, method="renamed clever trick")
    assert candidate_method_signature(same_topology_a) == candidate_method_signature(
        same_topology_b
    )

    direct = _candidate(
        "direct",
        "1",
        claims=claims,
        method_steps=[
            MethodStep("s1", "transformation", ["base"]),
            MethodStep("s2", "conclusion", ["finish"]),
        ],
    )
    contradiction = _candidate(
        "contradiction",
        "1",
        claims=claims,
        method_steps=[
            MethodStep("s1", "contradiction", ["base", "finish"]),
        ],
    )
    assert candidate_method_signature(direct) != candidate_method_signature(
        contradiction
    )


def test_structured_method_and_namespaced_lemma_contracts_round_trip():
    candidate = _candidate(
        "candidate",
        "1",
        claims=[Claim("base", "x = x", check_type="symbolic_equivalence")],
        method_steps=[MethodStep("s1", "conclusion", ["base"])],
    )
    candidate.validate()
    assert CandidateSolution.from_dict(candidate.to_dict()).to_dict() == candidate.to_dict()

    lemma = LemmaCurator().curate([candidate], round_id=1)[0]
    lemma.validate()
    assert LemmaCard.from_dict(lemma.to_dict()).to_dict() == lemma.to_dict()
    assert lemma.lemma_id.startswith("candidate::lemma::base-")


def test_solution_parser_accepts_only_structured_method_steps_with_real_claims():
    candidate = SolutionParser().parse(
        json.dumps(
            {
                "method": "direct-deduction",
                "solution_text": "work",
                "final_answer": "1",
                "claims": [{"claim_id": "base", "statement": "x = x"}],
                "method_steps": [
                    {
                        "step_id": "s1",
                        "kind": "conclusion",
                        "claim_ids": ["base", "missing"],
                    }
                ],
            }
        ),
        candidate_id="candidate",
        role="PrimarySolver",
        answer_type="expression",
    )

    assert candidate.method_steps[0].claim_ids == ["base"]
    assert "method_steps[0].claim_ids:unknown" in candidate.contract_deviations


def test_route_rejects_uncontrolled_method_family():
    route = RoutePlan(
        "algebra",
        None,
        "calculation",
        "expression",
        "low",
        method_families=["invented-free-text-method"],
    )
    with pytest.raises(SchemaValidationError, match="method families"):
        route.validate()


def test_method_contract_deviation_never_earns_independent_agreement():
    claims = [Claim("base", "premise"), Claim("finish", "result", ["base"])]
    deviating = _candidate(
        "deviating",
        "1",
        claims=claims,
        method_steps=[MethodStep("s1", "transformation", ["base", "finish"])],
    )
    deviating.contract_deviations.append("method:planned_method_family")
    independent = _candidate(
        "independent",
        "1",
        claims=claims,
        method_steps=[MethodStep("s1", "contradiction", ["base", "finish"])],
    )

    result = ArbitrationPolicy().select([deviating, independent], [], {})
    ranks = {rank.candidate_id: rank for rank in result.ranks}
    assert ranks["deviating"].independent_agreement == 0
    assert ranks["independent"].independent_agreement == 0


def test_session_raw_store_resolves_all_role_references_and_prompt_size_is_exact():
    problem = ProblemParser().parse("solve x=1")
    store = RawContextStore(2000)
    board = MemoryBlackboard(SessionMemory())
    board.publish("System", "raw", {"metadata": {"idx": 1}})
    factory = RoleContextFactory()

    first = factory.build(
        problem=problem,
        candidates=[],
        evidence=[],
        obligations={},
        blackboard=board,
        role="PrimarySolver",
        max_chars=1000,
        raw_store=store,
    )
    second = factory.build(
        problem=problem,
        candidates=[],
        evidence=[],
        obligations={},
        blackboard=board,
        role="VerifierSkeptic",
        max_chars=1000,
        raw_store=store,
    )

    assert store.resolve(first.payload["raw_context_ref"]) == problem.raw_problem
    assert store.resolve(second.payload["raw_context_ref"]) == problem.raw_problem
    assert store.stored_chars == len(problem.raw_problem)
    assert first.char_count == len(first.to_prompt_json())


class _LemmaIsolationClient:
    def __init__(self, *, review_expanded: bool = True) -> None:
        self.review_expanded = review_expanded
        self.calls: list[list[dict[str, str]]] = []
        self.solver_calls = 0
        self.verifier_candidate_ids: list[str] = []

    def chat(self, *, messages, temperature, max_tokens):
        del temperature, max_tokens
        self.calls.append(messages)
        system = messages[0]["content"]
        user = messages[-1]["content"]
        if system.startswith("You are VerifierSkeptic"):
            batch = json.loads(user.split("Batch:\n", 1)[1])
            self.verifier_candidate_ids = [
                candidate["candidate_id"] for candidate in batch["candidates"]
            ]
            findings = []
            for candidate in batch["candidates"]:
                if (
                    candidate["candidate_id"].startswith("lemma-round")
                    and not self.review_expanded
                ):
                    continue
                for obligation in candidate["obligations"]:
                    findings.append(
                        {
                            "candidate_id": candidate["candidate_id"],
                            "claim_id": obligation["kind"],
                            "obligation_ids": [obligation["obligation_id"]],
                            "status": "pass",
                            "description": "reviewed",
                        }
                    )
            return json.dumps({"findings": findings})

        self.solver_calls += 1
        family = re.search(r"Required core method family: ([^.\n]+)", user)
        method = family.group(1) if family else "direct-deduction"
        historical_marker = (
            "HISTORICAL_PRIVATE_SOLUTION"
            if self.solver_calls == 1
            else "EXPANDED_SOLUTION"
        )
        return json.dumps(
            {
                "method": method,
                "solution_text": historical_marker,
                "final_answer": "QED",
                "claims": [
                    {
                        "claim_id": f"identity{index}",
                        "statement": statement,
                        "check_type": "symbolic_equivalence",
                        "depends_on": (
                            [f"identity{index - 1}"]
                            if index > 1
                            else []
                        ),
                    }
                    for index, statement in enumerate(
                        ("x = x", "x+0 = x", "2*x = 2*x", "x*1 = x"),
                        start=1,
                    )
                ]
                + [
                    {
                        "claim_id": "definition",
                        "statement": "definition is supplied",
                        "check_type": "definition",
                    },
                    {
                        "claim_id": "sufficiency",
                        "statement": "sufficiency is supplied",
                        "check_type": "sufficiency",
                    },
                    {
                        "claim_id": "boundary",
                        "statement": "boundary is supplied",
                        "check_type": "boundary",
                    },
                ],
            }
        )


def _lemma_config():
    from mathforge.config import HarnessConfig

    return replace(
        HarnessConfig(),
        max_model_calls=3,
        model_max_concurrency=1,
        enable_router=False,
        enable_skills=False,
        enable_alternatives=False,
        enable_tools=True,
        enable_evidence=True,
        enable_proof_obligations=True,
        enable_verifier=True,
        enable_memory=True,
        enable_lemma_loop=True,
        enable_rag=False,
        enable_repair=False,
        enable_finalizer=False,
    )


def test_lemma_second_round_is_history_free_and_expanded_candidate_is_batch_reviewed():
    client = _LemmaIsolationClient()
    result = MathForgeHarness(client, _lemma_config()).solve(
        "Prove that x equals x",
        {
            "idx": 7,
            "benchmark_nonce": "public-nonce",
            "api_key": "MODEL_SECRET",
            "local_path": r"C:\private\answer.txt",
            "private_note": "DO_NOT_SEND",
        },
    )

    solver_prompts = [
        messages[-1]["content"]
        for messages in client.calls
        if messages[0]["content"].startswith("You are PrimarySolver")
    ]
    assert len(solver_prompts) == 2
    assert "HISTORICAL_PRIVATE_SOLUTION" not in solver_prompts[1]
    assert "Verified problem-local lemmas" in solver_prompts[1]
    assert solver_prompts[1].count("Prove that x equals x") == 1
    assert client.verifier_candidate_ids == ["primary-1", "lemma-round-2"]
    assert all(
        secret not in json.dumps(client.calls)
        for secret in ("MODEL_SECRET", r"C:\private\answer.txt", "DO_NOT_SEND")
    )
    reverified = next(
        event
        for event in result["trace"]
        if event["event"] == "expanded_candidates_reverified"
    )
    assert reverified["accepted"] == ["lemma-round-2"]
    assert reverified["skeptic_reviewed"] == ["lemma-round-2"]
    assert reverified["verification_chain"]["lemma-round-2"] == {
        "schema_validated": True,
        "answer_validated": True,
        "answer_shape_checked": True,
        "claims_reverified": True,
        "obligations_regenerated": True,
        "skeptic_reviewed": True,
        "final_status": "accepted",
    }
    lemma_trace = next(
        event
        for event in result["trace"]
        if event["event"] == "lemma_loop_completed"
    )
    assert lemma_trace["lemmas"]
    assert lemma_trace["round_states"]
    assert lemma_trace["downstream_usage"]["lemma-round-2"]
    assert lemma_trace["eligibility"]["eligible"] is True
    arbitration = next(
        event for event in result["trace"] if event["event"] == "candidate_arbitrated"
    )
    assert "lemma-round-2" in {
        candidate_id
        for cluster in arbitration["equivalence_clusters"]
        for candidate_id in cluster
    }


def test_expanded_candidate_without_skeptic_completion_cannot_enter_arbitration():
    client = _LemmaIsolationClient(review_expanded=False)
    result = MathForgeHarness(client, _lemma_config()).solve(
        "Prove that x equals x",
        {},
    )

    reverified = next(
        event
        for event in result["trace"]
        if event["event"] == "expanded_candidates_reverified"
    )
    assert reverified["rejected"] == ["lemma-round-2"]
    arbitration = next(
        event for event in result["trace"] if event["event"] == "candidate_arbitrated"
    )
    assert "lemma-round-2" not in {
        candidate_id
        for cluster in arbitration["equivalence_clusters"]
        for candidate_id in cluster
    }
