from __future__ import annotations

import pytest

from mathforge.harness.budget import CallBudget
from mathforge.harness.errors import BudgetExceeded


def test_call_and_token_budgets_are_enforced():
    budget = CallBudget(1, max_tokens=3)
    budget.consume()
    with pytest.raises(BudgetExceeded):
        budget.consume()
    budget.record_tokens(3)
    with pytest.raises(BudgetExceeded):
        budget.record_tokens(1)


def test_deadline_order_and_exploration_cutoff(monkeypatch):
    budget = CallBudget(
        2,
        soft_deadline_seconds=1,
        exploration_deadline_seconds=2,
        hard_deadline_seconds=3,
        deterministic_finalize_reserve_seconds=0.25,
    )
    monkeypatch.setattr(budget.deadline, "elapsed_seconds", lambda: 2.5)
    assert budget.soft_expired()
    assert not budget.can_start_exploration()
    assert not budget.must_finalize()
    monkeypatch.setattr(budget.deadline, "elapsed_seconds", lambda: 2.75)
    assert budget.must_finalize()


def test_session_resource_budgets_are_shared_and_bounded():
    budget = CallBudget(
        2,
        max_claims=3,
        max_tool_calls=2,
        max_isolated_tool_calls=1,
        max_tool_seconds=0.1,
        max_evidence_records=2,
        max_prompt_chars_total=10,
    )
    budget.record_claims(3)
    with pytest.raises(BudgetExceeded, match="claim"):
        budget.record_claims(1)

    budget.record_prompt_chars(10)
    with pytest.raises(BudgetExceeded, match="prompt"):
        budget.record_prompt_chars(1)

    timeout = budget.begin_tool_call(isolated=True, default_timeout=3.0)
    assert 0 < timeout <= 0.1
    budget.finish_tool_call(0.08)
    with pytest.raises(BudgetExceeded, match="isolated"):
        budget.begin_tool_call(isolated=True, default_timeout=3.0)

    budget.record_evidence(2)
    with pytest.raises(BudgetExceeded, match="evidence"):
        budget.record_evidence(1)


def test_resource_plan_reports_capacity_without_enforcing_stage_quotas():
    budget = CallBudget(3)
    plan = budget.resource_governor.activation_plan(
        used_calls=0,
        router_calls=0,
        candidate_count=3,
        verifier_required=True,
        repair_requested=True,
        lemma_requested=True,
        finalizer_requested=False,
    )
    assert plan.primary == 1
    assert plan.alternatives == 1
    assert plan.verifier == 1
    assert plan.repair_reserve == 0
    assert {"repair", "lemma"} <= set(plan.unreachable_by_budget)

    budget.consume(stage="primary")
    budget.consume(stage="alternative", optional=True)
    budget.consume(stage="repair", optional=True)
    assert budget.used_calls == 3


def test_resource_plan_describes_post_verifier_repair_capacity():
    budget = CallBudget(4)
    plan = budget.resource_governor.activation_plan(
        used_calls=0,
        router_calls=0,
        candidate_count=1,
        verifier_required=True,
        repair_requested=True,
        lemma_requested=False,
        finalizer_requested=False,
        reverification_requested=True,
    )
    assert plan.primary == 1
    assert plan.verifier == 2
    assert plan.repair_reserve == 1
    assert plan.unreachable_by_budget == ()

    insufficient = CallBudget(3).resource_governor.activation_plan(
        used_calls=0,
        router_calls=0,
        candidate_count=1,
        verifier_required=True,
        repair_requested=True,
        lemma_requested=False,
        finalizer_requested=False,
        reverification_requested=True,
    )
    assert insufficient.verifier == 1
    assert insufficient.repair_reserve == 0
    assert {"repair", "reverification"} <= set(
        insufficient.unreachable_by_budget
    )


def test_shared_budget_allows_primary_retry_until_global_cap():
    budget = CallBudget(6)
    budget.consume(stage="primary")
    budget.consume(stage="primary", optional=True)
    for _ in range(4):
        budget.consume(stage="primary", optional=True)
    with pytest.raises(BudgetExceeded, match="call budget exhausted"):
        budget.consume(stage="primary", optional=True)
