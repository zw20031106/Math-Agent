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
