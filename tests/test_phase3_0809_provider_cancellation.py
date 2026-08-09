from __future__ import annotations

from threading import Event, Thread
from time import perf_counter, sleep

import pytest

from mathforge.agent_runtime.definitions import AgentRegistry
from mathforge.agent_runtime.runtime import SessionAgentRuntime
from mathforge.agents.solver import PrimarySolver, SolverExecutor, SolverRequest
from mathforge.agents.router_planner import RouterRuleEngine
from mathforge.harness.budget import CallBudget
from mathforge.harness.cancellation import CancellationToken
from mathforge.harness.errors import ModelCallRejected, ModelTransportError
from mathforge.harness.model_policy import PROVIDER_CALL_TIMEOUT_SECONDS
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.harness.transport import ObservedModelResponse
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import SolutionParser
from scripts.run_case_outputs import PerCaseWallClockRunner


class _RecordingClient:
    def __init__(self, response="ok") -> None:
        self.response = response
        self.calls = 0

    def chat(self, **_kwargs):
        self.calls += 1
        return self.response


def _request() -> SolverRequest:
    problem = ProblemParser().parse("Compute 1+1.")
    route = RouterRuleEngine().plan(problem)
    return SolverRequest(
        "phase3-primary",
        problem,
        route,
        "",
        route.method_families[0],
    )


def test_timeout_records_configured_client_and_effective_bounds() -> None:
    budget = CallBudget(1)
    budget.consume(stage="primary")
    provider = OfficialClientProvider(_RecordingClient(), ModelCallGate(1))

    provider.chat(
        messages=[{"role": "user", "content": "prove"}],
        temperature=0.0,
        max_tokens=65_536,
        budget=budget,
        stage="primary",
        turn_kind="solver_candidate_proof",
    )

    record = budget.model_call_records[0]
    assert record["configured_stage_timeout_seconds"] == 270.0
    assert record["client_timeout_seconds"] == PROVIDER_CALL_TIMEOUT_SECONDS
    assert record["effective_stage_timeout_seconds"] == 165.0
    assert record["effective_stage_timeout_seconds"] <= min(
        record["configured_stage_timeout_seconds"],
        record["client_timeout_seconds"],
    )


def test_protocol_shape_failure_does_not_degrade_transport_health() -> None:
    gate = ModelCallGate(1)
    budget = CallBudget(1)
    budget.consume(stage="primary")

    with pytest.raises(ModelTransportError) as captured:
        OfficialClientProvider(_RecordingClient({"not": "text"}), gate).chat(
            messages=[{"role": "user", "content": "solve"}],
            temperature=0.0,
            max_tokens=16,
            budget=budget,
            stage="primary",
        )

    assert captured.value.code == "response_shape_invalid"
    health = gate.health_snapshot()
    assert health["transport_health"]["state"] == "healthy"
    assert health["transport_health"]["ordinary_failure_count"] == 0
    assert health["protocol_health"]["state"] == "degraded"
    assert budget.to_dict()["protocol_health"]["state"] == "degraded"


def test_cancellation_denies_new_calls_and_discards_inflight_result() -> None:
    entered = Event()
    release = Event()
    token = CancellationToken()
    gate = ModelCallGate(1, max_background_tails=1)

    def blocking_call() -> str:
        entered.set()
        release.wait(1)
        return "late"

    captured: list[BaseException] = []

    def invoke() -> None:
        try:
            gate.call(
                blocking_call,
                deadline=CallBudget(
                    1,
                    model_call_start_margin_seconds=0.0,
                ).deadline,
                stage_timeout_seconds=2.0,
                cancellation_token=token,
            )
        except BaseException as error:
            captured.append(error)

    worker = Thread(target=invoke)
    worker.start()
    assert entered.wait(0.2)
    token.cancel("per_case_wall_clock_exceeded")
    worker.join(0.3)
    assert len(captured) == 1
    assert isinstance(captured[0], ModelCallRejected)
    assert captured[0].code == "case_cancelled"

    with pytest.raises(ModelCallRejected) as denied:
        gate.call(lambda: "must not run", cancellation_token=token)
    assert denied.value.code == "case_cancelled"
    assert gate.health_snapshot()["active_tails"] == 0
    assert gate.health_snapshot()["state"] == "healthy"

    release.set()
    for _ in range(100):
        if gate.health_snapshot()["discarded_cancelled_results"]:
            break
        sleep(0.002)
    assert gate.health_snapshot()["discarded_cancelled_results"] == 1


def test_wall_clock_runner_propagates_cancellation_token() -> None:
    observed = Event()

    def cooperative_solve(
        _problem,
        _metadata,
        *,
        cancellation_token: CancellationToken,
    ):
        assert cancellation_token.wait(1)
        observed.set()
        return {"final_response": "late", "trace": []}

    runner = PerCaseWallClockRunner(
        cooperative_solve,
        wall_clock_seconds=0.08,
        serialization_reserve_seconds=0.03,
        cancellation_token_factory=CancellationToken,
    )
    result = runner.solve("slow", {"idx": "cancel"})

    assert result["run_metrics"]["outcome"] == "timeout"
    assert observed.wait(0.2)


def test_finalize_preserves_unfinished_task_as_deadline_expired() -> None:
    token = CancellationToken()
    runtime = SessionAgentRuntime("a" * 32, AgentRegistry.default())
    runtime.bind_cancellation_token(token)
    runtime.begin_model_turn(
        stage="primary",
        turn_kind="solver_candidate_standard",
        agent_hint="PrimarySolver:unfinished",
    )
    token.cancel("per_case_wall_clock_exceeded")

    snapshot = runtime.finalize([])

    assert snapshot["tasks"][0]["status"] == "deadline_expired"
    primary = next(
        row for row in snapshot["agents"] if row["role"] == "PrimarySolver"
    )
    assert primary["state"]["status"] == "deadline_expired"
    assert all(task["status"] != "completed" for task in snapshot["tasks"])


def test_attempt_reservation_reconciles_only_observed_attempts() -> None:
    gate = ModelCallGate(1, transport_attempt_reservation=3)
    budget = CallBudget(1)
    budget.consume(stage="primary")
    provider = OfficialClientProvider(
        _RecordingClient(ObservedModelResponse("ok", transport_attempts=1)),
        gate,
    )

    provider.chat(
        messages=[{"role": "user", "content": "solve"}],
        temperature=0.0,
        max_tokens=16,
        budget=budget,
        stage="primary",
    )

    record = budget.model_call_records[0]
    assert record["transport_attempt_reservation"] == 3
    assert record["transport_attempts"] == 1
    assert record["transport_attempt_observability"] == "observed"
    assert gate.health_snapshot()["rate_limit"]["reserved_weight"] == 1


def test_read_timeout_is_not_blindly_retried_on_same_branch() -> None:
    class ReadTimeoutClient:
        def __init__(self) -> None:
            self.calls = 0

        def chat(self, **_kwargs):
            self.calls += 1
            raise RuntimeError("ReadTimeout: response timed out")

    client = ReadTimeoutClient()
    started = perf_counter()
    with pytest.raises(ModelTransportError) as captured:
        SolverExecutor(
            OfficialClientProvider(client, ModelCallGate(1)),
            SolutionParser(),
        ).execute(
            PrimarySolver(),
            _request(),
            CallBudget(2),
            temperature=0.0,
            max_tokens=2048,
        )

    assert captured.value.code == "network_read_timeout"
    assert client.calls == 1
    assert perf_counter() - started < 1.0
