from __future__ import annotations

import json
from time import perf_counter
from typing import Any

from mathforge.agent_runtime.protocol import AgentTurnPayloadParser
from mathforge.agent_runtime.action_registry import ActionRegistry
from mathforge.agents.router_planner import RouterPlanner
from mathforge.agents.solver import PrimarySolver, SolverExecutor, SolverRequest
from mathforge.agents.verifier import VerifierSkepticAgent
from mathforge.harness.budget import CallBudget
from mathforge.harness.context_budget import (
    InternS2TokenCounter,
    OfficialTokenizerUnavailable,
)
from mathforge.harness.errors import ModelResponseError, ModelTransportError
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.harness.schemas import ProofObligation
from mathforge.harness.transport import classify_transport_failure, transport_attempts
from mathforge.model_identity import EXACT_INTERN_MODEL
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import SolutionParser


PRODUCTION_PREFLIGHT_SCHEMA_VERSION = "2.0"
PREFLIGHT_L1_MAX_TOKENS = 4096
PREFLIGHT_STAGE_MAX_TOKENS = 2048
PREFLIGHT_ROUTER_MAX_ATTEMPTS = 3
PREFLIGHT_VERIFIER_MAX_ATTEMPTS = 3
_ACTION_REGISTRY = ActionRegistry()

_AGENT_TURN_REQUEST = (
    "Return exactly one JSON object with these eight fields and no Host-owned IDs: "
    'protocol_version="1.0", task_result_type="PreflightArtifact", '
    'action="complete", public_state_delta={}, result_payload={"status":"ok"}, '
    "outbound_intents=[], progress_summary=\"preflight ok\", "
    'stop_reason="preflight complete".'
)


