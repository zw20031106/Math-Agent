from __future__ import annotations

import json

from mathforge.output.public_result import build_public_result
from mathforge.runtime import MathForgeHarness
from tests.test_f3_authoritative_router import (
    RouterAwareClient,
    _router_config,
    _router_payload,
)


def _event_values(trace: list[dict], event_name: str) -> list[dict]:
    return [item for item in trace if item.get("event") == event_name]


def characterize(result: dict, client: RouterAwareClient) -> dict:
    """Extract public, reproducible workflow facts for the E0 snapshot."""

    trace = [item for item in result.get("trace", []) if isinstance(item, dict)]
    budget_events = _event_values(trace, "budget_summary")
    budget = budget_events[-1] if budget_events else {}
    call_records = budget.get("model_call_records", [])
    candidate_events = _event_values(trace, "candidate_generated")
    graph_events = [
        item for item in trace
        if "task_graph" in str(item.get("event", "")).casefold()
    ]
    selected_skills = []
    for event in _event_values(trace, "skills_selected"):
        values = event.get("skills", event.get("selected_skills", []))
        if isinstance(values, list):
            selected_skills.extend(str(value) for value in values)
    progress_rounds = sum(
        1
        for item in trace
        if any(token in str(item.get("event", "")).casefold() for token in ("progress", "round"))
    )
    downstream = {
        "verifier_ran": any(
            "verif" in str(item.get("event", "")).casefold()
            for item in trace
        ),
        "repair_ran": any(
            "repair" in str(item.get("event", "")).casefold()
            for item in trace
        ),
        "audit_ran": any(
            "audit" in str(item.get("event", "")).casefold()
            for item in trace
        ),
    }
    return {
        "router_call_order": list(client.roles),
        "candidate": {
            "requested": budget.get("candidate_requested", budget.get("requested_candidates")),
            "allocated": budget.get("candidate_allocated", budget.get("allocated_candidates")),
            "realized": len(candidate_events),
        },
        "task_graph_nodes": [
            node
            for event in graph_events
            for node in event.get("nodes", [])
            if isinstance(node, dict)
        ],
        "model_call_task_mapping": [
            {
                "logical_call_index": item.get("logical_call_index"),
                "role": item.get("agent_role", item.get("role")),
                "task_id": item.get("task_id", item.get("scheduler_task_id")),
            }
            for item in call_records
            if isinstance(item, dict)
        ],
        "selected_skills": sorted(set(selected_skills)),
        "progress_rounds": progress_rounds,
        "downstream": downstream,
        "public_result": build_public_result("e0-characterization", result),
    }


def test_current_workflow_characterization_is_recorded_without_synthetic_events():
    client = RouterAwareClient([_router_payload()])
    result = MathForgeHarness(client, _router_config()).solve(
        "Compute 2+2.",
        {"idx": "e0-characterization", "benchmark_nonce": "e0-nonce"},
    )
    characterization = characterize(result, client)

    # Router order and model-call/task mapping come from actual calls.  The
    # remaining lists/flags intentionally preserve empty/not-run state instead
    # of inventing a successful downstream stage.
    assert characterization["router_call_order"]
    assert characterization["router_call_order"][0].startswith("You are RouterPlanner")
    assert characterization["model_call_task_mapping"]
    assert all(
        item["logical_call_index"] is not None
        and item["task_id"]
        for item in characterization["model_call_task_mapping"]
    )
    assert characterization["candidate"]["realized"] >= 1
    assert isinstance(characterization["task_graph_nodes"], list)
    assert isinstance(characterization["selected_skills"], list)
    assert isinstance(characterization["progress_rounds"], int)
    assert set(characterization["downstream"]) == {
        "verifier_ran",
        "repair_ran",
        "audit_ran",
    }
    public = characterization["public_result"]
    assert public["final_response"].strip()
    assert isinstance(public["trace"], list)
    json.dumps(characterization, ensure_ascii=False, sort_keys=True)
