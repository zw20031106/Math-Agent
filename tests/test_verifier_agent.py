import json

from mathforge.agents.verifier import VerifierSkepticAgent
from mathforge.harness.budget import CallBudget
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.harness.schemas import CandidateSolution, Claim, ProofObligation
from mathforge.parsing.problem_parser import ProblemParser


class CaptureVerifierClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = []

    def chat(self, *, messages, temperature, max_tokens):
        self.calls.append(
            {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        )
        return self.response


def test_verifier_batches_candidates_and_never_receives_solution_text():
    response = json.dumps(
        {
            "findings": [
                {
                    "candidate_id": "c1",
                    "claim_id": "claim-1",
                    "obligation_ids": ["c1:sufficiency"],
                    "status": "pass",
                    "description": "mapped",
                }
            ]
        }
    )
    client = CaptureVerifierClient(response)
    provider = OfficialClientProvider(client, ModelCallGate(1))
    candidates = [
        CandidateSolution(
            candidate_id,
            "PrimarySolver",
            "direct",
            "QED",
            "text",
            claims=[Claim("claim-1", "sufficiency", check_type="sufficiency")],
            solution_text=f"PRIVATE-SOLUTION-{candidate_id}",
        )
        for candidate_id in ("c1", "c2")
    ]
    obligations = {
        candidate.candidate_id: [
            ProofObligation(
                f"{candidate.candidate_id}:sufficiency",
                "sufficiency",
                "prove it",
                source_claim_ids=["claim-1"],
            )
        ]
        for candidate in candidates
    }

    result = VerifierSkepticAgent(provider).review(
        ProblemParser().parse("Prove the result"),
        candidates,
        obligations,
        CallBudget(1),
        max_tokens=500,
    )

    assert len(client.calls) == 1
    prompt = client.calls[0]["messages"][-1]["content"]
    assert "PRIVATE-SOLUTION" not in prompt
    assert result.used_llm is True
    assert len(result.findings) == 1
    assert result.findings[0].status == "pass"


def test_verifier_discards_unmapped_pass_and_invalid_ids():
    response = json.dumps(
        {
            "findings": [
                {
                    "candidate_id": "c",
                    "claim_id": "invented",
                    "obligation_ids": ["c:sufficiency"],
                    "status": "pass",
                }
            ]
        }
    )
    client = CaptureVerifierClient(response)
    candidate = CandidateSolution("c", "PrimarySolver", "direct", "QED", "text")
    obligation = ProofObligation("c:sufficiency", "sufficiency", "prove it")
    result = VerifierSkepticAgent(
        OfficialClientProvider(client, ModelCallGate(1))
    ).review(
        ProblemParser().parse("Prove the result"),
        [candidate],
        {"c": [obligation]},
        CallBudget(1),
        max_tokens=500,
    )
    assert result.findings == []
    assert result.reason == "invalid_or_empty_findings"
