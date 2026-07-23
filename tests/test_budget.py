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
