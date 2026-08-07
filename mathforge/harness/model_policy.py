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

_DEFAULT_STAGE_EXECUTION_POLICY = {
    "router": {"max_tokens": 4096, "timeout_seconds": 120.0, "minimum_start_window_seconds": 60.0},
    "replan": {"max_tokens": 4096, "timeout_seconds": 120.0, "minimum_start_window_seconds": 60.0},
    "solver_progress": {"max_tokens": 4096, "timeout_seconds": 180.0, "minimum_start_window_seconds": 90.0},
    "solver_candidate_standard": {
        "max_tokens": 8192,
        "timeout_seconds": 240.0,
        "minimum_start_window_seconds": 120.0,
    },
    "solver_candidate_proof": {
        "max_tokens": 12288,
        "timeout_seconds": 270.0,
        "minimum_start_window_seconds": 180.0,
    },
    "lemma_curator": {"max_tokens": 8192, "timeout_seconds": 225.0, "minimum_start_window_seconds": 120.0},
    "peer_review": {"max_tokens": 6144, "timeout_seconds": 180.0, "minimum_start_window_seconds": 90.0},
    "verifier": {"max_tokens": 6144, "timeout_seconds": 180.0, "minimum_start_window_seconds": 90.0},
    "repair": {"max_tokens": 8192, "timeout_seconds": 225.0, "minimum_start_window_seconds": 120.0},
    "finalizer": {"max_tokens": 4096, "timeout_seconds": 120.0, "minimum_start_window_seconds": 60.0},
}
_TURN_KIND_ALIASES = {
    "primary": "solver_candidate_standard",
    "alternative": "solver_candidate_standard",
    "lemma": "lemma_curator",
}
_DEFAULT_TURN_KIND = "solver_candidate_standard"
_STAGE_P95_SECONDS = {
    "router": 100.0,
    "replan": 100.0,
    "solver_progress": 150.0,
    "solver_candidate_standard": 210.0,
    "solver_candidate_proof": 240.0,
    "lemma_curator": 180.0,
    "peer_review": 150.0,
    "verifier": 150.0,
    "repair": 180.0,
    "finalizer": 90.0,
}
_DEFAULT_STAGE_P95_SECONDS = 180.0


def normalize_turn_kind(stage: str) -> str:
    normalized = str(stage)
    if normalized in _DEFAULT_STAGE_EXECUTION_POLICY:
        return normalized
    return _TURN_KIND_ALIASES.get(normalized, _DEFAULT_TURN_KIND)


def _execution_spec(
    stage: str,
    policy: dict[str, dict[str, int | float]] | None = None,
) -> dict[str, int | float]:
    active = policy or _DEFAULT_STAGE_EXECUTION_POLICY
    turn_kind = normalize_turn_kind(stage)
    return active.get(turn_kind, active[_DEFAULT_TURN_KIND])


def stage_output_cap(
    stage: str,
    policy: dict[str, dict[str, int | float]] | None = None,
) -> int:
    return int(_execution_spec(stage, policy)["max_tokens"])


def effective_output_tokens(
    stage: str,
    configured_max_tokens: int,
    policy: dict[str, dict[str, int | float]] | None = None,
) -> int:
    if type(configured_max_tokens) is not int or configured_max_tokens < 0:
        raise ValueError("configured max output tokens must be nonnegative")
    cap = stage_output_cap(stage, policy)
    return cap if configured_max_tokens == 0 else min(cap, configured_max_tokens)


def stage_call_timeout(
    stage: str,
    policy: dict[str, dict[str, int | float]] | None = None,
) -> float:
    return float(_execution_spec(stage, policy)["timeout_seconds"])


def stage_minimum_start_window(
    stage: str,
    policy: dict[str, dict[str, int | float]] | None = None,
) -> float:
    return float(
        _execution_spec(stage, policy)["minimum_start_window_seconds"]
    )


def effective_call_timeout(
    stage: str,
    remaining_seconds: float,
    policy: dict[str, dict[str, int | float]] | None = None,
) -> float:
    return max(
        0.0,
        min(float(remaining_seconds), stage_call_timeout(stage, policy)),
    )


def stage_p95_seconds(stage: str) -> float:
    """Return the frozen initial healthy-service p95 estimate for a stage."""

    return _STAGE_P95_SECONDS.get(
        normalize_turn_kind(stage),
        _DEFAULT_STAGE_P95_SECONDS,
    )


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
