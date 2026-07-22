from mathforge.tools.registry import ToolResult
from mathforge.verification.evidence import EvidenceLedger
import json


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


def test_tool_evidence_records_reproducible_invocation_and_stable_digest():
    ledger = EvidenceLedger()
    arguments = {
        "left": "sqrt(x^2)",
        "right": "x",
        "assumptions": ["x >= 0"],
        "domains": {"x": "R"},
    }
    result = ToolResult(
        "symbolic_equivalence",
        "unknown",
        "medium",
        "no counterexample",
        {},
        "2",
    )
    first = ledger.record_tool_result(
        candidate_id="candidate-1",
        claim_id="claim-1",
        result=result,
        arguments=arguments,
        assumptions=["x >= 0"],
        domains={"x": "R"},
        duration_ms=1.25,
        timeout_seconds=3.0,
    )
    second = ledger.record_tool_result(
        candidate_id="candidate-1",
        claim_id="claim-1",
        result=result,
        arguments=arguments,
        assumptions=["x >= 0"],
        domains={"x": "R"},
        duration_ms=9.5,
        timeout_seconds=3.0,
    )
    assert first.invocation["tool_version"] == "2"
    assert first.invocation["arguments"] == arguments
    assert first.invocation["input_digest"] == second.invocation["input_digest"]
    assert first.invocation["duration_ms"] != second.invocation["duration_ms"]
    json.dumps(first.to_dict())
