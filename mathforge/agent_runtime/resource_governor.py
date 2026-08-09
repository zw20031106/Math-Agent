from __future__ import annotations

from dataclasses import dataclass

from mathforge.harness.errors import BudgetExceeded
from mathforge.harness.cancellation import CancellationToken


_CLOSURE_ACTIONS = frozenset(
    {
        "candidate_completion",
        "peer_review_response",
        "verification",
        "repair",
        "replan",
        "final_audit",
        "finalization",
    }
)


@dataclass(frozen=True)
class AdaptiveResourcePlan:
    max_calls: int
    router: int
    primary: int
    alternatives: int
    verifier: int
    repair_reserve: int
    lemma_reserve: int
    finalizer_reserve: int
    unreachable_by_budget: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "policy": "adaptive_bounded",
            "stage_quotas_enforced": False,
            "max_calls": self.max_calls,
            "router": self.router,
            "primary": self.primary,
            "alternatives": self.alternatives,
            "verifier": self.verifier,
            "repair_reserve": self.repair_reserve,
            "lemma_reserve": self.lemma_reserve,
            "finalizer_reserve": self.finalizer_reserve,
            "unreachable_by_budget": list(self.unreachable_by_budget),
        }


class ResourceGovernor:
    """Enforce one shared hard cap and reserve its final calls for closure."""

    def __init__(
        self,
        *,
        hard_limit: int,
        soft_checkpoints: tuple[int, ...],
        speculative_exploration_cutoff: int,
        closure_reserve_calls: int,
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        if hard_limit < 1:
            raise ValueError("hard call limit must be positive")
        if speculative_exploration_cutoff != hard_limit - closure_reserve_calls:
            raise ValueError("exploration cutoff must preserve the closure reserve")
        if tuple(sorted(set(soft_checkpoints))) != soft_checkpoints:
            raise ValueError("soft call checkpoints must be strictly increasing")
        if any(not 0 < item <= speculative_exploration_cutoff for item in soft_checkpoints):
            raise ValueError("soft call checkpoints must lie in exploration capacity")
        self.hard_limit = int(hard_limit)
        self.soft_checkpoints = soft_checkpoints
        self.speculative_exploration_cutoff = int(speculative_exploration_cutoff)
        self.closure_reserve_calls = int(closure_reserve_calls)
        self._cancellation_token = cancellation_token

    def admit(self, *, used_calls: int, action_category: str) -> None:
        if (
            self._cancellation_token is not None
            and self._cancellation_token.is_cancelled
        ):
            raise BudgetExceeded("case cancellation requested")
        if used_calls >= self.hard_limit:
            raise BudgetExceeded("model call budget exhausted")
        if (
            used_calls >= self.speculative_exploration_cutoff
            and action_category not in _CLOSURE_ACTIONS
        ):
            raise BudgetExceeded("closure reserve rejects speculative model work")

    def phase(self, used_calls: int) -> str:
        if used_calls >= self.hard_limit:
            return "exhausted"
        if used_calls >= self.speculative_exploration_cutoff:
            return "closure_reserve"
        if any(used_calls >= checkpoint for checkpoint in self.soft_checkpoints):
            return "checkpoint_pressure"
        return "exploration"

    def next_checkpoint(self, used_calls: int) -> int | None:
        return next(
            (item for item in self.soft_checkpoints if item > used_calls),
            self.speculative_exploration_cutoff
            if used_calls < self.speculative_exploration_cutoff
            else None,
        )

    def activation_plan(
        self,
        *,
        used_calls: int,
        router_calls: int,
        candidate_count: int,
        verifier_required: bool,
        repair_requested: bool,
        lemma_requested: bool,
        finalizer_requested: bool,
        reverification_requested: bool = False,
        primary_calls: int = 1,
    ) -> AdaptiveResourcePlan:
        remaining = max(0, self.hard_limit - used_calls)
        requested_alternatives = max(0, int(candidate_count) - 1)
        consumed_after_router = max(0, int(used_calls) - max(0, int(router_calls)))
        primary_remaining = max(0, int(primary_calls) - consumed_after_router)
        consumed_alternatives = max(
            0,
            consumed_after_router - int(primary_calls),
        )
        requested_alternatives = max(
            0,
            requested_alternatives - consumed_alternatives,
        )
        mandatory = primary_remaining + int(verifier_required)
        unreachable: list[str] = []
        alternatives = min(requested_alternatives, max(0, remaining - mandatory))
        if alternatives < requested_alternatives:
            unreachable.append("alternatives")
        available = max(0, remaining - mandatory - alternatives)

        repair = 0
        extra_verifier = 0
        if repair_requested and reverification_requested:
            if available >= 2:
                repair = 1
                extra_verifier = 1
                available -= 2
            else:
                unreachable.extend(("repair", "reverification"))
        else:
            repair = int(repair_requested and available >= 1)
            available -= repair
            if repair_requested and not repair:
                unreachable.append("repair")
            extra_verifier = int(reverification_requested and available >= 1)
            available -= extra_verifier
            if reverification_requested and not extra_verifier:
                unreachable.append("reverification")
        lemma = int(lemma_requested and available >= 1)
        available -= lemma
        if lemma_requested and not lemma:
            unreachable.append("lemma")
        finalizer = int(finalizer_requested and available >= 1)
        if finalizer_requested and not finalizer:
            unreachable.append("finalizer")

        return AdaptiveResourcePlan(
            max_calls=self.hard_limit,
            router=max(0, int(router_calls)),
            primary=primary_remaining,
            alternatives=alternatives,
            verifier=int(verifier_required) + extra_verifier,
            repair_reserve=repair,
            lemma_reserve=lemma,
            finalizer_reserve=finalizer,
            unreachable_by_budget=tuple(unreachable),
        )

    @staticmethod
    def default_action_category(stage: str, *, optional: bool) -> str:
        normalized = str(stage)
        if normalized == "router":
            return "replan"
        if normalized in {"primary", "solver_candidate_standard", "solver_candidate_proof"}:
            return "candidate_completion"
        if normalized == "alternative":
            return "speculative_exploration" if optional else "candidate_completion"
        if normalized == "verifier":
            return "verification"
        if normalized == "repair":
            return "repair"
        if normalized == "finalizer":
            return "finalization"
        return "speculative_exploration"
