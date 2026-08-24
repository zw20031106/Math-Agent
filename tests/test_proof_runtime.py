from __future__ import annotations

from dataclasses import replace
import json
import re

from mathforge.agents.finalizer import FinalizationResult
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


def _assigned_method(messages) -> str:
    match = re.search(
        r"Required core method family: ([a-z-]+)\.",
        messages[-1]["content"],
    )
    return match.group(1) if match is not None else "direct-deduction"


def _proof_candidate(
    solution_text: str,
    claims: list[dict],
    *,
    method: str = "direct-deduction",
) -> dict:
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
        "method": method,
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
            for index, kind in enumerate(
                ("definition", "sufficiency", "boundary"),
                start=1,
            ):
                findings.append(
                    {
                        "candidate_id": "primary-1",
                        "claim_id": (
                            f"host-c{index}" if not self.claimless else "invented"
                        ),
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
                method=_assigned_method(messages),
            )
        )


def test_incomplete_proof_is_retained_as_best_available_candidate():
    result = MathForgeHarness(ProofClient(claimless=True), _proof_config()).solve(
        "Prove that x equals x", {}
    )
    assert "Assertion only" in result["final_response"]
    assert result["trace"][-1]["event"] == "run_completed"
    assert result["run_metrics"]["outcome"] == "primary"
    assert result["run_metrics"]["error_code"] == ""
    gate = next(event for event in result["trace"] if event["event"] == "proof_completion_gate")
    assert gate["accepted"] == ["primary-1"]
    assert gate["fully_verified"] == []
    assert gate["degraded_accepted"] == ["primary-1"]
    assert gate["rejected"] == []
    proof_status = next(
        event
        for event in result["trace"]
        if event["event"] == "proof_status_finalized"
    )
    assert proof_status["statuses"][0]["status"] == "incomplete"
    formal = next(
        event
        for event in result["trace"]
        if event["event"] == "formal_entry_compatibility"
    )
    assert formal["immutable_files"] == ["main.py", "llm_client.py"]
    assert formal["harness_status_limitation"]


def test_structured_proof_with_mapped_skeptic_findings_passes_gate():
    client = ProofClient()
    result = MathForgeHarness(client, _proof_config()).solve("Prove that x equals x", {})
    assert "Complete structured proof" in result["final_response"]
    gate = next(event for event in result["trace"] if event["event"] == "proof_completion_gate")
    assert gate["accepted"] == ["primary-1"]
    verifier = next(event for event in result["trace"] if event["event"] == "verifier_completed")
    assert verifier["finding_count"] == 3
    assert len(client.calls) == 2


class LowRiskTheoremClient:
    def __init__(self) -> None:
        self.roles: list[str] = []

    def chat(self, *, messages, temperature, max_tokens):
        del temperature, max_tokens
        role = messages[0]["content"]
        self.roles.append(role)
        if role.startswith("You are VerifierSkeptic"):
            return json.dumps(
                {
                    "findings": [
                        {
                            "candidate_id": "primary-1",
                            "claim_id": "host-c1",
                            "obligation_ids": [
                                "primary-1:theorem_preconditions"
                            ],
                            "status": "pass",
                            "public_rationale": (
                                "The stated arithmetic definitions apply."
                            ),
                            "missing_condition": "",
                            "counterexample_summary": "",
                        }
                    ]
                }
            )
        return json.dumps(
            {
                "method": "direct-analytic",
                "method_steps": [
                    {
                        "step_id": "s1",
                        "kind": "theorem_application",
                        "claim_ids": ["conditions"],
                        "theorem": "Elementary limit law",
                    }
                ],
                "solution_text": "The elementary limit law gives 1/n to 0.",
                "public_solution_steps": [
                    "Apply the elementary limit law."
                ],
                "final_answer": "0",
                "assumptions": ["n tends to positive infinity."],
                "theorems": ["Elementary limit law"],
                "claims": [
                    {
                        "claim_id": "conditions",
                        "statement": (
                            "Since n tends to positive infinity, the "
                            "elementary limit law applies and gives 1/n to 0."
                        ),
                        "depends_on": [],
                        "check_type": "theorem_preconditions",
                        "importance": "critical",
                    }
                ],
                "unresolved_obligations": [],
            }
        )