def run_production_preflight(
    client: Any,
    *,
    requested_model: str = EXACT_INTERN_MODEL,
    include_optional_verification: bool = True,
    require_official_tokenizer: bool = False,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": PRODUCTION_PREFLIGHT_SCHEMA_VERSION,
        "status": "running",
        "failed_level": "",
        "levels": [],
    }
    l0_error = ""
    if requested_model != EXACT_INTERN_MODEL:
        l0_error = "model_identity_invalid"
    elif not callable(getattr(client, "chat", None)):
        l0_error = "model_client_unavailable"
    if l0_error:
        _append_level(report, "L0", "failed", l0_error, 0.0, 0, 0)
        return _fail(report, "L0")
    if require_official_tokenizer:
        try:
            InternS2TokenCounter().require_official_tokenizer()
        except OfficialTokenizerUnavailable:
            _append_level(
                report,
                "L0",
                "failed",
                "official_tokenizer_unavailable",
                0.0,
                0,
                0,
            )
            return _fail(report, "L0")
    _append_level(report, "L0", "passed", "", 0.0, 0, 0)

    l1_started = perf_counter()
    try:
        l1_response = client.chat(
            messages=[
                {
                    "role": "system",
                    "content": "Return only the exact JSON object requested by the user.",
                },
                {"role": "user", "content": 'Return exactly {"status":"ok"}.'},
            ],
            temperature=0.0,
            max_tokens=PREFLIGHT_L1_MAX_TOKENS,
        )
        if not isinstance(l1_response, str) or not l1_response.strip():
            raise ModelTransportError("empty_response")
        if json.loads(l1_response) != {"status": "ok"}:
            raise ModelResponseError("response_shape_invalid")
    except Exception as error:
        return _record_failure(
            report,
            "L1",
            error,
            l1_started,
            PREFLIGHT_L1_MAX_TOKENS,
        )
    _record_pass(
        report,
        "L1",
        l1_started,
        PREFLIGHT_L1_MAX_TOKENS,
        transport_attempts(l1_response),
    )

    l2_started = perf_counter()
    try:
        l2_response = client.chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a protocol preflight. Return JSON only and never "
                        "invent Host-owned identifiers."
                    ),
                },
                {"role": "user", "content": _AGENT_TURN_REQUEST},
            ],
            temperature=0.0,
            max_tokens=PREFLIGHT_STAGE_MAX_TOKENS,
        )
        if not isinstance(l2_response, str) or not l2_response.strip():
            raise ModelTransportError("empty_response")
        parsed_turn = AgentTurnPayloadParser().parse(
            l2_response,
            allowed_actions=_ACTION_REGISTRY.prompt_actions(
                "LLMFinalizer",
                phase="finalize",
            ),
        )
        if (
            parsed_turn.payload.action != "complete"
            or parsed_turn.payload.result_payload != {"status": "ok"}
        ):
            raise ModelResponseError("agent_turn_semantics_invalid")
    except Exception as error:
        return _record_failure(
            report,
            "L2",
            error,
            l2_started,
            PREFLIGHT_STAGE_MAX_TOKENS,
            fallback_code="agent_turn_invalid",
        )
    _record_pass(
        report,
        "L2",
        l2_started,
        PREFLIGHT_STAGE_MAX_TOKENS,
        transport_attempts(l2_response),
        parse_tier=parsed_turn.parse_tier,
    )

    problem = ProblemParser().parse("Compute 1+1.")
    l3_started = perf_counter()
    router_attempts = 0
    router_outcome = None
    router_failure_reasons: list[str] = []
    try:
        for _ in range(PREFLIGHT_ROUTER_MAX_ATTEMPTS):
            router_attempts += 1
            router_outcome = RouterPlanner().plan_authoritative(
                problem,
                llm_chat=lambda **kwargs: client.chat(**kwargs),
                consume_call=lambda: None,
                max_tokens=PREFLIGHT_STAGE_MAX_TOKENS,
            )
            if router_outcome.source == "llm_router":
                break
            router_failure_reasons.append(
                router_outcome.fallback_reason or "router_rule_fallback"
            )
        if router_outcome is None or router_outcome.source != "llm_router":
            raise ModelResponseError(
                "router_preflight_fallback",
                details=tuple(router_failure_reasons),
            )
        router_outcome.authoritative_plan.validate()
    except Exception as error:
        return _record_failure(
            report,
            "L3",
            error,
            l3_started,
            PREFLIGHT_STAGE_MAX_TOKENS,
            fallback_code="router_protocol_invalid",
        )
    _record_pass(
        report,
        "L3",
        l3_started,
        PREFLIGHT_STAGE_MAX_TOKENS,
        router_attempts,
        router_source=router_outcome.source,
    )

    l4_started = perf_counter()
    l4_budget = CallBudget(2)
    try:
        route = router_outcome.route_plan
        candidate = SolverExecutor(
            OfficialClientProvider(client, ModelCallGate(1)),
            SolutionParser(),
        ).execute(
            PrimarySolver(),
            SolverRequest(
                candidate_id="preflight-l4",
                problem=problem,
                route=route,
                skill_context="",
                method_family=route.method_families[0],
            ),
            l4_budget,
            temperature=0.0,
            max_tokens=PREFLIGHT_STAGE_MAX_TOKENS,
        )
        if candidate.final_answer.strip() != "2" or not candidate.claims:
            raise ModelResponseError("candidate_schema_invalid")
    except Exception as error:
        return _record_failure(
            report,
            "L4",
            error,
            l4_started,
            PREFLIGHT_STAGE_MAX_TOKENS,
            attempts=l4_budget.transport_attempts,
            fallback_code="candidate_schema_invalid",
        )
    _record_pass(
        report,
        "L4",
        l4_started,
        PREFLIGHT_STAGE_MAX_TOKENS,
        l4_budget.transport_attempts,
        candidate_id=candidate.candidate_id,
    )

    if not include_optional_verification:
        _append_level(
            report,
            "L5",
            "skipped",
            "optional_verification_disabled",
            0.0,
            0,
            0,
        )
        report["status"] = "passed"
        return report

    l5_started = perf_counter()
    l5_budget = CallBudget(PREFLIGHT_VERIFIER_MAX_ATTEMPTS)
    claim_id = candidate.claims[0].claim_id
    obligation = ProofObligation(
        "preflight-l4:sufficiency",
        "sufficiency",
        "Check that the final claim supports the requested answer.",
        source_claim_ids=[claim_id],
    )
    verification = None
    verification_reasons: list[str] = []
    try:
        for _ in range(PREFLIGHT_VERIFIER_MAX_ATTEMPTS):
            verification = VerifierSkepticAgent(
                OfficialClientProvider(client, ModelCallGate(1))
            ).review(
                problem,
                [candidate],
                {candidate.candidate_id: [obligation]},
                l5_budget,
                max_tokens=PREFLIGHT_STAGE_MAX_TOKENS,
            )
            if verification.used_llm and verification.findings:
                break
            verification_reasons.append(verification.reason)
        if verification is None or not verification.used_llm or not verification.findings:
            raise ModelResponseError(
                "verification_preflight_invalid",
                details=tuple(verification_reasons),
            )
    except Exception as error:
        return _record_failure(
            report,
            "L5",
            error,
            l5_started,
            PREFLIGHT_STAGE_MAX_TOKENS,
            attempts=l5_budget.transport_attempts,
            fallback_code="verification_preflight_invalid",
        )
    _record_pass(
        report,
        "L5",
        l5_started,
        PREFLIGHT_STAGE_MAX_TOKENS,
        l5_budget.transport_attempts,
        finding_count=len(verification.findings),
    )
    report["status"] = "passed"
    return report


def _append_level(
    report: dict[str, Any],
    level: str,
    status: str,
    error_code: str,
    elapsed_seconds: float,
    max_tokens: int,
    attempts: int,
    **details: Any,
) -> None:
    report["levels"].append(
        {
            "level": level,
            "status": status,
            "error_code": error_code,
            "elapsed_seconds": round(max(0.0, elapsed_seconds), 6),
            "max_tokens": max(0, int(max_tokens)),
            "transport_attempts": max(0, int(attempts)),
            **details,
        }
    )


def _record_pass(
    report: dict[str, Any],
    level: str,
    started: float,
    max_tokens: int,
    attempts: int,
    **details: Any,
) -> None:
    _append_level(
        report,
        level,
        "passed",
        "",
        perf_counter() - started,
        max_tokens,
        max(1, int(attempts)),
        **details,
    )


def _record_failure(
    report: dict[str, Any],
    level: str,
    error: Exception,
    started: float,
    max_tokens: int,
    *,
    attempts: int | None = None,
    fallback_code: str = "",
) -> dict[str, Any]:
    code = str(getattr(error, "code", "")).strip()
    if not code:
        classified = classify_transport_failure(error)
        code = fallback_code if classified == "unknown_provider_failure" else classified
    _append_level(
        report,
        level,
        "failed",
        code,
        perf_counter() - started,
        max_tokens,
        attempts if attempts is not None else 1,
    )
    return _fail(report, level)


def _fail(report: dict[str, Any], level: str) -> dict[str, Any]:
    report["status"] = "failed"
    report["failed_level"] = level
    return report
