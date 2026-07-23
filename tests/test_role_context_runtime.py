from __future__ import annotations

from dataclasses import replace
import json

from mathforge.agents.registry import PromptContractLoader
from mathforge.config import HarnessConfig
from mathforge.context.role_views import RoleContextFactory
from mathforge.harness.schemas import CandidateSolution, Claim
from mathforge.memory.blackboard import MemoryBlackboard
from mathforge.memory.session_memory import SessionMemory
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.runtime import MathForgeHarness


_ROLE_DIRECTORIES = {
    "RouterPlanner": "router_planner",
    "PrimarySolver": "primary_solver",
    "AlternativeSolver": "alternative_solver",
    "VerifierSkeptic": "verifier_skeptic",
    "LLMFinalizer": "finalizer",
}


class ContextCaptureClient:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, *, messages, temperature, max_tokens):
        del temperature, max_tokens
        self.calls.append(messages)
        system = messages[0]["content"]
        if system.startswith("You are RouterPlanner"):
            return '{"primary_subject":"general-math","risk_level":"high"}'
        if system.startswith("You are VerifierSkeptic"):
            batch = json.loads(messages[-1]["content"].split("Batch:\n", 1)[1])
            return json.dumps(
                {
                    "findings": [
                        {
                            "candidate_id": candidate["candidate_id"],
                            "claim_id": obligation["kind"],
                            "obligation_ids": [obligation["obligation_id"]],
                            "status": "pass",
                        }
                        for candidate in batch["candidates"]
                        for obligation in candidate["obligations"]
                    ]
                }
            )
        private_text = (
            "PRIMARY_PRIVATE_DERIVATION"
            if system.startswith("You are PrimarySolver")
            else "INDEPENDENT_ALTERNATIVE"
        )
        return json.dumps(
            {
                "method": "direct",
                "solution_text": private_text,
                "final_answer": "QED",
                "answer_type": "text",
                "claims": [
                    {
                        "claim_id": kind,
                        "statement": f"{kind}: justified step",
                        "check_type": kind,
                    }
                    for kind in ("definition", "sufficiency", "boundary")
                ],
            }
        )


def test_runtime_role_calls_use_budgeted_views_without_private_derivation_leaks():
    client = ContextCaptureClient()
    config = replace(
        HarnessConfig(),
        max_model_calls=4,
        model_max_concurrency=2,
        enable_skills=False,
        enable_tools=False,
        enable_evidence=True,
        enable_proof_obligations=True,
        enable_memory=True,
        enable_lemma_loop=False,
        enable_rag=False,
        enable_repair=False,
        enable_finalizer=False,
    )
    result = MathForgeHarness(client, config).solve("Prove that x equals x", {})

    loader = PromptContractLoader()
    for messages in client.calls:
        role = messages[0]["content"].split("You are ", 1)[1].split(".", 1)[0]
        budget = loader.load(_ROLE_DIRECTORIES[role]).max_context_chars
        assert sum(len(message["content"]) for message in messages) <= budget
        assert "context_snapshot_id" in messages[-1]["content"]

    alternative = next(
        messages[-1]["content"]
        for messages in client.calls
        if messages[0]["content"].startswith("You are AlternativeSolver")
    )
    verifier = next(
        messages[-1]["content"]
        for messages in client.calls
        if messages[0]["content"].startswith("You are VerifierSkeptic")
    )
    assert "PRIMARY_PRIVATE_DERIVATION" not in alternative
    assert "PRIMARY_PRIVATE_DERIVATION" not in verifier
    assert "solution_text" not in verifier
    assert "Complete" in result["final_response"] or "DERIVATION" in result["final_response"]


def test_blackboard_permissions_and_repair_dependency_closure_shape_role_views():
    memory = SessionMemory()
    blackboard = MemoryBlackboard(memory)
    blackboard.publish("System", "raw", {"problem": "prove P"})
    blackboard.publish("System", "working", {"primary_secret": "hidden"})
    candidate = CandidateSolution(
        candidate_id="primary-1",
        role="PrimarySolver",
        method="direct",
        final_answer="P",
        answer_type="text",
        claims=[
            Claim("c1", "needed premise"),
            Claim("c2", "failed conclusion", ["c1"]),
            Claim("c3", "unrelated claim"),
        ],
        solution_text="full private derivation",
    )
    factory = RoleContextFactory()
    problem = ProblemParser().parse("prove P")

    alternative = factory.build(
        problem=problem,
        candidates=[candidate],
        evidence=[],
        obligations={},
        blackboard=blackboard,
        role="AlternativeSolver",
        max_chars=4000,
    )
    repair = factory.build(
        problem=problem,
        candidates=[candidate],
        evidence=[],
        obligations={},
        blackboard=blackboard,
        role="RepairAgent",
        max_chars=4000,
        focus_claim_ids=["c2"],
    )

    authorized = alternative.payload["metadata"]["authorized_memory"]
    assert {item["category"] for item in authorized} == {"raw"}
    assert "hidden" not in alternative.to_json()
    assert "full private derivation" not in alternative.to_json()
    assert {
        claim["claim_id"] for claim in repair.payload["candidates"][0]["claims"]
    } == {"c1", "c2"}
    assert "c3" not in repair.to_json()
    assert repair.char_count <= repair.max_chars


def test_runtime_finalizer_receives_a_budgeted_authorized_view():
    client = ContextCaptureClient()
    config = replace(
        HarnessConfig(),
        max_model_calls=2,
        enable_router=False,
        enable_skills=False,
        enable_alternatives=False,
        enable_tools=False,
        enable_evidence=False,
        enable_proof_obligations=False,
        enable_verifier=False,
        enable_memory=True,
        enable_lemma_loop=False,
        enable_rag=False,
        enable_repair=False,
        enable_finalizer=True,
    )
    MathForgeHarness(client, config).solve("Explain why x equals x", {})
    finalizer_messages = next(
        messages
        for messages in client.calls
        if messages[0]["content"].startswith("You are LLMFinalizer")
    )
    budget = PromptContractLoader().load("finalizer").max_context_chars
    assert sum(len(message["content"]) for message in finalizer_messages) <= budget
    assert "context_snapshot_id" in finalizer_messages[-1]["content"]
