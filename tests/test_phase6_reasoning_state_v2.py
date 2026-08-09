from __future__ import annotations

from hashlib import sha256
import json

from mathforge.harness.reasoning_state import (
    PublicClaim,
    PublicToolResult,
    ReasoningState,
    ReasoningStateCompressor,
    RoundDelta,
    Subgoal,
)
from mathforge.parsing.problem_parser import ProblemParser


def _state(*, branch_id: str = "branch-test") -> ReasoningState:
    problem = ProblemParser().parse(
        "For x in R, prove that (x + 1)^2 = x^2 + 2*x + 1."
    )
    return ReasoningState.initialize(
        problem,
        session_id="session-phase6",
        branch_id=branch_id,
        agent_id="PrimarySolver",
    )


def _tool_result(work_item_id: str, claim_id: str, status: str = "pass") -> PublicToolResult:
    return PublicToolResult(
        work_item_id=work_item_id,
        claim_id=claim_id,
        tool_name="symbolic_equivalence",
        status=status,
        strength="hard" if status == "pass" else "medium",
        summary=f"public check {work_item_id}",
        public_payload={"checked": True, "status": status},
        result_digest=sha256(work_item_id.encode("utf-8")).hexdigest(),
        impact="confirm_strategy" if status == "pass" else "switch_strategy",
        reason_code="phase6_test",
    )


def test_claim_versions_supersession_and_branch_identity():
    state = _state(branch_id="branch-alpha")
    first = PublicClaim(
        "c-bad",
        "The expansion omits the cross term.",
        status="proposed",
        branch_id="branch-alpha",
    )
    state, _ = state.apply(
        RoundDelta(1, "explore", "initial", "algebra", claims=(first,))
    )
    replacement = PublicClaim(
        "c-good",
        "The binomial expansion includes the cross term.",
        supersedes=("c-bad",),
        status="supported",
        branch_id="branch-alpha",
    )
    state, summary = state.apply(
        RoundDelta(state.version, "continue", "corrected", "algebra", claims=(replacement,))
    )

    claims = {item.claim_id: item for item in state.claim_ledger.items}
    assert claims["c-bad"].status == "superseded"
    assert claims["c-bad"].version == 2
    assert claims["c-good"].supersedes == ("c-bad",)
    assert claims["c-good"].branch_id == "branch-alpha"
    assert summary["superseded_claim_ids"] == ["c-bad"]
    assert state.state_id != _state(branch_id="branch-beta").state_id


def test_tool_evidence_transitions_claim_lifecycle_and_version():
    state = _state()
    claim = PublicClaim("c1", "The expansion is exact.")
    state, _ = state.apply(
        RoundDelta(1, "explore", "claim", "algebra", claims=(claim,))
    )
    state, summary = state.apply_tool_results((_tool_result("w1", "c1"),))

    updated = state.claim_ledger.items[0]
    assert updated.status == "verified"
    assert updated.version == 2
    assert updated.evidence_refs == ("tool-w1",)
    assert summary["claim_status_transitions"][0]["to"] == "verified"
    assert summary["information_gain"] >= 2

    state, summary = state.apply_tool_results((_tool_result("w2", "c1", "fail"),))
    updated = state.claim_ledger.items[0]
    assert updated.status == "challenged"
    assert updated.version == 3
    assert "tool-w2" in updated.evidence_refs
    assert summary["claim_status_transitions"][0]["from"] == "verified"


def test_information_gain_discounts_semantic_repetition():
    state = _state()
    first = PublicClaim("c1", "The cross term is 2*x.")
    state, first_summary = state.apply(
        RoundDelta(1, "explore", "first", "algebra", claims=(first,))
    )
    repeat = PublicClaim("c2", "  The cross   term is 2*x.  ")
    state, repeat_summary = state.apply(
        RoundDelta(state.version, "continue", "repeat", "algebra", claims=(repeat,))
    )
    assert first_summary["information_gain"] > 0
    assert repeat_summary["semantic_repetition_ids"] == ["c2"]
    assert repeat_summary["information_gain"] == 0


def test_twenty_plus_rounds_semantic_gc_and_active_frontier_compression():
    state = _state()
    for index in range(1, 25):
        claim_id = f"c{index}"
        supersedes = (f"c{index - 1}",) if index > 1 else ()
        claim = PublicClaim(
            claim_id,
            f"Round {index} establishes a distinct algebraic invariant.",
            supersedes=supersedes,
            subgoal_ids=(f"sg{index}",),
        )
        subgoals = [
            Subgoal(f"sg{index}", f"Round {index} obligation", status="open")
        ]
        if index > 1:
            subgoals.insert(
                0,
                Subgoal(
                    f"sg{index - 1}",
                    f"Round {index - 1} obligation",
                    status="closed",
                ),
            )
        delta = RoundDelta(
            state.version,
            "explore" if index == 1 else "continue",
            (f"round {index}: " + "long public progress " * 120),
            "algebra",
            subgoals=tuple(subgoals),
            claims=(claim,),
        )
        state, summary = state.apply(delta)
        assert summary["information_gain"] > 0

    assert state.version == 25
    compact, gc_summary = state.semantic_gc()
    assert gc_summary["compacted_round_count"] == 22
    assert gc_summary["removed_claim_ids"] == [f"c{i}" for i in range(1, 24)]
    assert [item.claim_id for item in compact.claim_ledger.items] == ["c24"]
    assert gc_summary["removed_subgoal_ids"] == [f"sg{i}" for i in range(1, 24)]
    assert [item.subgoal_id for item in compact.subgoal_ledger.items] == ["sg24"]

    compressed = ReasoningStateCompressor().compress(state, max_tokens=8000)
    payload = json.loads(compressed.prompt_json)
    assert compressed.compressed
    assert compressed.state_tokens <= 8000
    assert payload["compression"]["kind"] == "active_frontier"
    assert payload["compression"]["active_claim_ids"] == ["c24"]
    assert {item["claim_id"] for item in payload["claim_ledger"]["items"]} == {"c24"}
    assert compressed.omitted_rounds >= 22
