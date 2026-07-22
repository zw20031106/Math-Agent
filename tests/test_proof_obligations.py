from mathforge.harness.schemas import CandidateSolution, Claim
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.verification.proof_obligations import ProofObligationEngine


def test_proof_obligations_cover_bidirectional_unique_statement():
    problem = ProblemParser().parse("证明当且仅当条件成立时存在唯一解")
    candidate = CandidateSolution("c", "PrimarySolver", "direct", "proved", "text")
    kinds = {item.kind for item in ProofObligationEngine().generate(problem, candidate)}
    assert {"definition", "necessity", "sufficiency", "existence", "uniqueness", "boundary"} <= kinds


def test_required_obligation_is_only_satisfied_by_verified_claim():
    problem = ProblemParser().parse("证明结论")
    candidate = CandidateSolution(
        "c",
        "PrimarySolver",
        "direct",
        "proved",
        "text",
        claims=[Claim("claim-1", "sufficiency", check_type="sufficiency", importance="required", status="verified")],
    )
    obligations = ProofObligationEngine().generate(problem, candidate)
    sufficiency = next(item for item in obligations if item.kind == "sufficiency")
    assert sufficiency.status == "satisfied"
    assert any(item.status == "unresolved" for item in obligations)
