from mathforge.harness.schemas import CandidateSolution, Claim
from mathforge.tools.executor import ToolExecutor
from mathforge.verification.evidence import ClaimEvidenceVerifier, EvidenceLedger


def test_claim_tools_bind_evidence_and_update_status():
    candidate = CandidateSolution(
        "c",
        "PrimarySolver",
        "algebra",
        "1",
        "expression",
        claims=[
            Claim("good", "(x+1)^2 = x^2+2*x+1", check_type="symbolic_equivalence"),
            Claim("bad", "x = x+1", check_type="symbolic_equivalence"),
            Claim("narrative", "therefore done", check_type="reasoning"),
        ],
    )
    ledger = EvidenceLedger()
    records = ClaimEvidenceVerifier(ToolExecutor()).verify(candidate, ledger)
    assert [(record.claim_id, record.status) for record in records] == [
        ("good", "pass"),
        ("bad", "fail"),
    ]
    assert candidate.claims[0].status == "verified"
    assert candidate.claims[1].status == "rejected"
    assert candidate.claims[2].status == "unverified"
