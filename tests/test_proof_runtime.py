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


def _proof_candidate(solution_text: str, claims: list[dict]) -> dict:
    normalized_claims = []
    for claim in claims:
        normalized_claims.append(
            {
                **claim,
                "depends_on": list(claim.get("depends_on", [])),
                "importance": claim.get("importance", "critical"),
            }
        )
    return {
        "method": "direct",
        "method_steps": [
            {
                "step_id": "s1",
                "kind": "conclusion",
                "claim_ids": [normalized_claims[-1]["claim_id"]],
                "theorem": "",
            }
        ],
        "solution_text": solution_text,
        "public_solution_steps": [solution_text],
        "final_answer": "QED",
        "assumptions": [],
        "theorems": [],
        "claims": normalized_claims,
        "unresolved_obligations": [],
    }


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
        if self.claimless:
            claims = [
                {
                    "claim_id": "assertion",
                    "statement": "The result is asserted without proof.",
                    "check_type": "reasoning",
                    "importance": "critical",
                }
            ]
        else:
            claims = [
                {
                    "claim_id": kind,
                    "statement": f"{kind}: justified step",
                    "check_type": kind,
                    "importance": "critical",
                }
                for kind in ("definition", "sufficiency", "boundary")
            ]
        return json.dumps(
            _proof_candidate(
                "Assertion only." if self.claimless else "Complete structured proof.",
                claims,
            )
        )


def test_claimless_proof_falls_back_even_when_skeptic_claims_pass():
    result = MathForgeHarness(ProofClient(claimless=True), _proof_config()).solve(
        "Prove that x equals x", {}
    )
    assert "Assertion only" not in result["final_response"]
    assert result["trace"][-1]["event"] == "run_completed"
    assert result["run_metrics"]["error_code"] == "proof_incomplete"
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
    assert result["trace"][-1]["event"] == "run_completed"
    assert result["run_metrics"]["error_code"] == "proof_incomplete"
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
            _proof_candidate(
                "Complete routed proof.",
                [
                    {
                        "claim_id": kind,
                        "statement": f"{kind}: justified step",
                        "check_type": kind,
                    }
                    for kind in ("definition", "sufficiency", "boundary")
                ],
            )
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


class RepairPressureProofClient:
    def __init__(self) -> None:
        self.roles: list[str] = []

    def chat(self, *, messages, temperature, max_tokens):
        del temperature, max_tokens
        role = messages[0]["content"]
        self.roles.append(role)
        if role.startswith("You are VerifierSkeptic"):
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
        if role.startswith("You are PrimarySolver"):
            claims = [
                {
                    "claim_id": "failed",
                    "statement": "x = x + 1",
                    "check_type": "symbolic_equivalence",
                }
            ]
        else:
            claims = [
                {
                    "claim_id": kind,
                    "statement": f"{kind}: supported",
                    "check_type": kind,
                }
                for kind in ("definition", "sufficiency", "boundary")
            ]
        return json.dumps(
            _proof_candidate("Complete alternative proof.", claims)
        )


def test_optional_repair_cannot_consume_required_verifier_call():
    client = RepairPressureProofClient()
    config = replace(
        _proof_config(),
        max_model_calls=3,
        model_max_concurrency=2,
        enable_alternatives=True,
        enable_tools=True,
        enable_repair=True,
    )
    result = MathForgeHarness(client, config).solve("Prove that x equals x", {})

    assert any(role.startswith("You are AlternativeSolver") for role in client.roles)
    assert any(role.startswith("You are VerifierSkeptic") for role in client.roles)
    assert not any(role.startswith("You are RepairAgent") for role in client.roles)
    allocation = next(
        event
        for event in result["trace"]
        if event["event"] == "call_allocation_rebalanced"
    )
    assert allocation["verifier"] == 1
    assert allocation["repair_reserve"] == 0
    assert "repair" in allocation["unreachable_by_budget"]
    assert allocation["repair_unreachable_reason"]
    assert result["run_metrics"]["model_calls"] == 3


class SyntaxOnlyProofClient:
    def chat(self, *, messages, temperature, max_tokens):
        del messages, temperature, max_tokens
        return json.dumps(
            _proof_candidate(
                "Unsupported assertions only.",
                [
                    {
                        "claim_id": kind,
                        "statement": f"{kind} is handled",
                        "check_type": "latex_syntax_check",
                        "importance": "critical",
                    }
                    for kind in ("definition", "sufficiency", "uniqueness", "boundary")
                ],
            )
        )


def test_syntax_checks_cannot_complete_mathematical_proof_obligations():
    config = replace(
        _proof_config(),
        max_model_calls=1,
        enable_tools=True,
        enable_verifier=False,
    )
    result = MathForgeHarness(SyntaxOnlyProofClient(), config).solve(
        "Prove that the solution is unique.", {}
    )
    assert "Unsupported assertions" not in result["final_response"]
    gate = next(event for event in result["trace"] if event["event"] == "proof_completion_gate")
    assert gate["accepted"] == []
    assert {
        item.rsplit(":", 1)[-1]
        for item in gate["rejected"][0]["unresolved_obligation_ids"]
    } == {"definition", "sufficiency", "uniqueness", "boundary"}
    assert result["trace"][-1]["event"] == "run_completed"
    assert result["run_metrics"]["error_code"] == "proof_incomplete"