def test_low_risk_candidate_with_required_obligation_runs_verifier():
    client = LowRiskTheoremClient()
    config = replace(
        _proof_config(),
        max_model_calls=2,
        enable_tools=False,
    )

    result = MathForgeHarness(client, config).solve(
        "Evaluate the limit of 1/n as n tends to infinity.",
        {},
    )

    route = next(
        event for event in result["trace"] if event["event"] == "route_planned"
    )
    gate = next(
        event
        for event in result["trace"]
        if event["event"] == "proof_completion_gate"
    )
    assert route["risk_level"] == "low"
    assert gate["accepted"] == ["primary-1"]
    assert any(
        role.startswith("You are VerifierSkeptic") for role in client.roles
    )
    assert result["run_metrics"]["outcome"] == "primary"


def test_invalid_verifier_output_degrades_but_does_not_erase_candidate():
    result = MathForgeHarness(ProofClient(invalid_verifier=True), _proof_config()).solve(
        "Prove that x equals x", {}
    )
    assert result["trace"][-1]["event"] == "run_completed"
    assert result["run_metrics"]["outcome"] == "primary"
    assert "Complete structured proof" in result["final_response"]
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
                method=_assigned_method(messages),
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
            _proof_candidate(
                "Complete alternative proof.",
                claims,
                method=_assigned_method(messages),
            )
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
        if event["event"] == "resource_plan_updated"
    )
    assert allocation["verifier"] == 1
    assert allocation["repair_reserve"] == 0
    assert "repair" in allocation["unreachable_by_budget"]
    assert allocation["repair_unreachable_reason"]
    assert result["run_metrics"]["model_calls"] == 3


class SyntaxOnlyProofClient:
    def chat(self, *, messages, temperature, max_tokens):
        del temperature, max_tokens
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
                method=_assigned_method(messages),
            )
        )


def test_syntax_only_checks_mark_candidate_incomplete_but_keep_its_answer():
    config = replace(
        _proof_config(),
        max_model_calls=1,
        enable_tools=True,
        enable_verifier=False,
    )
    result = MathForgeHarness(SyntaxOnlyProofClient(), config).solve(
        "Prove that the solution is unique.", {}
    )
    assert "Unsupported assertions" in result["final_response"]
    gate = next(event for event in result["trace"] if event["event"] == "proof_completion_gate")
    assert gate["accepted"] == ["primary-1"]
    assert gate["degraded_accepted"] == ["primary-1"]
    assert {
        item.rsplit(":", 1)[-1]
        for item in gate["decisions"][0]["unresolved_obligation_ids"]
    } == {"definition", "sufficiency", "uniqueness", "boundary"}
    assert result["trace"][-1]["event"] == "run_completed"
    assert result["run_metrics"]["outcome"] == "primary"


def test_empty_finalizer_result_rolls_back_to_deterministic_response():
    class EmptyFinalizer:
        @staticmethod
        def finalize(*args, **kwargs):
            del args, kwargs
            return FinalizationResult("", True, "accepted")

    harness = MathForgeHarness(
        ProofClient(),
        replace(
            _proof_config(),
            max_model_calls=3,
            enable_finalizer=True,
        ),
    )
    harness._finalizer = EmptyFinalizer()

    result = harness.solve("Prove that x equals x", {})

    assert "Complete structured proof" in result["final_response"]
    finalization = next(
        event
        for event in result["trace"]
        if event["event"] == "finalization_completed"
    )
    assert finalization["used_llm"] is False
    assert finalization["reason"] == "finalizer_empty"
    assert result["run_metrics"]["outcome"] == "primary"
