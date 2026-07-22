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


def test_claim_verifier_propagates_assumptions_and_domains():
    candidate = CandidateSolution(
        "c",
        "PrimarySolver",
        "algebra",
        "x",
        "expression",
        assumptions=["x >= 0"],
        claims=[
            Claim(
                "domain",
                "sqrt(x^2) = x",
                check_type="symbolic_equivalence",
            )
        ],
    )
    ledger = EvidenceLedger()
    records = ClaimEvidenceVerifier(ToolExecutor()).verify(
        candidate,
        ledger,
        domains={"x": "R"},
        assumptions=["y > 0"],
    )
    assert records[0].status == "unknown"
    assert records[0].invocation["assumptions"] == ["y > 0", "x >= 0"]
    assert records[0].invocation["domains"] == {"x": "R"}
    assert candidate.claims[0].status == "unverified"
