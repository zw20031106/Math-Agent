from __future__ import annotations

from types import SimpleNamespace

import pytest

from mathforge.harness.budget import CallBudget
from mathforge.harness.deadline import DeadlineController
from mathforge.harness.errors import BudgetExceeded
from mathforge.harness.model_policy import effective_output_tokens
from mathforge.harness.provider import _looks_truncated
from scripts.run_case_outputs import (
    ConsecutiveProviderFailureCircuitBreaker,
    DEFAULT_MAX_CONSECUTIVE_PROVIDER_FAILURES,
    _provider_failure_reasons,
)


def _record(reason: str, *, outcome: str = "fallback") -> SimpleNamespace:
    return SimpleNamespace(
        run_metrics=SimpleNamespace(
            outcome=outcome,
            model_call_failure_count=1,
        ),
        result={
            "trace": [
                {
                    "event": "candidate_generation_failed",
                    "reason": reason,
                }
            ]
        },
    )


def test_stage_admission_uses_actual_timeout_and_short_late_fallback() -> None:
    now = [0.0]
    deadline = DeadlineController(
        soft_deadline_seconds=600.0,
        exploration_deadline_seconds=770.0,
        hard_deadline_seconds=850.0,
        deterministic_finalize_reserve_seconds=50.0,
        model_call_start_margin_seconds=30.0,
        clock=lambda: now[0],
    )

    now[0] = 379.0
    assert deadline.can_start_stage_call(stage_timeout=420.0)
    now[0] = 380.0
    assert not deadline.can_start_stage_call(stage_timeout=420.0)
    now[0] = 770.0
    assert not deadline.can_start_stage_call(stage_timeout=60.0)
    assert deadline.can_start_stage_call(stage_timeout=20.0)


def test_truncation_classifier_is_conservative_and_three_state() -> None:
    assert _looks_truncated("A", 64, 1) == "complete"
    assert _looks_truncated("1/3", 64, 2) == "complete"
    assert _looks_truncated(r"\frac{9}{25}", 64, 5) == "complete"
    assert _looks_truncated("f(x) = (x+1)", 64, 5) == "complete"
    assert _looks_truncated("```json\n{\"answer\": 2}\n```", 64, 5) == "complete"
    assert _looks_truncated('{"answer": 2', 64, 5) == "truncated"
    assert _looks_truncated("<think>unfinished", 64, 5) == "truncated"
    assert _looks_truncated("x" * 300, 1000, 100) == "suspect"


def test_context_output_cap_includes_prompt_and_safety_margin() -> None:
    assert effective_output_tokens(
        "solver_candidate_standard",
        32768,
        prompt_tokens=700,
        context_window_tokens=2048,
        context_safety_margin_tokens=256,
    ) == 1092


def test_observed_output_mean_controls_token_admission_not_requested_cap() -> None:
    budget = CallBudget(max_calls=4, max_tokens=5)
    allocation = {
        "prompt_tokens": 0,
        "max_output_tokens": 100000,
        "counting_mode": "multilingual_estimate",
    }

    budget.consume(stage="primary")
    first = budget.record_model_call_started("primary", allocation)
    budget.record_model_call_completed(
        first,
        observed_output_tokens=2,
        output_counting_mode="multilingual_estimate",
        output_chars=2,
        elapsed_seconds=0.01,
    )
    budget.record_tokens(2)
    budget.consume(stage="primary")
    second = budget.record_model_call_started("primary", allocation)
    budget.record_model_call_completed(
        second,
        observed_output_tokens=2,
        output_counting_mode="multilingual_estimate",
        output_chars=2,
        elapsed_seconds=0.01,
    )
    budget.record_tokens(2)
    with pytest.raises(BudgetExceeded, match="admission"):
        budget.consume(stage="primary")
    assert budget.requested_output_tokens == 200000
    assert budget.observed_output_tokens_mean() == 2.0


def test_batch_breaker_ignores_deadline_and_schema_failures() -> None:
    assert _provider_failure_reasons(_record("model_response_deadline_exceeded")) == []
    assert _provider_failure_reasons(_record("candidate_schema_invalid")) == []
    assert _provider_failure_reasons(_record("provider_5xx")) == ["provider_5xx"]
    activity = _record("not-a-provider-code")
    activity.result["trace"].append(
        {"event": "model_activity", "failure_code": "network_read_timeout"}
    )
    assert _provider_failure_reasons(activity) == ["network_read_timeout"]
    assert DEFAULT_MAX_CONSECUTIVE_PROVIDER_FAILURES == 6


def test_batch_breaker_has_half_open_recovery() -> None:
    now = [0.0]
    breaker = ConsecutiveProviderFailureCircuitBreaker(
        2,
        cooldown_seconds=10.0,
        clock=lambda: now[0],
    )
    assert not breaker.observe(_record("provider_5xx"))
    assert breaker.observe(_record("network_connect_failure"))
    assert breaker.is_open()
    now[0] = 10.0
    assert not breaker.is_open()
    assert breaker.to_dict()["state"] == "half_open"
    assert not breaker.observe(_record("success", outcome="primary"))
    assert breaker.to_dict()["state"] == "closed"
