from __future__ import annotations

import json
import re

from mathforge.agents.registry import PromptContractLoader
from mathforge.agents.solver import PrimarySolver, SolverRequest
from mathforge.agents.verifier import VerifierSkepticAgent
from mathforge.evaluation.prompt_contract_probe import (
    PROMPT_CONTRACT_PROBE_CASES,
    run_live_prompt_contract_probe,
)
from mathforge.harness.budget import CallBudget
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.harness.schemas import (
    CandidateSolution,
    Claim,
    EvidenceRecord,
    MethodStep,
    ProofObligation,
)
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import SolutionParser
from mathforge.agents.router_planner import RouterRuleEngine


def _complete_payload(method: str) -> dict:
    return {
        "method": method,
        "method_steps": [
            {
                "step_id": "s1",
                "kind": "conclusion",
                "claim_ids": ["c1"],
                "theorem": "",
            }
        ],
        "solution_text": "Establish the stated result from the supplied conditions.",
        "public_solution_steps": [
            "Apply the assigned method and establish the critical claim."
        ],
        "final_answer": "1",
        "assumptions": [],
        "theorems": [],
        "claims": [
            {
                "claim_id": "c1",
                "statement": "The requested result equals 1.",
                "depends_on": [],
                "check_type": "reasoning",
                "importance": "critical",
            }
        ],
        "unresolved_obligations": [],
    }


def test_prompt_contract_versions_and_solver_contract_are_unambiguous():
    loader = PromptContractLoader()
    roles = (
        "router_planner",
        "primary_solver",
        "alternative_solver",
        "lemma_curator",
        "verifier_skeptic",
        "repair",
        "finalizer",
    )
    expected_versions = {
        "router_planner": "5",
        "primary_solver": "12",
        "alternative_solver": "11",
        "lemma_curator": "5",
        "repair": "7",
        "verifier_skeptic": "8",
        "finalizer": "6",
    }
    for role in roles:
        contract = loader.load(role)
        expected_version = expected_versions.get(role, "2")
        assert contract.fields["version"] == expected_version
        assert "when possible" not in contract.body.lower()

    for role in ("primary_solver", "alternative_solver"):
        body = loader.load(role).body
        assert "编译器会为当前回合提供唯一" in body
        assert "由主机负责" in body
        assert "hidden chain-of-thought" not in body
        assert "optional exposition" not in body
        assert "\\boxed" not in body
        assert "solution_text" not in body
        assert "public_solution_steps" not in body

    repair = loader.load("repair").body
    assert "重写无关 Claim" in repair
    assert "编译的补丁模式" in repair
    assert "local-patch output example" not in repair


def test_solver_runtime_prompt_uses_method_as_a_diversity_signal():
    problem = ProblemParser().parse("求 1+1。")
    route = RouterRuleEngine().plan(problem)
    request = SolverRequest(
        "candidate",
        problem,
        route,
        "",
        "direct-deduction",
    )
    messages = PrimarySolver().build_messages(request)
    rendered = "\n".join(message["content"] for message in messages)

    assert "Required core method family: direct-deduction." in rendered
    assert "diversity signal" in rendered
    assert "when possible" not in rendered.lower()
    assert rendered.count("Exact JSON schema example:") == 1
    assert "Candidate response mode is answer_only" in rendered
    assert "final_answer" in rendered
    assert '"check"' in rendered


def test_solution_parser_classifies_json_failure_and_contract_incompleteness():
    parser = SolutionParser()
    truncated = parser.parse(
        '{"method":"direct-deduction","final_answer":"2"',
        candidate_id="truncated",
        role="PrimarySolver",
        answer_type="integer",
    )
    malformed = parser.parse(
        '{"method":direct-deduction}',
        candidate_id="malformed",
        role="PrimarySolver",
        answer_type="integer",
    )
    incomplete = parser.parse(
        '{"final_answer":"2"}',
        candidate_id="incomplete",
        role="PrimarySolver",
        answer_type="integer",
    )
    fenced = parser.parse(
        f"```json\n{json.dumps(_complete_payload('direct-deduction'))}\n```",
        candidate_id="fenced",
        role="PrimarySolver",
        answer_type="integer",
    )

    assert truncated.parse_status == "truncated_recovered_json:incomplete_candidate"
    assert truncated.degraded is True
    assert malformed.parse_status == "malformed_json"
    assert incomplete.parse_status == "incomplete_json"
    assert "solution_text:missing" in incomplete.contract_deviations
    assert fenced.parse_status == "fenced_json"


def test_solution_parser_normalizes_only_approved_unambiguous_aliases():
    payload = _complete_payload("direct-deduction")
    payload["structured_method_steps"] = payload.pop("method_steps")
    payload["public_steps"] = payload.pop("public_solution_steps")
    payload["claims"][0]["id"] = payload["claims"][0].pop("claim_id")
    payload["claims"][0]["dependencies"] = payload["claims"][0].pop("depends_on")
    payload["structured_method_steps"][0]["id"] = payload[
        "structured_method_steps"
    ][0].pop("step_id")
    payload["structured_method_steps"][0]["claims"] = payload[
        "structured_method_steps"
    ][0].pop("claim_ids")

    candidate = SolutionParser().parse(
        json.dumps(payload),
        candidate_id="alias",
        role="PrimarySolver",
        answer_type="integer",
    )

    assert candidate.parse_status == "strict_json"
    assert candidate.claims[0].claim_id == "host-c1"
    assert candidate.method_steps[0].claim_ids == ["host-c1"]
    assert {
        "structured_method_steps:alias_normalized:method_steps",
        "public_steps:alias_normalized:public_solution_steps",
        "claims[0].id:alias_normalized:claim_id",
        "claims[0].dependencies:alias_normalized:depends_on",
        "method_steps[0].id:alias_normalized:step_id",
        "method_steps[0].claims:alias_normalized:claim_ids",
    } <= set(candidate.contract_deviations)

    conflict_payload = _complete_payload("direct-deduction")
    conflict_payload["public_steps"] = ["conflicting alias"]
    conflict = SolutionParser().parse(
        json.dumps(conflict_payload),
        candidate_id="conflict",
        role="PrimarySolver",
        answer_type="integer",
    )
    assert conflict.public_solution_steps != ["conflicting alias"]
    assert (
        "public_steps:alias_conflict:public_solution_steps"
        in conflict.contract_deviations
    )


