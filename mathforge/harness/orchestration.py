from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any, Callable

from mathforge.agents.solver import (
    AlternativeSolver,
    PrimarySolver,
    SolverExecutor,
    SolverRequest,
)
from mathforge.agents.router_planner import method_families_for
from mathforge.agents.registry import PromptContractLoader
from mathforge.context.errors import ContextBudgetExceeded
from mathforge.context.snapshots import RoleContextView
from mathforge.harness.budget import CallBudget
from mathforge.harness.errors import (
    BudgetExceeded,
    ModelResponseError,
    ModelTransportError,
)
from mathforge.harness.allocation import FanoutDecision
from mathforge.harness.schemas import CandidateSolution, ProblemIR, RoutePlan
from mathforge.harness.fingerprints import semantic_fingerprint
from mathforge.verification.methods import candidate_method_signature


@dataclass(frozen=True)
class BranchFailure:
    candidate_id: str
    reason: str
    details: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        payload: dict[str, Any] = {
            "candidate_id": self.candidate_id,
            "reason": self.reason,
        }
        if self.details:
            payload["details"] = list(self.details)
        return payload


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
        fanout_decider: (
            Callable[[CandidateSolution | None, CallBudget], FanoutDecision]
            | None
        ) = None,
        primary_candidate: CandidateSolution | None = None,
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

        ordered: dict[int, CandidateSolution] = {}
        failures: list[BranchFailure] = []

        def record_result(index: int, candidate_id: str, get_result) -> None:
            try:
                candidate = get_result()
            except BudgetExceeded as error:
                reason = (
                    "model_response_deadline_exceeded"
                    if "response exceeded" in str(error)
                    else "deadline_cutoff"
                )
                failures.append(BranchFailure(candidate_id, reason))
                if event_callback is not None:
                    event_callback(
                        "candidate_generation_failed",
                        **candidate_failure_trace_payload(candidate_id, reason),
                    )
            except Exception as error:
                reason = _branch_failure_reason(error)
                details = _branch_failure_details(error)
                failures.append(BranchFailure(candidate_id, reason, details))
                if event_callback is not None:
                    event_callback(
                        "candidate_generation_failed",
                        **candidate_failure_trace_payload(
                            candidate_id,
                            reason,
                            details=details,
                        ),
                    )
            else:
                ordered[index] = candidate
                if event_callback is not None:
                    event_callback(
                        "candidate_generated",
                        **candidate_trace_payload(candidate),
                    )

        primary_index, primary_solver, primary_request = branches[0]
        if event_callback is not None:
            event_callback(
                "candidate_generation_started",
                candidate_id=primary_request.candidate_id,
                role=primary_solver.role,
                planned_method_family=primary_request.method_family,
            )
        if primary_candidate is None:
            record_result(
                primary_index,
                primary_request.candidate_id,
                lambda: self._executor.execute(
                    primary_solver,
                    primary_request,
                    budget,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    optional=False,
                ),
            )
        else:
            if primary_candidate.candidate_id != primary_request.candidate_id:
                raise ValueError(
                    "seeded Primary candidate identity does not match the branch"
                )
            ordered[primary_index] = primary_candidate
            if event_callback is not None:
                event_callback(
                    "candidate_generated",
                    **candidate_trace_payload(primary_candidate),
                )

        decision = (
            fanout_decider(ordered.get(0), budget)
            if fanout_decider is not None
            else None
        )
        alternative_limit = (
            max(0, decision.admitted_candidates - 1)
            if decision is not None
            else len(branches) - 1
        )
        alternative_branches = branches[1 : 1 + alternative_limit]
        if decision is not None and event_callback is not None:
            event_callback("adaptive_fanout_decided", **decision.to_dict())
        if event_callback is not None:
            for _, solver, request in alternative_branches:
                event_callback(
                    "candidate_generation_started",
                    candidate_id=request.candidate_id,
                    role=solver.role,
                    planned_method_family=request.method_family,
                )
        pool = ThreadPoolExecutor(
            max_workers=max(1, len(alternative_branches)),
            thread_name_prefix="mathforge-solver",
        )
        futures = {
            pool.submit(
                self._executor.execute,
                solver,
                request,
                budget,
                temperature=max(temperature, 0.35),
                max_tokens=max_tokens,
                optional=True,
            ): (index, request.candidate_id)
            for index, solver, request in alternative_branches
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
                    record_result(index, candidate_id, future.result)
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
        "parse_tier": candidate.parse_tier,
        "source": candidate.source,
        "contract_deviations": list(candidate.contract_deviations),
        "content": public_candidate_content(candidate),
        "content_digest": semantic_fingerprint(candidate.to_dict()),
    }


def candidate_failure_trace_payload(
    candidate_id: str,
    reason: str,
    *,
    details: tuple[str, ...] = (),
) -> dict:
    payload = {
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
    if details:
        payload["details"] = list(details)
    return payload


def _branch_failure_reason(error: Exception) -> str:
    if isinstance(error, ContextBudgetExceeded):
        return "context_budget_exceeded"
    if isinstance(error, (ModelTransportError, ModelResponseError)):
        return error.code
    if isinstance(error, RuntimeError):
        return "unknown_provider_failure"
    if isinstance(error, (TypeError, ValueError)):
        return "model_response_invalid"
    return "solver_branch_failed"


def _branch_failure_details(error: Exception) -> tuple[str, ...]:
    if isinstance(error, ModelResponseError):
        return error.details
    return ()
