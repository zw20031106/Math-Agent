from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from mathforge.agents.solver import (
    AlternativeSolver,
    PrimarySolver,
    SolverExecutor,
    SolverRequest,
)
from mathforge.agents.router_planner import method_families_for
from mathforge.agents.registry import PromptContractLoader
from mathforge.context.snapshots import RoleContextView
from mathforge.harness.budget import CallBudget
from mathforge.harness.schemas import CandidateSolution, ProblemIR, RoutePlan
from mathforge.verification.methods import candidate_method_signature


@dataclass(frozen=True)
class BranchFailure:
    candidate_id: str
    reason: str

    def to_dict(self) -> dict:
        return {"candidate_id": self.candidate_id, "reason": self.reason}


@dataclass
class FanoutResult:
    candidates: list[CandidateSolution]
    failures: list[BranchFailure]


class CandidateOrchestrator:
    def __init__(
        self,
        executor: SolverExecutor,
        contracts: PromptContractLoader | None = None,
    ) -> None:
        self._executor = executor
        self._contracts = contracts or PromptContractLoader()

    def fanout(
        self,
        problem: ProblemIR,
        route: RoutePlan,
        skill_context: str,
        budget: CallBudget,
        *,
        temperature: float,
        max_tokens: int,
        context_views: dict[str, RoleContextView] | None = None,
    ) -> FanoutResult:
        views = context_views or {}
        count = max(1, min(3, route.candidate_count))
        method_families = list(
            dict.fromkeys(
                route.method_families
                or method_families_for(route.primary_subject, route.problem_type)
            )
        )
        if len(method_families) < count:
            method_families.extend(
                family
                for family in method_families_for("general-math", route.problem_type)
                if family not in method_families
            )
        count = min(count, len(method_families))
        branches: list[tuple[int, PrimarySolver | AlternativeSolver, SolverRequest]] = []
        branches.append(
            (
                0,
                PrimarySolver(self._contracts),
                SolverRequest(
                    "primary-1",
                    problem,
                    route,
                    skill_context,
                    method_families[0],
                    tuple(method_families[1:count]),
                    views.get("PrimarySolver"),
                ),
            )
        )
        for index in range(1, count):
            branches.append(
                (
                    index,
                    AlternativeSolver(self._contracts),
                    SolverRequest(
                        f"alternative-{index}",
                        problem,
                        route,
                        skill_context,
                        method_families[index],
                        tuple(
                            family
                            for family in method_families[:count]
                            if family != method_families[index]
                        ),
                        views.get("AlternativeSolver"),
                    ),
                )
            )

        ordered: dict[int, CandidateSolution] = {}
        failures: list[BranchFailure] = []
        with ThreadPoolExecutor(max_workers=count, thread_name_prefix="mathforge-solver") as pool:
            futures = {
                pool.submit(
                    self._executor.execute,
                    solver,
                    request,
                    budget,
                    temperature=temperature if index == 0 else max(temperature, 0.35),
                    max_tokens=max_tokens,
                ): (index, request.candidate_id)
                for index, solver, request in branches
            }
            for future in as_completed(futures):
                index, candidate_id = futures[future]
                try:
                    ordered[index] = future.result()
                except Exception:
                    failures.append(BranchFailure(candidate_id, "solver_branch_failed"))

        candidates = [ordered[index] for index in sorted(ordered)]
        seen: set[tuple] = set()
        for candidate in candidates:
            signature = candidate_method_signature(candidate)
            if signature in seen:
                candidate.parse_status = f"{candidate.parse_status}:duplicate_method"
                candidate.is_method_duplicate = True
            else:
                seen.add(signature)
        failures.sort(key=lambda item: item.candidate_id)
        return FanoutResult(candidates, failures)
