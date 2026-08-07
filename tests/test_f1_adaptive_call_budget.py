from __future__ import annotations

import pytest
from concurrent.futures import ThreadPoolExecutor

from mathforge.agent_runtime.session_call_budget import SessionCallBudget
from mathforge.harness.allocation import CallAllocationPlan
from mathforge.harness.errors import BudgetExceeded


def _adaptive_budget() -> SessionCallBudget:
    return SessionCallBudget(
        max_calls=48,
        model_call_policy="adaptive_bounded",
        soft_call_checkpoints=(16, 28, 40),
        speculative_exploration_cutoff=40,
        closure_reserve_calls=8,
    )


def test_adaptive_budget_uses_global_checkpoints_without_stage_quotas():
    budget = _adaptive_budget()

    for _ in range(16):
        budget.consume(
            stage="alternative",
            optional=True,
            action_category="speculative_exploration",
        )

    snapshot = budget.snapshot()
    assert snapshot.used_calls == 16
    assert snapshot.budget_phase == "checkpoint_pressure"
    assert snapshot.next_checkpoint == 28
    assert snapshot.stage_remaining["alternative"] == 32

    with pytest.raises(RuntimeError, match="do not accept stage allocations"):
        budget.set_allocation_plan(
            CallAllocationPlan.build(
                max_calls=48,
                router_calls=1,
                candidate_count=2,
                verifier_required=True,
                repair_requested=True,
                lemma_requested=True,
                finalizer_requested=False,
            )
        )


def test_closure_reserve_rejects_speculation_but_allows_eight_closure_calls():
    budget = _adaptive_budget()
    for _ in range(40):
        budget.consume(
            stage="alternative",
            optional=True,
            action_category="speculative_exploration",
        )

    assert budget.budget_phase == "closure_reserve"
    assert budget.can_start_exploration() is False
    with pytest.raises(BudgetExceeded, match="closure reserve"):
        budget.consume(
            stage="alternative",
            optional=True,
            action_category="speculative_exploration",
        )

    for _ in range(8):
        budget.consume(stage="verifier", action_category="verification")

    assert budget.used_calls == 48
    assert budget.budget_phase == "exhausted"
    with pytest.raises(BudgetExceeded, match="exhausted"):
        budget.consume(stage="repair", action_category="repair")


def test_undispatched_refund_restores_the_shared_logical_budget():
    budget = _adaptive_budget()
    budget.consume(stage="router", action_category="replan")
    assert budget.refund(stage="router") is True
    assert budget.used_calls == 0
    assert budget.to_dict()["calls_remaining"] == 48


def test_concurrent_agent_reservations_are_atomic_at_the_48_call_limit():
    budget = _adaptive_budget()

    def consume_once(_: int) -> bool:
        try:
            budget.consume(stage="verifier", action_category="verification")
            return True
        except BudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=16) as pool:
        outcomes = list(pool.map(consume_once, range(64)))

    assert sum(outcomes) == 48
    assert budget.used_calls == 48
