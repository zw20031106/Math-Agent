from __future__ import annotations

import json

from mathforge.output.judge_trace import minimal_judge_trace
from mathforge.output.public_result import build_public_result
from tests.fake_client import FakeClient
from user_agent import ReasoningAgent


def test_public_trace_starts_with_detailed_selected_solution_process():
    result = ReasoningAgent(FakeClient()).solve("1+1", {"idx": 1})
    plan = result["trace"][0]
    process = next(item for item in result["trace"] if item["step"] == "reasoning")

    assert result["final_response"] == "1+1"
    assert plan["step"] == "plan"
    assert process["content"]
    assert "Step 1:" in process["content"]
    assert result["trace"][-1]["step"] == "finalize"


def test_public_trace_drops_full_effective_config_and_omitted_skill_catalog():
    result = ReasoningAgent(FakeClient()).solve("Compute $2+2$.", {"idx": 2})
    serialized = json.dumps(result["trace"], ensure_ascii=False)

    assert "effective_config_snapshot" not in serialized
    assert "omitted_by_role" not in serialized
    assert "unknown_by_role" not in serialized
    assert "included_sections" not in serialized
    assert all(set(item) == {"step", "content"} for item in result["trace"])


def test_fallback_trace_still_has_a_first_safe_solution_status():
    trace = minimal_judge_trace(error_code="network_connect_failure")

    assert trace[0]["event"] == "solution_process"
    assert trace[0]["status"] == "unavailable"
    assert trace[0]["steps"] == []
    assert trace[-1]["event"] == "run_completed"


def test_judge_trace_projection_remains_idempotent():
    result = ReasoningAgent(FakeClient()).solve("Compute $3+3$.", {"idx": 3})
    assert build_public_result(result["id"], result) == result
