from __future__ import annotations

import json

from mathforge.harness.trace import TraceBuilder


def test_judge_trace_filters_unknown_events_secrets_and_paths():
    events: list[dict] = []
    trace = TraceBuilder(events)
    trace.add("private_reasoning", candidate_text="do not return")
    trace.add(
        "route_planned",
        primary_subject="algebra",
        api_key="secret",
        note=r"C:\\private\\answer.txt",
    )
    assert len(trace.internal_events) == 2
    assert trace.build() == [
        {
            "event": "route_planned",
            "primary_subject": "algebra",
            "note": "[local-path]",
        }
    ]


def test_judge_trace_size_is_bounded():
    events: list[dict] = []
    trace = TraceBuilder(events, max_chars=200)
    for index in range(100):
        trace.add("retrieval_completed", card_ids=[f"card-{index}-" + "x" * 100])
    assert len(json.dumps(trace.build())) <= 200


def test_cost_tokens_are_not_redacted_as_credentials():
    events: list[dict] = []
    trace = TraceBuilder(events)
    trace.add(
        "budget_summary",
        model_calls=2,
        estimated_tokens=128,
        access_token="secret",
        client_secret="secret",
        private_token="secret",
    )
    assert trace.build() == [
        {
            "event": "budget_summary",
            "model_calls": 2,
            "estimated_tokens": 128,
        }
    ]


def test_terminal_trace_events_survive_event_pressure():
    events: list[dict] = []
    trace = TraceBuilder(events, max_events=3, max_chars=240)
    trace.add("session_started", session_id="s")
    for index in range(10):
        trace.add("retrieval_completed", card_ids=[str(index)])
    trace.add("budget_summary", model_calls=1, estimated_tokens=12)
    trace.add("fallback_used", reason="primary_unavailable")
    assert [event["event"] for event in trace.build()] == [
        "session_started",
        "budget_summary",
        "fallback_used",
    ]
    assert len(json.dumps(trace.build())) <= 240
