from __future__ import annotations

from mathforge.harness.schemas import CandidateSolution, Claim, EvidenceRecord, MethodStep, ProofObligation
from mathforge.runtime_flows.final_flow import FinalProofStatusService
from mathforge.verification.capabilities import VerificationCapability
from mathforge.verification.completion import ProofCompletionGate
from mathforge.verification.proof_obligations import ProofObligationEngine
from mathforge.verification.verification_v2 import assess_verification
from mathforge.parsing.problem_parser import ProblemParser


def _candidate(*, claims: list[Claim], answer: str = "QED") -> CandidateSolution:
    return CandidateSolution(
        "c",
        "PrimarySolver",
        "direct-deduction",
        answer,
        "text",
        claims=claims,
        public_solution_steps=["derive the conclusion"],
        method_steps=[
            MethodStep("conclusion-step", "conclusion", ["conclusion"])
        ],
    )


def _hard_obligation_evidence(obligation_id: str, claim_id: str) -> EvidenceRecord:
    return EvidenceRecord(
        "offline-proof",
        "c",
        claim_id,
        "offline:proof_checker",
        "pass",
        "hard",
        "deterministic proof obligation check",
        {"obligation_ids": [obligation_id]},
        {"schema_valid": True, "formal_engine": False},
        VerificationCapability.PROOF_OBLIGATION_REVIEW.value,
    )


def test_unknown_claim_cannot_create_v2_hard_verified():
    candidate = _candidate(
        claims=[
            Claim(
                "conclusion",
                "The asserted result follows.",
                check_type="reasoning",
                importance="critical",
            )
        ]
    )

    decision = ProofCompletionGate().evaluate(candidate, [], [])

    # ``complete_hard`` remains a legacy wire value for old consumers; the
    # V2 assurance field is the authoritative claim.
    assert decision.status == "complete_hard"
    assert decision.assurance_level in {"answer_contract_valid", "not_disproved"}
    assert decision.hard_verified is False
    assert decision.terminal_closure is False


def test_required_obligation_without_real_claim_stays_unmapped():
    problem = ProblemParser().parse("Prove the stated conclusion.")
    candidate = _candidate(
        claims=[
            Claim(
                "conclusion",
                "The conclusion is asserted.",
                check_type="reasoning",
                importance="critical",
            )
        ]
    )
    obligations = ProofObligationEngine().generate(problem, candidate)
    required = next(item for item in obligations if item.kind == "sufficiency")

    assert required.status == "unmapped_required_obligation"
    assert not set(required.source_claim_ids).intersection(
        {claim.claim_id for claim in candidate.claims}
    )

    decision = ProofCompletionGate().evaluate(candidate, [], obligations)
    assert required.obligation_id in decision.unmapped_required_obligation_ids
    assert decision.hard_verified is False
    assert decision.status == "incomplete"


def test_peripheral_hard_pass_cannot_lift_candidate_closure():
    candidate = _candidate(
        claims=[
            Claim(
                "conclusion",
                "The final equality holds.",
                depends_on=["dependency"],
                check_type="reasoning",
                importance="critical",
            ),
            Claim(
                "dependency",
                "The dependency is asserted.",
                check_type="reasoning",
                importance="critical",
            ),
            Claim(
                "peripheral",
                "An unrelated equality is true.",
                check_type="symbolic_equivalence",
            ),
        ]
    )
    evidence = [
        EvidenceRecord(
            "peripheral-pass",
            "c",
            "peripheral",
            "tool:symbolic_equivalence",
            "pass",
            "hard",
            "unrelated check",
            {},
            {"claim_kind": "equality", "schema_valid": True},
            VerificationCapability.EQUALITY_SYMBOLIC_UNDER_DOMAIN.value,
        )
    ]

    closure = assess_verification(candidate, evidence, [])
    assert closure.critical_claim_ids == ("conclusion", "dependency")
    assert closure.assurance_level != "tool_supported"
    assert closure.hard_verified is False
    assert "peripheral-pass" not in closure.supporting_evidence_ids


def test_compatible_hard_obligation_evidence_closes_terminal_path():
    candidate = _candidate(
        claims=[
            Claim(
                "conclusion",
                "The conclusion follows.",
                check_type="sufficiency",
                importance="critical",
            ),
        ]
    )
    obligation = ProofObligation(
        "c:sufficiency",
        "sufficiency",
        "prove the conclusion",
        source_claim_ids=["conclusion"],
    )
    evidence = [_hard_obligation_evidence(obligation.obligation_id, "conclusion")]

    decision = ProofCompletionGate().evaluate(candidate, evidence, [obligation])

    assert decision.status == "complete_hard"
    assert decision.assurance_level == "tool_supported"
    assert decision.terminal_closure is True
    assert decision.hard_verified is True
    assert decision.conclusion_claim_id == "conclusion"


def test_llm_review_and_audit_never_become_formally_verified():
    candidate = _candidate(
        claims=[
            Claim(
                "conclusion",
                "The conclusion follows.",
                check_type="sufficiency",
                importance="critical",
            ),
        ]
    )
    obligation = ProofObligation(
        "c:sufficiency",
        "sufficiency",
        "prove the conclusion",
        source_claim_ids=["conclusion"],
    )
    llm_evidence = EvidenceRecord(
        "llm-review",
        "c",
        "conclusion",
        "llm:VerifierSkeptic",
        "pass",
        "soft",
        "the model found no gap",
        {"obligation_ids": [obligation.obligation_id]},
        {"role": "VerifierSkeptic"},
        VerificationCapability.PROOF_OBLIGATION_REVIEW.value,
    )

    closure = assess_verification(candidate, [llm_evidence], [obligation])
    assert closure.assurance_level != "formally_verified"
    assert closure.hard_verified is False
    final = FinalProofStatusService().finalize(
        candidate,
        ProofCompletionGate().evaluate(candidate, [llm_evidence], [obligation]),
        obligations=[obligation],
    )
    assert final.assurance_level != "formally_verified"

