from mathforge.tools.registry import ToolResult
from mathforge.verification.evidence import EvidenceLedger


def test_claim_level_hard_failure_gate():
    ledger = EvidenceLedger()
    ledger.record_tool_result(
        candidate_id="candidate-1",
        claim_id="claim-2",
        result=ToolResult("symbolic_equivalence", "fail", "hard", "counterexample", {}),
    )
    assert ledger.has_hard_fail("candidate-1")
    assert ledger.has_hard_fail("candidate-1", "claim-2")
    assert not ledger.has_hard_fail("candidate-2")


def test_unknown_is_not_a_failure_or_a_pass():
    ledger = EvidenceLedger()
    record = ledger.record_tool_result(
        candidate_id="candidate-1",
        claim_id=None,
        result=ToolResult("simplify_expression", "unknown", "soft", "timeout", {}),
    )
    assert record.status == "unknown"
    assert not ledger.has_hard_fail("candidate-1")
