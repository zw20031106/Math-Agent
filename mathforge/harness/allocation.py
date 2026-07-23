from __future__ import annotations

from dataclasses import dataclass


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
    ) -> "CallAllocationPlan":
        router = max(0, router_calls)
        primary = 1
        verifier = int(verifier_required)
        required = router + primary + verifier
        if required > max_calls:
            raise ValueError("required model stages are unreachable by call budget")

        remaining = max_calls - required
        requested = (
            ("alternatives", max(0, candidate_count - 1)),
            ("repair", int(repair_requested)),
            ("lemma", int(lemma_requested)),
            ("finalizer", int(finalizer_requested)),
        )
        allocated: dict[str, int] = {}
        unreachable: list[str] = []
        for stage, count in requested:
            allocated[stage] = min(count, remaining)
            remaining -= allocated[stage]
            if allocated[stage] < count:
                unreachable.append(stage)

        return cls(
            max_calls=max_calls,
            router=router,
            primary=primary,
            alternatives=allocated["alternatives"],
            verifier=verifier,
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
