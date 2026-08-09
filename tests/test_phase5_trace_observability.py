from __future__ import annotations

from copy import deepcopy
import json

import pytest

from mathforge.config import HarnessConfig
from mathforge.harness.trace import (
    TraceBuilder,
    TraceIntegrityError,
    validate_trace_v2,
)
from mathforge.harness.trace_journal import TraceJournalFactory
from mathforge.output.public_result import build_public_result
from mathforge.runtime import MathForgeHarness
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


def test_runtime_trace_exposes_transport_proof_graph_and_case_summary():
    result = MathForgeHarness(FakeClient(), _minimal_config()).solve(
        "Compute 1 + 1.",
        {},
    )
    trace = result["trace"]

    validate_trace_v2(trace, final_response=result["final_response"])
    transport = next(
        event
        for event in trace
        if event["event"] == "model_transport_completed"
    )
    assert transport["calls"] == [
        {
            "call_index": 1,
                "role": "PrimarySolver",
                "stage": "primary",
                "dispatched": True,
                "status": "completed",
            "attempts": 1,
            "failure_code": "",
            "response_validation": "strict_candidate_json",
            "protocol_parse_tier": "strict_json",
            "protocol_recovery_reason": "",
            "protocol_assurance_degradation": "none",
            "elapsed_seconds": transport["calls"][0]["elapsed_seconds"],
            "queue_elapsed_seconds": transport["calls"][0][
                "queue_elapsed_seconds"
            ],
            "execution_elapsed_seconds": transport["calls"][0][
                "execution_elapsed_seconds"
            ],
            "output_chars": transport["calls"][0]["output_chars"],
        }
    ]

    graph = next(
        event["graph"]
        for event in trace
        if event["event"] == "proof_graph_completed"
    )
    node_ids = {node["id"] for node in graph["nodes"]}
    assert graph["selected_candidate_id"] == "primary-1"
    assert "candidate:primary-1" in node_ids
    assert any(node["kind"] == "claim" for node in graph["nodes"])
    assert all(
        edge["from"] in node_ids and edge["to"] in node_ids
        for edge in graph["edges"]
    )

    summary = next(
        event["summary"]
        for event in trace
        if event["event"] == "case_trace_summary"
    )
    assert summary["roles_called"] == [
        {"role": "PrimarySolver", "calls": 1}
    ]
    assert summary["candidates"][0]["complete"] is True
    assert summary["candidates"][0]["final_answer"]
    assert summary["selected_candidate_id"] == "primary-1"
    assert summary["selection_reason"]
    assert summary["decision_path"][-1] == "outcome:primary"
    public = build_public_result("case-1", result)
    public_events = {event["event"] for event in public["trace"]}
    assert not {
        "model_transport_completed",
        "proof_graph_completed",
        "case_trace_summary",
    } & public_events
    assert {
        "evidence_summary",
        "proof_completion_summary",
        "candidate_arbitrated",
        "final_answer_selected",
    } <= public_events


class _LeakyFailureClient(FakeClient):
    def chat(self, *, messages, temperature, max_tokens):
        fake_credential = "sk-" + "abcdefghijklmnopqrstuvwxyz123456"
        raise RuntimeError(
            "Traceback (most recent call last): "
            r"C:\private\provider.py "
            f"api_key={fake_credential}"
        )


def test_provider_failure_is_safe_and_locatable_without_raw_exception():
    result = MathForgeHarness(
        _LeakyFailureClient(),
        _minimal_config(),
    ).solve("Compute 1 + 1.", {})
    serialized = json.dumps(result["trace"], ensure_ascii=False)
    transport = next(
        event
        for event in result["trace"]
        if event["event"] == "model_transport_completed"
    )

    assert result["run_metrics"]["outcome"] == "fallback"
    assert transport["summary"]["failure_codes"] == {
        "unknown_provider_failure": 1
    }
    assert ("sk-" + "abcdefghijklmnopqrstuvwxyz123456") not in serialized
    assert "private\\provider.py" not in serialized
    assert "most recent call" not in serialized.lower()
    assert "RuntimeError" not in serialized


