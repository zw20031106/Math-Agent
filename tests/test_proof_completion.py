from mathforge.harness.schemas import CandidateSolution, Claim, EvidenceRecord, ProofObligation
from mathforge.verification.completion import ProofCompletionGate
from mathforge.verification.capabilities import VerificationCapability


def _obligation(candidate_id: str = "c") -> ProofObligation:
    return ProofObligation(
        f"{candidate_id}:sufficiency",
        "sufficiency",
        "prove the conclusion",
        source_claim_ids=["claim-1"],
    )


def test_claimless_candidate_is_incomplete():
    candidate = CandidateSolution("c", "PrimarySolver", "direct", "QED", "text")
    obligation = ProofObligation("c:sufficiency", "sufficiency", "prove it")
    decision = ProofCompletionGate().evaluate(candidate, [], [obligation])
    assert decision.status == "incomplete"
    assert decision.unresolved_obligation_ids == ["c:sufficiency"]


def test_mapped_skeptic_pass_completes_obligation_but_remains_soft():
    candidate = CandidateSolution(
        "c",
        "PrimarySolver",
        "direct",
        "QED",
        "text",
        claims=[
            Claim(
                "claim-1",
                "x = x + 1",
                check_type="symbolic_equivalence",
                claim_kind="equality",
            )
        ],
    )
    evidence = [
        EvidenceRecord(
            "ev",
            "c",
            "claim-1",
            "llm:VerifierSkeptic",
            "pass",
            "soft",
            "claim supports obligation",
            {"obligation_ids": ["c:sufficiency"]},
            {"role": "VerifierSkeptic"},
            VerificationCapability.PROOF_OBLIGATION_REVIEW.value,
        )
    ]
    obligation = _obligation()
    decision = ProofCompletionGate().evaluate(candidate, evidence, [obligation])
    assert decision.status == "complete"
    assert obligation.status == "satisfied"
    assert obligation.satisfaction_evidence_ids == ["ev"]
    assert evidence[0].strength == "soft"
    assert evidence[0].capability == "proof.obligation_review"
    assert evidence[0].invocation["role"] == "VerifierSkeptic"


def test_hard_failure_cannot_be_overridden_by_skeptic_pass():
    candidate = CandidateSolution(
        "c",
        "PrimarySolver",
        "direct",
        "QED",
        "text",
        claims=[Claim("claim-1", "sufficiency", check_type="sufficiency")],
    )
    evidence = [
        EvidenceRecord(
            "hard",
            "c",
            "claim-1",
            "tool:test",
            "fail",
            "hard",
            "false",
            invocation={
                "claim_kind": "equality",
                "schema_valid": True,
                "fatal_eligible": True,
            },
            capability=VerificationCapability.EQUALITY_SYMBOLIC_UNDER_DOMAIN.value,
        ),
        EvidenceRecord(
            "soft",
            "c",
            "claim-1",
            "llm:VerifierSkeptic",
            "pass",
            "soft",
            "looks valid",
            {"obligation_ids": ["c:sufficiency"]},
            {"role": "VerifierSkeptic"},
            VerificationCapability.PROOF_OBLIGATION_REVIEW.value,
        ),
    ]
    decision = ProofCompletionGate().evaluate(candidate, evidence, [_obligation()])
    assert decision.status == "failed"
    assert decision.failed_claim_ids == ["claim-1"]


def test_unmapped_satisfied_status_cannot_complete_claimless_candidate():
    candidate = CandidateSolution("c", "PrimarySolver", "direct", "QED", "text")
    obligation = ProofObligation(
        "c:sufficiency", "sufficiency", "prove it", status="satisfied"
    )
    decision = ProofCompletionGate().evaluate(candidate, [], [obligation])
    assert decision.status == "incomplete"
    assert obligation.status == "unresolved"
