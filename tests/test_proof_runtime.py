from __future__ import annotations

from dataclasses import replace
import json

from mathforge.config import HarnessConfig
from mathforge.runtime import MathForgeHarness


def _proof_config() -> HarnessConfig:
    return HarnessConfig(
        max_model_calls=2,
        model_max_concurrency=1,
        enable_router=False,
        enable_skills=False,
        enable_alternatives=False,
        enable_tools=False,
        enable_evidence=True,
        enable_proof_obligations=True,
        enable_verifier=True,
        enable_memory=False,
        enable_lemma_loop=False,
        enable_rag=False,
        enable_repair=False,
        enable_finalizer=False,
    )


class ProofClient:
    def __init__(self, *, claimless: bool = False, invalid_verifier: bool = False) -> None:
        self.claimless = claimless
        self.invalid_verifier = invalid_verifier
        self.calls = []

    def chat(self, *, messages, temperature, max_tokens):
        del temperature, max_tokens
        self.calls.append(messages)
        role = messages[0]["content"]
        if role.startswith("You are VerifierSkeptic"):
            if self.invalid_verifier:
                return "not JSON"
            findings = []
            for kind in ("definition", "sufficiency", "boundary"):
                findings.append(
                    {
                        "candidate_id": "primary-1",
                        "claim_id": kind if not self.claimless else "invented",
                        "obligation_ids": [f"primary-1:{kind}"],
                        "status": "pass",
                        "description": f"{kind} is supported",
                    }
                )
            return json.dumps({"findings": findings})
        claims = []
        if not self.claimless:
            claims = [
                {
                    "claim_id": kind,
                    "statement": f"{kind}: justified step",
                    "check_type": kind,
                    "importance": "required",
                }
                for kind in ("definition", "sufficiency", "boundary")
            ]
        return json.dumps(
            {
                "method": "direct",
                "solution_text": (
                    "Assertion only." if self.claimless else "Complete structured proof."
                ),
                "final_answer": "QED",
                "answer_type": "text",
                "claims": claims,
            }
        )


def test_claimless_proof_falls_back_even_when_skeptic_claims_pass():
    result = MathForgeHarness(ProofClient(claimless=True), _proof_config()).solve(
        "Prove that x equals x", {}
    )
    assert "Assertion only" not in result["final_response"]
    assert result["trace"][-1]["event"] == "fallback_used"
    gate = next(event for event in result["trace"] if event["event"] == "proof_completion_gate")
    assert gate["accepted"] == []
    assert gate["rejected"][0]["status"] == "incomplete"


def test_structured_proof_with_mapped_skeptic_findings_passes_gate():
    client = ProofClient()
    result = MathForgeHarness(client, _proof_config()).solve("Prove that x equals x", {})
    assert "Complete structured proof" in result["final_response"]
    gate = next(event for event in result["trace"] if event["event"] == "proof_completion_gate")
    assert gate["accepted"] == ["primary-1"]
    verifier = next(event for event in result["trace"] if event["event"] == "verifier_completed")
    assert verifier["finding_count"] == 3
    assert len(client.calls) == 2


def test_invalid_verifier_output_cannot_complete_proof():
    result = MathForgeHarness(ProofClient(invalid_verifier=True), _proof_config()).solve(
        "Prove that x equals x", {}
    )
    assert result["trace"][-1]["event"] == "fallback_used"
    verifier = next(event for event in result["trace"] if event["event"] == "verifier_completed")
    assert verifier["reason"] == "invalid_or_empty_findings"


class RoutedProofClient:
    def __init__(self) -> None:
        self.roles = []

    def chat(self, *, messages, temperature, max_tokens):
        del temperature, max_tokens
        system = messages[0]["content"]
        self.roles.append(system)
        if system.startswith("You are RouterPlanner"):
            return '{"primary_subject":"general-math","risk_level":"high"}'
        if system.startswith("You are VerifierSkeptic"):
            batch = json.loads(messages[-1]["content"].split("Batch:\n", 1)[1])
            findings = [
                {
                    "candidate_id": candidate["candidate_id"],
                    "claim_id": obligation["kind"],
                    "obligation_ids": [obligation["obligation_id"]],
                    "status": "pass",
                }
                for candidate in batch["candidates"]
                for obligation in candidate["obligations"]
            ]
            return json.dumps({"findings": findings})
        return json.dumps(
            {
                "method": "direct",
                "solution_text": "Complete routed proof.",
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


def test_runtime_reserves_one_call_for_verifier_after_router():
    client = RoutedProofClient()
    config = replace(
        _proof_config(),
        max_model_calls=4,
        model_max_concurrency=2,
        enable_router=True,
        enable_alternatives=True,
    )
    result = MathForgeHarness(client, config).solve("Prove that x equals x", {})
    assert "Complete routed proof" in result["final_response"]
    assert len(client.roles) == 4
    assert sum(role.startswith("You are VerifierSkeptic") for role in client.roles) == 1
    budget = next(event for event in result["trace"] if event["event"] == "budget_summary")
    assert budget["model_calls"] == 4