def test_trace_journal_writes_each_sanitized_event_immediately(tmp_path):
    factory = TraceJournalFactory(tmp_path)
    sink = factory("session", {"idx": 7})
    trace = TraceBuilder([], event_sink=sink)
    trace.add(
        "route_planned",
        primary_subject="algebra",
        api_key="removed",
        path=r"C:\private\answer.txt",
    )

    path = tmp_path / factory.attempt_id / "7.trace.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["journal_seq"] == 1
    assert payload["trace_event"]["event"] == "route_planned"
    assert payload["trace_event"]["path"] == "[local-path]"
    assert "removed" not in lines[0]


def test_runtime_uses_one_incremental_journal_per_case(tmp_path):
    factory = TraceJournalFactory(tmp_path)
    result = MathForgeHarness(
        FakeClient(),
        _minimal_config(),
        trace_sink_factory=factory,
    ).solve("Compute 1 + 1.", {"idx": "case-9"})

    path = tmp_path / factory.attempt_id / "case-9.trace.jsonl"
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert records[0]["trace_event"]["event"] == "session_started"
    assert records[-1]["trace_event"]["event"] == "run_completed"
    assert [record["journal_seq"] for record in records] == list(
        range(1, len(records) + 1)
    )
    assert len(records) >= len(result["trace"])


def test_public_and_internal_trace_are_separate_and_resident_memory_is_bounded():
    trace = TraceBuilder(
        [],
        max_chars=0,
        max_events=0,
        internal_max_events=8,
    )
    for index in range(20):
        trace.add(
            "private_reasoning",
            candidate_text=f"hidden-{index}",
            scratchpad="private",
            safe_counter=index,
        )

    assert trace.build() == []
    assert len(trace.internal_events) == 8
    assert all("candidate_text" not in event for event in trace.internal_events)
    assert all("scratchpad" not in event for event in trace.internal_events)
    assert trace.stream_stats == {
        "public_events_resident": 0,
        "internal_events_seen": 20,
        "internal_events_resident": 8,
        "internal_events_dropped": 12,
        "journal_failures": 0,
    }


def test_duplicate_lifecycle_events_are_merged_in_the_resident_trace():
    trace = TraceBuilder([], max_chars=0, max_events=0)
    for _ in range(12):
        trace.add("retrieval_completed", card_ids=["same-card"])

    assert trace.build() == [
        {
            "schema_version": "2.0",
            "seq": 1,
            "elapsed_ms": trace.build()[0]["elapsed_ms"],
            "event": "retrieval_completed",
            "stage": "retrieval",
            "card_ids": ["same-card"],
            "repeat_count": 12,
        }
    ]


def test_zero_configured_trace_limit_still_has_a_resident_event_safety_cap():
    trace = TraceBuilder([], max_chars=0, max_events=0)
    for index in range(4100):
        trace.add("retrieval_completed", card_ids=[str(index)])

    assert len(trace.build()) == 4096


def test_trace_v2_rejects_unsafe_transport_and_dangling_proof_edges():
    result = MathForgeHarness(FakeClient(), _minimal_config()).solve(
        "Compute 2 + 2.",
        {},
    )
    unsafe_transport = deepcopy(result["trace"])
    transport = next(
        event
        for event in unsafe_transport
        if event["event"] == "model_transport_completed"
    )
    transport["calls"][0]["failure_code"] = "raw provider exception"
    with pytest.raises(TraceIntegrityError, match="unsafe"):
        validate_trace_v2(
            unsafe_transport,
            final_response=result["final_response"],
        )

    dangling_graph = deepcopy(result["trace"])
    graph = next(
        event["graph"]
        for event in dangling_graph
        if event["event"] == "proof_graph_completed"
    )
    graph["edges"][0]["to"] = "claim:foreign:missing"
    with pytest.raises(TraceIntegrityError, match="edge reference"):
        validate_trace_v2(
            dangling_graph,
            final_response=result["final_response"],
        )
