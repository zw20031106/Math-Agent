from __future__ import annotations

import json

from mathforge.config import load_competition_config
from mathforge.harness.budget import CallBudget
from mathforge.harness.provider import ModelCallGate
from mathforge.agents.registry import PromptContractLoader
from mathforge.skills.registry import SkillRegistry
from mathforge.output.judge_trace import project_judge_trace
from mathforge.output.official_trace import project_official_trace


def _diagnostic_input() -> list[dict]:
    return [
        {
            "schema_version": "2.0",
            "seq": 1,
            "elapsed_ms": 0,
            "event": "session_started",
            "stage": "session",
            "session_id": "phase0-case",
        },
        {
            "schema_version": "2.0",
            "seq": 2,
            "elapsed_ms": 12,
            "event": "truncation_assessed",
            "stage": "reasoning",
            "status": "COMPLETE",
        },
        {
            "schema_version": "2.0",
            "seq": 3,
            "elapsed_ms": 20,
            "event": "truncation_assessed",
            "stage": "reasoning",
            "status": "PROBABLE_TRUNCATION",
        },
        {
            "schema_version": "2.0",
            "seq": 4,
            "elapsed_ms": 30,
            "event": "budget_summary",
            "stage": "finalization",
            "model_calls": 4,
            "prompt_tokens": 800,
            "elapsed_seconds": 3.5,
            "deadline_phase": "normal",
            "provider_health_state": "healthy",
            "answer_source": "L1",
            "answer_source_counts": {"L1": 1, "L5": 0},
        },
        {
            "schema_version": "2.0",
            "seq": 5,
            "elapsed_ms": 40,
            "event": "fallback_used",
            "stage": "fallback",
            "reason": "all_candidates_failed",
            "error_code": "all_candidates_failed",
        },
        {
            "schema_version": "2.0",
            "seq": 6,
            "elapsed_ms": 50,
            "event": "run_completed",
            "stage": "completion",
            "outcome": "fallback",
            "error_code": "all_candidates_failed",
            "final_phase": "fallback_completed",
        },
    ]


def test_phase0_diagnostics_step_has_fixed_fields_and_counts() -> None:
    judge_trace = project_judge_trace(_diagnostic_input(), final_response="A")
    diagnostics = next(item for item in judge_trace if item["event"] == "diagnostics")
    assert diagnostics["truncation_verdicts"] == {
        "complete": 1,
        "suspect": 1,
        "truncated": 0,
    }
    assert diagnostics["model_calls"] == 4
    assert diagnostics["prompt_tokens_avg"] == 200.0
    assert diagnostics["circuit_open"] is False
    assert diagnostics["salvage_used"] is False
    assert set(diagnostics) >= {
        "truncation_verdicts",
        "deadline_phase",
        "elapsed_seconds",
        "model_calls",
        "prompt_tokens_avg",
        "circuit_open",
        "salvage_used",
        "sanitizer_issues",
        "error_code",
    }

    official_trace = project_official_trace(judge_trace, final_response="A")
    official_diagnostics = next(
        item for item in official_trace if item["step"] == "diagnostics"
    )
    assert json.loads(official_diagnostics["content"])["model_calls"] == 4


def test_phase0_answer_source_is_recorded_once_and_tail_budget_is_independent() -> None:
    budget = CallBudget(max_calls=1)
    budget.record_answer_source("L1")
    budget.record_answer_source("L5")
    snapshot = budget.to_dict()
    assert snapshot["answer_source"] == "L5"
    assert snapshot["answer_source_counts"] == {"L1": 0, "L5": 1}

    # Two background tails are allowed while six foreground calls remain
    # available; the budgets are intentionally independent.
    ModelCallGate(6, max_background_tails=2)


def test_phase0_competition_configuration_enables_diagnostics() -> None:
    config = load_competition_config()
    assert config.trace_max_chars == 4000
    assert config.max_background_model_tails == 2


def test_model_facing_prompt_and_skill_contracts_are_chinese() -> None:
    prompt = PromptContractLoader().system_prompt("primary_solver")
    skill = SkillRegistry().compose_for_role(
        ["calculus"],
        max_chars=4000,
        role="PrimarySolver",
    ).text
    assert "语言要求" in prompt
    assert "所有解释、步骤和结论必须使用中文" in prompt
    assert "语言要求" in skill
    assert "## 触发条件" in skill


def test_phase0_local_twenty_case_gate_exposes_diagnostics_and_answer_paths() -> None:
    """Run the Phase 0 local smoke gate without a network model dependency."""

    source_counts = {"L1": 0, "L5": 0}
    for index in range(20):
        events = _diagnostic_input()
        source = "L1" if index % 2 == 0 else "L5"
        events[3]["answer_source"] = source
        events[3]["answer_source_counts"] = {
            "L1": int(source == "L1"),
            "L5": int(source == "L5"),
        }
        events[5]["error_code"] = "" if source == "L1" else "all_candidates_failed"
        projected = project_judge_trace(
            events,
            final_response=f"答案{index}",
        )
        diagnostics = next(
            item for item in projected if item["event"] == "diagnostics"
        )
        assert set(diagnostics) >= {
            "truncation_verdicts",
            "deadline_phase",
            "elapsed_seconds",
            "model_calls",
            "prompt_tokens_avg",
            "circuit_open",
            "salvage_used",
            "sanitizer_issues",
            "error_code",
        }
        assert diagnostics["truncation_verdicts"]["suspect"] == 1
        source_counts[source] += events[3]["answer_source_counts"][source]

    assert source_counts == {"L1": 10, "L5": 10}
    assert sum(source_counts.values()) == 20
