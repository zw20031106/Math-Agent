from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from mathforge.agents.solver import (
    AlternativeSolver,
    PrimarySolver,
    SolverExecutor,
    SolverRequest,
)
from mathforge.harness.budget import CallBudget
from mathforge.harness.schemas import CandidateSolution, ProblemIR, RoutePlan


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


def candidate_method_signature(candidate: CandidateSolution) -> tuple:
    topology = tuple(
        sorted((claim.check_type, len(claim.depends_on), claim.importance) for claim in candidate.claims)
    )
    return (
        candidate.method.strip().lower(),
        tuple(sorted(theorem.strip().lower() for theorem in candidate.theorems)),
        topology,
    )


class CandidateOrchestrator:
    def __init__(self, executor: SolverExecutor) -> None:
        self._executor = executor

    def fanout(
        self,
        problem: ProblemIR,
        route: RoutePlan,
        skill_context: str,
        budget: CallBudget,
        *,
        temperature: float,
        max_tokens: int,
    ) -> FanoutResult:
        count = max(1, min(3, route.candidate_count))
        primary_label = f"standard-{route.primary_subject}"
        branches: list[tuple[int, PrimarySolver | AlternativeSolver, SolverRequest]] = []
        branches.append(
            (
                0,
                PrimarySolver(),
                SolverRequest("primary-1", problem, route, skill_context, primary_label),
            )
        )
        for index in range(1, count):
            branches.append(
                (
                    index,
                    AlternativeSolver(),
                    SolverRequest(
                        f"alternative-{index}",
                        problem,
                        route,
                        skill_context,
                        primary_label,
                        (primary_label, f"alternative-{index - 1}"),
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
            else:
                seen.add(signature)
        failures.sort(key=lambda item: item.candidate_id)
        return FanoutResult(candidates, failures)
