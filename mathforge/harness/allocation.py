from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CallBudgetSnapshot:
    max_calls: int
    used_calls: int
    remaining_calls: int
    remaining_seconds: float
    exploration_open: bool
    stage_remaining: dict[str, int]

    def to_dict(self) -> dict:
        return {
            "max_calls": self.max_calls,
            "used_calls": self.used_calls,
            "remaining_calls": self.remaining_calls,
            "remaining_seconds": self.remaining_seconds,
            "exploration_open": self.exploration_open,
            "stage_remaining": dict(self.stage_remaining),
        }


@dataclass(frozen=True)
class FanoutDecision:
    requested_candidates: int
    admitted_candidates: int
    reason_codes: tuple[str, ...]
    budget: CallBudgetSnapshot

    def to_dict(self) -> dict:
        return {
            "requested_candidates": self.requested_candidates,
            "admitted_candidates": self.admitted_candidates,
            "reason_codes": list(self.reason_codes),
            "budget": self.budget.to_dict(),
        }


@dataclass(frozen=True)
class CallAllocationPlan:
    max_calls: int
    router: int
    primary: int
    alternatives: int
    verifier: int
    repair_reserve: int
    lemma_reserve: int
    finalizer_reserve: int
    unreachable_by_budget: tuple[str, ...] = ()

    @classmethod
    def build(
        cls,
        *,
        max_calls: int,
        router_calls: int,
        candidate_count: int,
        verifier_required: bool,
        repair_requested: bool,
        lemma_requested: bool,
        finalizer_requested: bool,
        reverification_requested: bool = False,
    ) -> "CallAllocationPlan":
        router = max(0, router_calls)
        primary = 1
        verifier = int(verifier_required)
        required = router + primary + verifier
        if required > max_calls:
            raise ValueError("required model stages are unreachable by call budget")

        remaining = max_calls - required
        alternative_count = min(max(0, candidate_count - 1), remaining)
        remaining -= alternative_count
        allocated: dict[str, int] = {}
        unreachable: list[str] = []
        if alternative_count < max(0, candidate_count - 1):
            unreachable.append("alternatives")
        repair_count = 0
        extra_verifier = 0
        if repair_requested and reverification_requested:
            if remaining >= 2:
                repair_count = 1
                extra_verifier = 1
                remaining -= 2
            else:
                unreachable.extend(["repair", "reverification"])
        else:
            repair_count = min(int(repair_requested), remaining)
            remaining -= repair_count
            if repair_count < int(repair_requested):
                unreachable.append("repair")
            extra_verifier = min(int(reverification_requested), remaining)
            remaining -= extra_verifier
            if extra_verifier < int(reverification_requested):
                unreachable.append("reverification")
        allocated["alternatives"] = alternative_count
        allocated["repair"] = repair_count
        for stage, count in (
            ("lemma", int(lemma_requested)),
            ("finalizer", int(finalizer_requested)),
        ):
            allocated[stage] = min(count, remaining)
            remaining -= allocated[stage]
            if allocated[stage] < count:
                unreachable.append(stage)
        primary += min(1, remaining)

        return cls(
            max_calls=max_calls,
            router=router,
            primary=primary,
            alternatives=allocated["alternatives"],
            verifier=verifier + extra_verifier,
            repair_reserve=allocated["repair"],
            lemma_reserve=allocated["lemma"],
            finalizer_reserve=allocated["finalizer"],
            unreachable_by_budget=tuple(unreachable),
        )

    def limit_for(self, stage: str) -> int:
        limits = {
            "router": self.router,
            "primary": self.primary,
            "alternative": self.alternatives,
            "verifier": self.verifier,
            "repair": self.repair_reserve,
            "lemma": self.lemma_reserve,
            "finalizer": self.finalizer_reserve,
        }
        return limits.get(stage, 0)

    def with_stage_floors(
        self,
        used_by_stage: dict[str, int],
    ) -> "CallAllocationPlan":
        """Return a plan that never retracts already-consumed stage calls.

        A re-plan is allowed to reduce *future* optional work, but it must not
        make a previously legal call illegal.  The global ``max_calls`` quota
        remains the authoritative cap for future consumption; stage limits are
        cumulative limits and may therefore include calls that have already
        been spent.
        """

        floors = {
            str(stage): max(0, int(count))
            for stage, count in (used_by_stage or {}).items()
        }
        return CallAllocationPlan(
            max_calls=self.max_calls,
            router=max(self.router, floors.get("router", 0)),
            primary=max(self.primary, floors.get("primary", 0)),
            alternatives=max(self.alternatives, floors.get("alternative", 0)),
            verifier=max(self.verifier, floors.get("verifier", 0)),
            repair_reserve=max(self.repair_reserve, floors.get("repair", 0)),
            lemma_reserve=max(self.lemma_reserve, floors.get("lemma", 0)),
            finalizer_reserve=max(
                self.finalizer_reserve,
                floors.get("finalizer", 0),
            ),
            unreachable_by_budget=self.unreachable_by_budget,
        )

    def to_dict(self) -> dict:
        return {
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
