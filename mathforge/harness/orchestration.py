from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Callable

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
from mathforge.harness.errors import BudgetExceeded
from mathforge.harness.schemas import CandidateSolution, ProblemIR, RoutePlan
from mathforge.harness.fingerprints import semantic_fingerprint
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
        role_skill_contexts: dict[str, str] | None = None,
        event_callback: Callable[..., None] | None = None,
    ) -> FanoutResult:
        views = context_views or {}
        skill_contexts = role_skill_contexts or {}
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
                    skill_contexts.get("PrimarySolver", skill_context),
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
                        skill_contexts.get("AlternativeSolver", skill_context),
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

        if event_callback is not None:
            for _, solver, request in branches:
                event_callback(
                    "candidate_generation_started",
                    candidate_id=request.candidate_id,
                    role=solver.role,
                    planned_method_family=request.method_family,
                )
        ordered: dict[int, CandidateSolution] = {}
        failures: list[BranchFailure] = []
        pool = ThreadPoolExecutor(max_workers=count, thread_name_prefix="mathforge-solver")
        futures = {
            pool.submit(
                self._executor.execute,
                solver,
                request,
                budget,
                temperature=temperature if index == 0 else max(temperature, 0.35),
                max_tokens=max_tokens,
                optional=index > 0,
            ): (index, request.candidate_id)
            for index, solver, request in branches
        }
        pending = set(futures)
        try:
            while pending:
                timeout = budget.deadline.remaining_for_model_call()
                if timeout <= 0:
                    break
                completed, pending = wait(
                    pending,
                    timeout=timeout,
                    return_when=FIRST_COMPLETED,
                )
                if not completed:
                    break
                for future in completed:
                    index, candidate_id = futures[future]
                    try:
                        candidate = future.result()
                    except BudgetExceeded:
                        reason = "deadline_cutoff"
                        failures.append(BranchFailure(candidate_id, reason))
                        if event_callback is not None:
                            event_callback(
                                "candidate_generation_failed",
                                **candidate_failure_trace_payload(
                                    candidate_id,
                                    reason,
                                ),
                            )
                    except Exception:
                        reason = "solver_branch_failed"
                        failures.append(BranchFailure(candidate_id, reason))
                        if event_callback is not None:
                            event_callback(
                                "candidate_generation_failed",
                                **candidate_failure_trace_payload(
                                    candidate_id,
                                    reason,
                                ),
                            )
                    else:
                        ordered[index] = candidate
                        if event_callback is not None:
                            event_callback(
                                "candidate_generated",
                                **candidate_trace_payload(candidate),
                            )
            for future in pending:
                _, candidate_id = futures[future]
                future.cancel()
                reason = "deadline_cutoff"
                failures.append(BranchFailure(candidate_id, reason))
                if event_callback is not None:
                    event_callback(
                        "candidate_generation_failed",
                        **candidate_failure_trace_payload(
                            candidate_id,
                            reason,
                        ),
                    )
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

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


def public_candidate_content(candidate: CandidateSolution) -> dict:
    return {
        "public_solution_steps": list(candidate.public_solution_steps),
        "final_answer": candidate.final_answer,
        "assumptions": list(candidate.assumptions),
        "theorems": list(candidate.theorems),
        "claims": [claim.to_dict() for claim in candidate.claims],
        "method_steps": [step.to_dict() for step in candidate.method_steps],
        "unresolved_obligations": list(candidate.unresolved_obligations),
    }


def candidate_trace_payload(candidate: CandidateSolution) -> dict:
    return {
        "candidate_id": candidate.candidate_id,
        "status": "generated",
        "role": candidate.role,
        "method": candidate.method,
        "planned_method_family": candidate.planned_method_family,
        "parse_status": candidate.parse_status,
        "contract_deviations": list(candidate.contract_deviations),
        "content": public_candidate_content(candidate),
        "content_digest": semantic_fingerprint(candidate.to_dict()),
    }


def candidate_failure_trace_payload(
    candidate_id: str,
    reason: str,
) -> dict:
    return {
        "candidate_id": candidate_id,
        "status": "failed",
        "method": "unavailable",
        "reason": reason,
        "content": {
            "public_solution_steps": [],
            "final_answer": "",
            "claims": [],
        },
    }
