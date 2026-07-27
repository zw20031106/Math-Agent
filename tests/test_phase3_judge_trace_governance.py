from __future__ import annotations

import json
from time import perf_counter

import pytest

from mathforge.config import HarnessConfig, load_competition_config
from mathforge.harness.events import DEBUG_TRACE_SCHEMA_VERSION
from mathforge.harness.trace_journal import TraceJournalFactory
from mathforge.output.judge_trace import (
    JUDGE_TRACE_SCHEMA_VERSION,
    validate_judge_trace,
)
from mathforge.output.public_result import (
    build_public_result,
    serialized_public_result_bytes,
)
from mathforge.runtime import MathForgeHarness
from tests.fake_client import FakeClient
from user_agent import ReasoningAgent


def _minimal_config(**overrides) -> HarnessConfig:
    values = {
        "profile": "phase3-test",
        "status": "test",
        "max_model_calls": 1,
        "model_max_concurrency": 1,
        "max_background_model_tails": 1,
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


def _candidate(answer: str, marker: str, claim_count: int = 1) -> str:
    claims = [
        {
            "claim_id": f"c{index}",
            "statement": f"Claim {index}: the computed value is {answer}.",
            "depends_on": [f"c{index - 1}"] if index else [],
            "check_type": "reasoning",
            "importance": "critical" if index == claim_count - 1 else "supporting",
        }
        for index in range(claim_count)
    ]
    return json.dumps(
        {
            "method": "direct-deduction",
            "method_steps": [
                {
                    "step_id": f"s{index}",
                    "kind": "conclusion",
                    "claim_ids": [f"c{index}"],
                    "theorem": "",
                }
                for index in range(claim_count)
            ],
            "solution_text": f"{marker}: derive {answer}.",
            "public_solution_steps": [f"{marker}: derive {answer}."],
            "final_answer": answer,
            "assumptions": [],
            "theorems": [],
            "claims": claims,
            "unresolved_obligations": [],
        }
    )


class _ConflictingClient:
    def chat(self, *, messages, temperature, max_tokens):
        del temperature, max_tokens
        system = messages[0]["content"]
        if system.startswith("You are AlternativeSolver"):
            return _candidate("3", "REJECTED_ANSWER_MARKER")
        return _candidate("2", "SELECTED_ANSWER_MARKER")


def test_formal_output_uses_judge_v3_while_local_journal_keeps_debug_events(
    tmp_path,
):
    config = _minimal_config()
    harness = MathForgeHarness(
        FakeClient(),
        config,
        trace_sink_factory=TraceJournalFactory(tmp_path),
    )
    internal = harness.solve("Compute 1+1.", {"idx": "judge-debug"})
    public = build_public_result("judge-debug", internal)

    validate_judge_trace(
        public["trace"],
        final_response=public["final_response"],
        limits=internal["_public_output_limits"],
    )
    selected = next(
        event
        for event in public["trace"]
        if event["event"] == "final_answer_selected"
    )
    assert "final_response" not in selected["public_solution"]
    assert all(
        event["schema_version"] == JUDGE_TRACE_SCHEMA_VERSION
        for event in public["trace"]
    )
    assert not {
        "candidate_generated",
        "candidate_generation_failed",
        "proof_graph_completed",
        "case_trace_summary",
        "model_transport_completed",
    } & {event["event"] for event in public["trace"]}

    records = [
        json.loads(line)
        for line in (tmp_path / "judge-debug.trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert any(
        record["trace_event"]["event"] == "candidate_generated"
        for record in records
    )
    assert all(
        record["trace_event"]["schema_version"] == DEBUG_TRACE_SCHEMA_VERSION
        for record in records
    )


def test_rejected_candidate_answer_and_solution_never_enter_judge_trace():
    config = _minimal_config(
        max_model_calls=3,
        enable_alternatives=True,
        candidate_summary_max_count=4,
    )
    result = ReasoningAgent(_ConflictingClient(), config=config).solve(
        "Prove carefully that a unique integer answer exists.",
        {"idx": "conflict"},
    )
    serialized = json.dumps(result["trace"], ensure_ascii=False)
    selected = next(
        event
        for event in result["trace"]
        if event["event"] == "final_answer_selected"
    )
    summaries = next(
        event
        for event in result["trace"]
        if event["event"] == "candidate_summaries"
    )

    assert result["status"] == "success"
    assert selected["public_solution"]["final_answer"] == "2"
    assert "SELECTED_ANSWER_MARKER" in result["final_response"]
    assert "REJECTED_ANSWER_MARKER" not in serialized
    assert all(
        set(item)
        == {
            "candidate_id",
            "role",
            "method_family",
            "status",
            "content_digest",
            "rejection_category",
            "evidence_summary",
        }
        for item in summaries["candidates"]
    )
    assert all("final_answer" not in item for item in summaries["candidates"])


def test_long_proof_and_sixty_four_claims_have_bounded_structured_judge_output():
    long_marker = "LONG_PROOF_" + "x" * 8000
    config = _minimal_config(
        public_result_max_bytes=300000,
        judge_trace_max_events=16,
        judge_trace_max_chars=24000,
        judge_trace_event_max_chars=6000,
        candidate_summary_max_count=2,
    )
    internal = MathForgeHarness(FakeClient(), config).solve(
        "Compute a value with a long derivation.",
        {},
    )
    candidate_event = next(
        event
        for event in internal["trace"]
        if event["event"] == "candidate_generated"
    )
    candidate_event["content"]["public_solution_steps"] = [long_marker]
    candidate_event["content"]["claims"] = [
        {
            "claim_id": f"c{index}",
            "statement": f"Claim {index}.",
            "depends_on": [f"c{index - 1}"] if index else [],
            "check_type": "reasoning",
            "importance": "critical" if index == 63 else "supporting",
        }
        for index in range(64)
    ]
    result = build_public_result("long-proof", internal)
    trace_json = json.dumps(result["trace"], ensure_ascii=False)

    assert result["status"] == "success"
    assert len(result["trace"]) <= config.judge_trace_max_events
    assert len(trace_json) <= config.judge_trace_max_chars
    assert all(
        len(json.dumps(event, ensure_ascii=False))
        <= config.judge_trace_event_max_chars
        for event in result["trace"]
    )
    assert '"claims"' not in trace_json
    assert serialized_public_result_bytes(result) <= config.public_result_max_bytes
    assert json.loads(json.dumps(result, ensure_ascii=False)) == result


def test_four_thousand_internal_events_are_projected_quickly_and_bounded():
    config = _minimal_config(
        public_result_max_bytes=200000,
        judge_trace_max_events=12,
        judge_trace_max_chars=20000,
        judge_trace_event_max_chars=5000,
    )
    internal = MathForgeHarness(FakeClient(), config).solve("Compute 2+2.", {})
    terminal = internal["trace"].pop()
    elapsed = int(terminal["elapsed_ms"])
    for index in range(4096):
        internal["trace"].append(
            {
                "schema_version": "2.0",
                "seq": 0,
                "elapsed_ms": elapsed,
                "event": "retrieval_completed",
                "stage": "retrieval",
                "card_ids": [f"card-{index}-" + "x" * 128],
            }
        )
    internal["trace"].append(terminal)
    for sequence, event in enumerate(internal["trace"], start=1):
        event["seq"] = sequence

    started = perf_counter()
    public = build_public_result("many-events", internal)
    elapsed_seconds = perf_counter() - started

    assert elapsed_seconds < 2.0
    assert len(public["trace"]) <= config.judge_trace_max_events
    assert serialized_public_result_bytes(public) <= config.public_result_max_bytes
    assert public["trace"][-1]["event"] == "run_completed"


def test_secret_path_traceback_and_private_payload_keys_are_absent():
    fake_secret = "sk-" + "abcdefghijklmnopqrstuvwxyz123456"

    class FailingClient:
        def chat(self, **_):
            raise RuntimeError(
                "Traceback (most recent call last): "
                rf"C:\private\provider.py raw_response={fake_secret}"
            )

    result = ReasoningAgent(
        FailingClient(),
        config=_minimal_config(),
    ).solve("Compute 1+1.", {})
    serialized = json.dumps(result, ensure_ascii=False).lower()

    assert result["status"] == "failed"
    assert result["trace"][-1]["event"] == "run_completed"
    assert fake_secret.lower() not in serialized
    assert "c:\\private" not in serialized
    assert "traceback" not in serialized
    assert "raw_response" not in serialized
    assert "candidate_text" not in serialized


def test_competition_output_limits_are_explicit_and_public_projection_is_idempotent():
    config = load_competition_config()
    assert config.public_result_max_bytes > config.judge_trace_max_chars
    assert config.judge_trace_max_events >= 8
    assert config.judge_trace_event_max_chars < config.judge_trace_max_chars
    assert config.candidate_summary_max_count >= 1

    result = ReasoningAgent(FakeClient()).solve("Compute 3+3.", {"idx": 3})
    assert build_public_result(result["id"], result) == result
    assert serialized_public_result_bytes(result) <= config.public_result_max_bytes


def test_judge_trace_rejects_a_final_response_changed_after_projection():
    result = ReasoningAgent(FakeClient()).solve("Compute 3+3.", {"idx": 3})
    tampered = {**result, "final_response": "A conflicting answer."}

    with pytest.raises(ValueError, match="digest is inconsistent"):
        build_public_result(result["id"], tampered)


def test_invalid_judge_output_limits_fail_configuration_validation():
    with pytest.raises(ValueError, match="public_result_max_bytes"):
        _minimal_config(public_result_max_bytes=100)
    with pytest.raises(ValueError, match="judge_trace_event_max_chars"):
        _minimal_config(
            judge_trace_max_chars=8000,
            judge_trace_event_max_chars=9000,
        )
    with pytest.raises(ValueError, match="judge_trace_max_events"):
        _minimal_config(judge_trace_max_events=4)
