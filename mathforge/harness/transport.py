from __future__ import annotations

import re
from typing import Any

from mathforge.harness.errors import ModelTransportError


SAFE_TRANSPORT_FAILURE_CODES = frozenset(
    {
        "auth_or_permission_failure",
        "rate_limited",
        "provider_5xx",
        "network_connect_failure",
        "network_read_timeout",
        "response_shape_invalid",
        "empty_response",
        "model_response_deadline_exceeded",
        "model_concurrency_wait_exceeded",
        "unknown_provider_failure",
    }
)
RETRYABLE_TRANSPORT_FAILURE_CODES = frozenset(
    {"rate_limited", "provider_5xx", "network_connect_failure"}
)

_HTTP_5XX = re.compile(r"\b5\d\d\b")
_ATTEMPTS_IN_MESSAGE = re.compile(r"\bafter\s+(\d+)\s+attempts?\b", re.I)


class ObservedModelResponse(str):
    transport_attempts: int
    model_call_index: int | None
    output_budget_exceeded: bool
    finish_reason: str
    truncation_status: str
    protocol_turn_id: str

    def __new__(
        cls,
        value: str,
        *,
        transport_attempts: int = 1,
        model_call_index: int | None = None,
        output_budget_exceeded: bool = False,
        finish_reason: str = "",
        truncation_status: str = "complete",
        protocol_turn_id: str = "",
    ) -> ObservedModelResponse:
        instance = super().__new__(cls, value)
        instance.transport_attempts = max(1, int(transport_attempts))
        instance.model_call_index = model_call_index
        instance.output_budget_exceeded = bool(output_budget_exceeded)
        instance.finish_reason = str(finish_reason)
        normalized_truncation = str(truncation_status).strip().casefold()
        if normalized_truncation not in {"complete", "suspect", "truncated"}:
            raise ValueError("unsupported truncation status")
        instance.truncation_status = normalized_truncation
        instance.protocol_turn_id = str(protocol_turn_id)
        return instance


def classify_transport_failure(error: BaseException) -> str:
    if isinstance(error, ModelTransportError):
        return error.code
    name = type(error).__name__.lower()
    message = str(error).lower()
    combined = f"{name} {message}"
    if any(token in combined for token in ("401", "403", "unauthorized", "forbidden")):
        return "auth_or_permission_failure"
    if any(token in combined for token in ("429", "rate limit", "too many requests")):
        return "rate_limited"
    if _HTTP_5XX.search(combined) or "server error" in combined:
        return "provider_5xx"
    if any(
        token in combined
        for token in (
            "connecttimeout",
            "connectionerror",
            "connection refused",
            "name resolution",
            "dns",
            "proxyerror",
            "sslerror",
            "unexpected_eof_while_reading",
            "remote end closed connection",
            "connection reset",
        )
    ):
        return "network_connect_failure"
    if any(
        token in combined
        for token in ("readtimeout", "timed out", "timeout", "response exceeded")
    ):
        return "network_read_timeout"
    if any(
        token in combined
        for token in (
            "jsondecodeerror",
            "choices",
            "message content",
            "response shape",
        )
    ):
        return "response_shape_invalid"
    return "unknown_provider_failure"


def transport_attempts(value: Any) -> int:
    attempts, _ = transport_attempt_observation(value)
    return attempts


def transport_attempt_observation(value: Any) -> tuple[int, bool]:
    marker = object()
    attempts = getattr(
        value,
        "transport_attempts",
        getattr(value, "attempts", marker),
    )
    observed = attempts is not marker
    if not observed:
        match = _ATTEMPTS_IN_MESSAGE.search(str(value))
        if match:
            attempts = match.group(1)
            observed = True
        else:
            attempts = 1
    try:
        return max(1, int(attempts)), observed
    except (TypeError, ValueError):
        return 1, False
