from __future__ import annotations

from mathforge.harness.schemas import CandidateSolution, EvidenceRecord, ProofObligation
from mathforge.verification.arbitration import ArbitrationPolicy


def _candidate(identifier: str, answer: str, role: str = "PrimarySolver") -> CandidateSolution:
    return CandidateSolution(identifier, role, "method", answer, "expression")


def _evidence(identifier: str, status: str, strength: str) -> EvidenceRecord:
    return EvidenceRecord("e", identifier, None, "test", status, strength, "test")


def test_soft_score_can_never_rescue_hard_failed_candidate():
    failed = _candidate("failed", "1")
    sound = _candidate("sound", "2")
    evidence = [_evidence("failed", "fail", "hard")] + [
        _evidence("failed", "pass", "soft") for _ in range(20)
    ]
    result = ArbitrationPolicy().select([failed, sound], evidence, {})
    assert result.selected.candidate_id == "sound"


def test_required_coverage_precedes_same_answer_agreement():
    incomplete_a = _candidate("a", "7", "PrimarySolver")
    incomplete_b = _candidate("b", "7", "AlternativeSolver")
    complete = _candidate("c", "8", "AlternativeSolver")
    obligations = {
        "a": [ProofObligation("a:o", "sufficiency", "", status="unresolved")],
        "b": [ProofObligation("b:o", "sufficiency", "", status="unresolved")],
        "c": [ProofObligation("c:o", "sufficiency", "", status="satisfied")],
    }
    result = ArbitrationPolicy().select([incomplete_a, incomplete_b, complete], [], obligations)
    assert result.selected.candidate_id == "c"


def test_arbiter_failure_is_not_required_for_deterministic_output():
    first = _candidate("first", "x")
    second = _candidate("second", "y")
    result = ArbitrationPolicy().select([first, second], [], {})
    assert result.selected.candidate_id == "first"
    assert not result.used_llm_arbiter


def test_same_method_same_answer_has_zero_independent_agreement():
    first = _candidate("first", "7", "PrimarySolver")
    second = _candidate("second", "7", "AlternativeSolver")
    first.method = second.method = "substitution-elimination"
    result = ArbitrationPolicy().select([first, second], [], {})
    assert [rank.independent_agreement for rank in result.ranks] == [0, 0]


def test_distinct_actual_methods_can_contribute_one_agreement():
    first = _candidate("first", "7", "PrimarySolver")
    second = _candidate("second", "7", "AlternativeSolver")
    first.method = "substitution-elimination"
    second.method = "factorization-invariant"
    result = ArbitrationPolicy().select([first, second], [], {})
    assert [rank.independent_agreement for rank in result.ranks] == [1, 1]
