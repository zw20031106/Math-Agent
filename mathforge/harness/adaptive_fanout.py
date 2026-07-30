from __future__ import annotations

from mathforge.harness.allocation import FanoutDecision
from mathforge.harness.budget import CallBudget
from mathforge.harness.schemas import CandidateSolution, RoutePlan


class AdaptiveFanoutPolicy:
    """Admit optional alternatives after Primary without consuming required calls."""

    def decide(
        self,
        route: RoutePlan,
        primary: CandidateSolution | None,
        budget: CallBudget,
        *,
        required_stage_reserve: int,
        shadow_consistency: str = "not_available",
    ) -> FanoutDecision:
        snapshot = budget.snapshot()
        requested = max(1, min(3, route.candidate_count))
        requested_alternatives = min(2, requested - 1)
        reasons: list[str] = []

        if requested_alternatives == 0:
            reasons.append("route_single_candidate")
            admitted_alternatives = 0
        elif primary is None:
            reasons.append("primary_unavailable")
            admitted_alternatives = requested_alternatives
        elif shadow_consistency == "conflict":
            reasons.append("shadow_conflict")
            admitted_alternatives = max(1, requested_alternatives)
        elif (
            route.risk_level == "low"
            and primary.parse_tier == "strict"
            and primary.final_answer.strip()
            and primary.public_solution_steps
            and not primary.unresolved_obligations
            and not primary.contract_deviations
        ):
            reasons.append("low_risk_primary_complete")
            admitted_alternatives = 0
        else:
            reasons.append(
                "primary_recovered"
                if primary.parse_tier != "strict"
                else f"risk_{route.risk_level}"
            )
            admitted_alternatives = requested_alternatives

        call_capacity = max(
            0,
            snapshot.remaining_calls - max(0, int(required_stage_reserve)),
        )
        stage_capacity = snapshot.stage_remaining.get(
            "alternative",
            call_capacity,
        )
        admitted_alternatives = min(
            admitted_alternatives,
            call_capacity,
            stage_capacity,
            2,
        )
        if admitted_alternatives < requested_alternatives:
            reasons.append("required_stage_reserve_protected")
        if not snapshot.exploration_open:
            admitted_alternatives = 0
            reasons.append("exploration_closed")

        return FanoutDecision(
            requested_candidates=requested,
            admitted_candidates=1 + admitted_alternatives,
            reason_codes=tuple(dict.fromkeys(reasons)),
            budget=snapshot,
        )
