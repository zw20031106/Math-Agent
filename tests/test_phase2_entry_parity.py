from __future__ import annotations

import main as official_main
from user_agent import CASE_MAX_CONCURRENCY


class _StubAgent:
    def solve(self, problem, metadata):
        assert problem == "1+1"
        assert metadata == {"idx": "case-1"}
        return {
            "id": "case-1",
            "status": "failed",
            "final_response": "No verified answer.",
            "trace": [{"event": "run_completed", "outcome": "fallback"}],
        }


def test_frozen_official_entry_preserves_agent_content_but_not_public_status():
    output = official_main.solve_item(
        _StubAgent(),
        {"idx": "case-1", "problem": "1+1"},
    )

    assert output == {
        "idx": "case-1",
        "status": "success",
        "final_response": "No verified answer.",
        "trace": [{"event": "run_completed", "outcome": "fallback"}],
    }
    assert "id" not in output


def test_agent_bounds_the_frozen_outer_dispatch_to_four_active_cases():
    assert official_main.LOCAL_MAX_CONCURRENCY == 8
    assert CASE_MAX_CONCURRENCY == 4