class _ProbeClient:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, *, messages, temperature, max_tokens):
        del temperature, max_tokens
        self.calls.append(messages)
        match = re.search(
            r"Required core method family: ([a-z-]+)\.",
            messages[-1]["content"],
        )
        assert match is not None
        method = match.group(1)
        system = messages[0]["content"]
        step = {
            "statement": "Establish the requested result from the conditions.",
            "claim_kind": "reasoning",
            "depends_on": [],
        }
        if "Candidate response mode is proof_full" in system:
            payload = {
                "final_answer": "1",
                "method": method,
                "proof_steps": [
                    step,
                    {
                        **step,
                        "statement": "Therefore the stated conclusion follows.",
                        "depends_on": [0],
                    },
                ],
                "open_conditions": [],
            }
        elif "Candidate response mode is worked_solution" in system:
            payload = {
                "final_answer": "1",
                "method": method,
                "steps": [step],
                "uncertainties": [],
            }
        else:
            payload = {
                "final_answer": "1",
                "check": {
                    "statement": step["statement"],
                    "claim_kind": "reasoning",
                },
            }
        return json.dumps(payload, ensure_ascii=False)


def test_fixed_20_case_live_probe_runner_meets_all_contract_thresholds():
    client = _ProbeClient()
    report = run_live_prompt_contract_probe(client, max_tokens=8192)
    metrics = report.metrics.to_dict()

    assert len(PROMPT_CONTRACT_PROBE_CASES) == len(client.calls) == 20
    assert {
        case.category for case in PROMPT_CONTRACT_PROBE_CASES
    } == {
        "scalar",
        "linear_input_scalar",
        "interval_input_numeric",
        "polynomial",
        "set_or_group",
        "proof_or_derivation",
        "cross_domain",
    }
    assert any(
        call[0]["content"].startswith("You are AlternativeSolver")
        for call in client.calls
    )
    assert metrics["strict_json_rate"] == 1.0
    assert metrics["candidate_deviation_rate"] == 0.0
    assert metrics["claims_nonempty_rate"] == 1.0
    assert metrics["public_steps_rate"] == 1.0
    assert metrics["final_answer_rate"] == 1.0
    assert metrics["method_family_match_rate"] == 1.0
    assert metrics["host_owned_deviation_count"] == 0
    assert metrics["private_reasoning_field_count"] == 0
    assert report.acceptance_errors == []


class _VerifierClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def chat(self, *, messages, temperature, max_tokens):
        del temperature, max_tokens
        self.messages = messages
        return json.dumps(
            {
                "findings": [
                    {
                        "candidate_id": "candidate",
                        "claim_id": "c1",
                        "obligation_ids": ["candidate:sufficiency"],
                        "status": "unknown",
                        "public_rationale": "The evidence does not close the claim.",
                        "missing_condition": "A boundary condition is missing.",
                        "counterexample_summary": "The boundary case remains open.",
                    }
                ]
            }
        )


def test_verifier_receives_public_steps_method_steps_and_evidence_not_private_solution():
    client = _VerifierClient()
    candidate = CandidateSolution(
        "candidate",
        "PrimarySolver",
        "direct-deduction",
        "QED",
        "text",
        claims=[Claim("c1", "The conclusion follows.", check_type="sufficiency")],
        public_solution_steps=["PUBLIC-STEP"],
        solution_text="PRIVATE-SOLUTION",
        method_steps=[MethodStep("s1", "conclusion", ["c1"])],
    )
    obligation = ProofObligation(
        "candidate:sufficiency",
        "sufficiency",
        "Establish the conclusion.",
        source_claim_ids=["c1"],
    )
    evidence = EvidenceRecord(
        "evidence-id",
        "candidate",
        "c1",
        "tool:test",
        "unknown",
        "soft",
        "Needs review.",
    )
    result = VerifierSkepticAgent(
        OfficialClientProvider(client, ModelCallGate(1))
    ).review(
        ProblemParser().parse("证明结论。"),
        [candidate],
        {"candidate": [obligation]},
        CallBudget(1),
        max_tokens=1024,
        evidence=[evidence],
    )
    prompt = client.messages[-1]["content"]

    assert "PUBLIC-STEP" in prompt
    assert "method_steps" in prompt
    assert "evidence-id" in prompt
    assert '"response_mode":"proof_full"' in prompt
    assert '"answer_type":"text"' in prompt
    assert "PRIVATE-SOLUTION" not in prompt
    assert result.findings[0].missing_condition == "A boundary condition is missing."
    assert (
        result.findings[0].counterexample_summary
        == "The boundary case remains open."
    )
