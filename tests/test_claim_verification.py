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
    assert records[0].capability == "equality.symbolic_under_domain"
    assert candidate.claims[0].status == "verified"
    assert candidate.claims[0].verification_state == "semantically_verified"
    assert candidate.claims[1].status == "rejected"
    assert candidate.claims[1].verification_state == "rejected"
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
    assert records[0].status == "pass"
    assert records[0].strength == "hard"
    assert records[0].invocation["assumptions"] == ["y > 0", "x >= 0"]
    assert records[0].invocation["domains"] == {"x": "R"}
    assert candidate.claims[0].status == "verified"
    assert candidate.claims[0].verification_state == "semantically_verified"


def test_nonsemantic_hard_pass_does_not_verify_mathematical_claim():
    candidate = CandidateSolution(
        "c",
        "PrimarySolver",
        "direct",
        "QED",
        "text",
        claims=[
            Claim(
                "fake-proof",
                "uniqueness is handled",
                check_type="latex_syntax_check",
                importance="critical",
            )
        ],
    )
    records = ClaimEvidenceVerifier(ToolExecutor()).verify(candidate, EvidenceLedger())
    assert records[0].status == "pass"
    assert records[0].capability == "syntax.latex_brace_balance"
    assert candidate.claims[0].status == "unverified"
    assert candidate.claims[0].verification_state == "syntax_checked"


def test_unknown_check_suggestion_produces_only_unknown_host_evidence():
    candidate = CandidateSolution(
        "c",
        "PrimarySolver",
        "direct",
        "QED",
        "text",
        claims=[Claim("forged", "done", check_type="proof_everything")],
    )
    records = ClaimEvidenceVerifier(ToolExecutor()).verify(
        candidate,
        EvidenceLedger(),
    )
    assert len(records) == 1
    assert records[0].evidence_type == "host:check_type_resolution"
    assert records[0].status == "unknown"
    assert records[0].capability == "none"
    assert candidate.claims[0].status == "unverified"
    assert candidate.claims[0].verification_state == "unknown"


def test_shape_and_syntax_tools_only_update_their_own_capability_state():
    candidate = CandidateSolution(
        "c",
        "PrimarySolver",
        "matrix",
        "[[1,2],[3,4]]",
        "matrix",
        claims=[
            Claim(
                "matrix",
                "[[1,2],[3,4]]",
                check_type="matrix_shape_check",
            ),
            Claim(
                "answer",
                "the answer has the right shape",
                check_type="answer_type_check",
            ),
            Claim(
                "syntax",
                "x + 1",
                check_type="safe_parse_expression",
            ),
        ],
    )
    records = ClaimEvidenceVerifier(ToolExecutor()).verify(
        candidate,
        EvidenceLedger(),
    )
    by_claim = {record.claim_id: record for record in records}
    assert by_claim["matrix"].capability == "matrix.shape"
    assert candidate.claims[0].verification_state == "semantically_verified"
    assert candidate.claims[0].status == "verified"
    assert by_claim["answer"].capability == "answer.shape"
    assert candidate.claims[1].status == "unverified"
    assert by_claim["syntax"].capability == "syntax.restricted_parse"
    assert candidate.claims[2].verification_state == "syntax_checked"
    assert candidate.claims[2].status == "unverified"


def test_route_selected_tools_gate_claim_checks_and_explain_skips():
    candidate = CandidateSolution(
        "c",
        "PrimarySolver",
        "algebra",
        "1",
        "expression",
        claims=[
            Claim(
                "identity",
                "x = x",
                check_type="symbolic_equivalence",
            )
        ],
    )
    records = ClaimEvidenceVerifier(ToolExecutor()).verify(
        candidate,
        EvidenceLedger(),
        selected_tools=["latex_syntax_check"],
    )
    assert len(records) == 1
    assert records[0].status == "unknown"
    assert records[0].description == "check not selected by route"
    assert candidate.claims[0].status == "unverified"


def test_host_reconstructs_only_controlled_density_and_finite_case_arguments():
    candidate = CandidateSolution(
        "c",
        "PrimarySolver",
        "probability",
        "1",
        "expression",
        claims=[
            Claim(
                "density",
                "density[expression=1; variable=x; lower=0; upper=1]",
                check_type="density_normalization",
            ),
            Claim(
                "cases",
                "cases[variable=n; values=0,1,2; expression=n-n; expected=0]",
                check_type="small_case_enumeration",
            ),
            Claim(
                "unsafe",
                "integrate whatever the model meant",
                check_type="density_normalization",
            ),
        ],
    )
    records = ClaimEvidenceVerifier(ToolExecutor()).verify(
        candidate,
        EvidenceLedger(),
        selected_tools=["density_normalization", "small_case_enumeration"],
    )
    by_claim = {record.claim_id: record for record in records}
    assert by_claim["density"].status == "pass"
    assert by_claim["cases"].status == "pass"
    assert by_claim["unsafe"].status == "unknown"
    assert (
        by_claim["unsafe"].description
        == "safe argument reconstruction unavailable"
    )
