from __future__ import annotations

from copy import deepcopy
import json

import pytest

from mathforge.config import HarnessConfig
from mathforge.harness.schemas import CandidateSolution, Claim
from mathforge.harness.trace import (
    TraceBuilder,
    TraceIntegrityError,
    validate_trace_v2,
)
from mathforge.runtime import MathForgeHarness
from mathforge.tools.registry import ToolResult
from mathforge.verification.evidence import EvidenceLedger
from tests.fake_client import FakeClient


def _minimal_config(**overrides) -> HarnessConfig:
    values = {
        "profile": "test",
        "status": "test",
        "max_model_calls": 1,
        "enable_router": False,
        "enable_skills": False,
        "enable_alternatives": False,
        "enable_tools": False,
        "enable_evidence": False,
        "enable_proof_obligations": False,
        "enable_verifier": False,
        "enable_memory": False,
        "enable_lemma_loop": False,
        "enable_rag": False,
        "enable_repair": False,
        "enable_finalizer": False,
    }
    values.update(overrides)
    return HarnessConfig(**values)


def test_primary_trace_v2_exposes_auditable_candidate_and_selected_solution():
    result = MathForgeHarness(
        FakeClient(),
        _minimal_config(),
    ).solve("1 + 1", {})
    trace = result["trace"]

    validate_trace_v2(trace, final_response=result["final_response"])
    assert [event["seq"] for event in trace] == list(range(1, len(trace) + 1))
    assert [event["elapsed_ms"] for event in trace] == sorted(
        event["elapsed_ms"] for event in trace
    )
    generated = next(
        event for event in trace if event["event"] == "candidate_generated"
    )
    assert generated["content"]["public_solution_steps"]
    assert generated["content"]["final_answer"]
    assert "solution_text" not in generated["content"]
    assert generated["content_digest"]

    evidence = next(
        event
        for event in trace
        if event["event"] == "candidate_evidence_completed"
    )
    assert evidence["candidate_id"] == generated["candidate_id"]
    arbitration = next(
        event for event in trace if event["event"] == "candidate_arbitrated"
    )
    assert arbitration["selected"] in arbitration["viable_candidates"]
    assert arbitration["rank_details"][0]["lexicographic_key"]
    selected = next(
        event for event in trace if event["event"] == "final_answer_selected"
    )
    assert selected["candidate_id"] == arbitration["selected"]
    assert (
        selected["public_solution"]["final_response"]
        == result["final_response"]
    )
    assert trace[-1]["event"] == "run_completed"
    assert json.loads(json.dumps(trace, ensure_ascii=False)) == trace


class _AlternativeFailureClient(FakeClient):
    def chat(self, *, messages, temperature, max_tokens):
        if messages[0]["content"].startswith("You are AlternativeSolver"):
            raise RuntimeError("private branch failure details")
        return super().chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )


def test_each_candidate_start_has_one_safe_terminal_event():
    result = MathForgeHarness(
        _AlternativeFailureClient(),
        _minimal_config(max_model_calls=2, enable_alternatives=True),
    ).solve("solve x + 1 = 2", {})
    trace = result["trace"]
    starts = [
        event["candidate_id"]
        for event in trace
        if event["event"] == "candidate_generation_started"
    ]
    terminals = [
        event
        for event in trace
        if event["event"]
        in {"candidate_generated", "candidate_generation_failed"}
    ]

    assert starts == ["primary-1", "alternative-1"]
    assert all(
        sum(event["candidate_id"] == candidate_id for event in terminals) == 1
        for candidate_id in starts
    )
    failure = next(
        event
        for event in terminals
        if event["event"] == "candidate_generation_failed"
    )
    assert failure["reason"] == "solver_branch_failed"
    assert "private branch failure details" not in json.dumps(trace)


@pytest.mark.parametrize(
    "mutation",
    ["missing_evidence", "foreign_candidate", "wrong_final_response"],
)
def test_trace_integrity_rejects_cross_reference_breakage(mutation):
    result = MathForgeHarness(
        FakeClient(),
        _minimal_config(),
    ).solve("2 + 2", {})
    trace = deepcopy(result["trace"])

    if mutation == "missing_evidence":
        trace[:] = [
            event
            for event in trace
            if event["event"] != "candidate_evidence_completed"
        ]
        for index, event in enumerate(trace, start=1):
            event["seq"] = index
    elif mutation == "foreign_candidate":
        event = next(
            item for item in trace if item["event"] == "candidate_arbitrated"
        )
        event["viable_candidates"].append("foreign-candidate")
    else:
        event = next(
            item for item in trace if item["event"] == "final_answer_selected"
        )
        event["public_solution"]["final_response"] = "different"

    with pytest.raises(TraceIntegrityError):
        validate_trace_v2(trace, final_response=result["final_response"])


def test_unlimited_trace_preserves_public_content_and_recursively_redacts():
    events: list[dict] = []
    trace = TraceBuilder(
        events,
        max_chars=0,
        max_events=0,
        redacted_values=("benchmark-secret",),
    )
    trace.add("session_started", session_id="session")
    long_text = "推导" * 20_000
    trace.add(
        "retrieval_completed",
        text=long_text,
        nested={
            "api_key": "removed",
            "authorization": "Bearer private-credential",
            "path": r"C:\private\answer.txt",
            "token_value": "sk-" + "abcdefghijklmnopqrstuvwxyz123456",
            "nonce_value": "benchmark-secret",
            "trace": "Traceback (most recent call last): private",
            **{f"field_{index}": index for index in range(40)},
        },
        values=list(range(100)),
    )
    for index in range(70):
        trace.add("retrieval_completed", card_ids=[f"card-{index}"])
    trace.add("fallback_used", reason="test")
    trace.add("budget_summary", outcome="fallback")
    trace.add(
        "run_completed",
        outcome="fallback",
        final_phase="fallback_completed",
        error_code="test",
    )
    built = trace.build(final_response="fallback")
    serialized = json.dumps(built, ensure_ascii=False)

    retrieval = next(
        event for event in built if event["event"] == "retrieval_completed"
    )
    assert retrieval["text"] == long_text
    assert retrieval["values"] == list(range(100))
    assert "removed" not in serialized
    assert "private\\answer" not in serialized
    assert "abcdefghijklmnopqrstuvwxyz123456" not in serialized
    assert "private-credential" not in serialized
    assert "benchmark-secret" not in serialized
    assert "most recent call" not in serialized
    assert len(built) > 64


def test_evidence_ledger_rejects_unknown_candidate_and_claim_references():
    candidate = CandidateSolution(
        "candidate-1",
        "PrimarySolver",
        "direct",
        "1",
        "expression",
        claims=[Claim("claim-1", "1 = 1")],
        public_solution_steps=["Establish 1 = 1."],
        solution_text="Establish 1 = 1.",
    )
    ledger = EvidenceLedger(candidates=[candidate])
    result = ToolResult(
        "symbolic_equivalence",
        "pass",
        "hard",
        "verified",
        {},
    )

    with pytest.raises(ValueError, match="unknown candidate"):
        ledger.record_tool_result(
            candidate_id="foreign",
            claim_id=None,
            result=result,
        )
    with pytest.raises(ValueError, match="unknown claim"):
        ledger.record_tool_result(
            candidate_id="candidate-1",
            claim_id="foreign-claim",
            result=result,
        )
