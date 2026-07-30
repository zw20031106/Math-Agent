from __future__ import annotations


PROVIDER_RESPONSE_LIMIT_SECONDS = 120.0
PROVIDER_HTTP_GRACE_SECONDS = 30.0
PROVIDER_HTTP_TIMEOUT_SECONDS = (
    PROVIDER_RESPONSE_LIMIT_SECONDS + PROVIDER_HTTP_GRACE_SECONDS
)
PROVIDER_CALL_GRACE_SECONDS = 15.0
PROVIDER_CALL_TIMEOUT_SECONDS = (
    PROVIDER_HTTP_TIMEOUT_SECONDS + PROVIDER_CALL_GRACE_SECONDS
)

_STAGE_OUTPUT_CAPS = {
    "router": 4096,
    "primary": 32768,
    "alternative": 24576,
    "verifier": 8192,
    "repair": 8192,
    "lemma": 16384,
    "finalizer": 4096,
}
_DEFAULT_OUTPUT_CAP = 16384
_STAGE_CALL_TIMEOUTS = {
    "router": 60.0,
    "primary": PROVIDER_CALL_TIMEOUT_SECONDS,
    "alternative": PROVIDER_CALL_TIMEOUT_SECONDS,
    "verifier": PROVIDER_CALL_TIMEOUT_SECONDS,
    "repair": PROVIDER_CALL_TIMEOUT_SECONDS,
    "lemma": PROVIDER_CALL_TIMEOUT_SECONDS,
    "finalizer": 60.0,
}
_STAGE_P95_SECONDS = {
    "router": 45.0,
    "primary": 125.0,
    "alternative": 125.0,
    "verifier": 90.0,
    "repair": 100.0,
    "lemma": 105.0,
    "finalizer": 45.0,
}
_DEFAULT_STAGE_P95_SECONDS = 100.0


def stage_output_cap(stage: str) -> int:
    return _STAGE_OUTPUT_CAPS.get(str(stage), _DEFAULT_OUTPUT_CAP)


def effective_output_tokens(stage: str, configured_max_tokens: int) -> int:
    if type(configured_max_tokens) is not int or configured_max_tokens < 0:
        raise ValueError("configured max output tokens must be nonnegative")
    cap = stage_output_cap(stage)
    return cap if configured_max_tokens == 0 else min(cap, configured_max_tokens)


def stage_call_timeout(stage: str) -> float:
    return _STAGE_CALL_TIMEOUTS.get(str(stage), PROVIDER_CALL_TIMEOUT_SECONDS)


def effective_call_timeout(stage: str, remaining_seconds: float) -> float:
    return max(0.0, min(float(remaining_seconds), stage_call_timeout(stage)))


def stage_p95_seconds(stage: str) -> float:
    """Return the frozen initial healthy-service p95 estimate for a stage."""

    return _STAGE_P95_SECONDS.get(str(stage), _DEFAULT_STAGE_P95_SECONDS)


def feasible_queue_budget(
    stage: str,
    remaining_seconds: float,
    maximum_queue_seconds: float,
) -> float:
    """Reserve stage execution time before admitting queue wait."""

    remaining = max(0.0, float(remaining_seconds))
    maximum = max(0.0, float(maximum_queue_seconds))
    p95 = stage_p95_seconds(stage)
    execution_slack = max(0.0, remaining - p95)
    stage_target = min(maximum, p95 * 0.4)
    return max(0.0, min(execution_slack, stage_target))


def stage_sequence_reserve_seconds(
    stages: tuple[str, ...] | list[str],
    maximum_queue_seconds: float,
) -> float:
    """Estimate the time needed to finish an atomic sequence of model stages."""

    maximum = max(0.0, float(maximum_queue_seconds))
    return sum(
        stage_p95_seconds(stage)
        + min(maximum, stage_p95_seconds(stage) * 0.4)
        for stage in stages
    )


def stage_sequence_feasible(
    stages: tuple[str, ...] | list[str],
    *,
    remaining_seconds: float,
    maximum_queue_seconds: float,
) -> bool:
    return max(0.0, float(remaining_seconds)) >= stage_sequence_reserve_seconds(
        stages,
        maximum_queue_seconds,
    )
