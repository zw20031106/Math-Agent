from __future__ import annotations

import json

from mathforge.output.judge_trace import minimal_judge_trace
from mathforge.output.public_result import build_public_result
from tests.fake_client import FakeClient
from user_agent import ReasoningAgent


def test_public_trace_starts_with_detailed_selected_solution_process():
    result = ReasoningAgent(FakeClient()).solve("1+1", {"idx": 1})
    process = result["trace"][0]
    selected = next(
        event
        for event in result["trace"]
        if event["event"] == "final_answer_selected"
    )

    assert result["final_response"] == "Final answer: $1+1$"
    assert process["event"] == "solution_process"
    assert process["status"] == "complete"
    assert process["response_mode"] == "answer_only"
    assert process["candidate_id"] == selected["candidate_id"]
    assert process["steps"]
    assert process["conclusion"].startswith("$")
    assert selected["public_solution"]["solution_process_ref"] == "trace[0]"
    assert "public_solution_steps" not in selected["public_solution"]


def test_public_trace_drops_full_effective_config_and_omitted_skill_catalog():
    result = ReasoningAgent(FakeClient()).solve("Compute $2+2$.", {"idx": 2})
    names = [event["event"] for event in result["trace"]]
    skills = next(
        event for event in result["trace"] if event["event"] == "skills_selected"
    )

    assert "effective_config_snapshot" not in names
    assert "omitted_by_role" not in skills
    assert "unknown_by_role" not in skills
    assert all("included_sections" not in item for item in skills["skills"])
    assert len(json.dumps(skills, ensure_ascii=False)) < 2048


def test_fallback_trace_still_has_a_first_safe_solution_status():
    trace = minimal_judge_trace(error_code="network_connect_failure")

    assert trace[0]["event"] == "solution_process"
    assert trace[0]["status"] == "unavailable"
    assert trace[0]["steps"] == []
    assert trace[-1]["event"] == "run_completed"


def test_judge_trace_projection_remains_idempotent():
    result = ReasoningAgent(FakeClient()).solve("Compute $3+3$.", {"idx": 3})
    assert build_public_result(result["id"], result) == result
