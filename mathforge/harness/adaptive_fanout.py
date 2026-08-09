from __future__ import annotations

from mathforge.harness.budget_types import FanoutDecision
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
        posterior_signals = _primary_posterior_signals(primary)

        if requested_alternatives == 0:
            reasons.append("route_single_candidate")
            admitted_alternatives = 0
        elif primary is None:
            reasons.append(
                "reliability_standby"
                if route.risk_level == "low" and requested == 2
                else "primary_unavailable"
            )
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
            and not posterior_signals
        ):
            reasons.extend(
                [
                    "low_risk_primary_complete",
                    "independent_alternative_backbone",
                ]
            )
            admitted_alternatives = min(1, requested_alternatives)
        else:
            if posterior_signals:
                reasons.append("primary_posterior_escalation")
                reasons.extend(
                    f"posterior:{signal}" for signal in posterior_signals
                )
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


def _primary_posterior_signals(
    primary: CandidateSolution | None,
) -> tuple[str, ...]:
    if primary is None:
        return ()
    signals: list[str] = []
    if primary.parse_tier != "strict":
        signals.append("recovered_parse")
    if not primary.final_answer.strip():
        signals.append("missing_answer")
    if not primary.public_solution_steps:
        signals.append("missing_public_steps")
    if primary.unresolved_obligations:
        signals.append("unresolved_obligations")
    if primary.contract_deviations:
        signals.append("contract_deviations")
    if not any(claim.importance == "critical" for claim in primary.claims):
        signals.append("missing_critical_claim")
    return tuple(dict.fromkeys(signals))
