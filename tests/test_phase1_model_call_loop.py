from __future__ import annotations

import json

import pytest

from mathforge.agents.solver import PrimarySolver, SolverExecutor, SolverRequest
from mathforge.harness.budget import CallBudget
from mathforge.harness.errors import ModelResponseError, ModelTransportError
from mathforge.harness.model_policy import (
    effective_call_timeout,
    effective_output_tokens,
    stage_call_timeout,
    stage_output_cap,
)
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.harness.schemas import RoutePlan
from mathforge.harness.transport import (
    ObservedModelResponse,
    classify_transport_failure,
)
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import SolutionParser
from mathforge.parsing.solution_parser import candidate_response_validation
from scripts.run_case_outputs import run_model_preflight


@pytest.mark.parametrize(
    ("stage", "expected_tokens", "expected_timeout"),
    [
        ("router", 4096, 60.0),
        ("primary", 32768, 125.0),
        ("alternative", 24576, 125.0),
        ("verifier", 8192, 90.0),
        ("repair", 12288, 110.0),
        ("lemma", 16384, 110.0),
        ("finalizer", 4096, 60.0),
    ],
)
def test_role_policy_separates_output_and_call_budgets(
    stage,
    expected_tokens,
    expected_timeout,
):
    assert stage_output_cap(stage) == expected_tokens
    assert effective_output_tokens(stage, 65_536) == expected_tokens
    assert stage_call_timeout(stage) == expected_timeout
    assert effective_call_timeout(stage, 900.0) == expected_timeout
    assert effective_call_timeout(stage, 10.0) == 10.0


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (RuntimeError("401 unauthorized"), "auth_or_permission_failure"),
        (RuntimeError("429 too many requests"), "rate_limited"),
        (RuntimeError("503 server error"), "provider_5xx"),
        (RuntimeError("DNS name resolution failed"), "network_connect_failure"),
        (RuntimeError("ReadTimeout"), "network_read_timeout"),
        (RuntimeError("choices missing"), "response_shape_invalid"),
        (RuntimeError("opaque"), "unknown_provider_failure"),
    ],
)
def test_transport_failures_have_one_safe_classification(error, expected):
    assert classify_transport_failure(error) == expected


class _RecordingClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def test_provider_applies_role_cap_and_records_transport_attempts():
    client = _RecordingClient(
        ObservedModelResponse("ok", transport_attempts=2)
    )
    budget = CallBudget(1)
    budget.consume(stage="primary")
    response = OfficialClientProvider(client, ModelCallGate(1)).chat(
        messages=[{"role": "user", "content": "short"}],
        temperature=0.0,
        max_tokens=65_536,
        budget=budget,
        stage="primary",
    )

    assert response == "ok"
    assert client.calls[0]["max_tokens"] == 32_768
    assert budget.transport_attempts == 2
    record = budget.model_call_records[0]
    assert record["configured_output_tokens"] == 65_536
    assert record["stage_output_cap_tokens"] == 32_768
    assert record["max_output_tokens"] == 32_768
    assert record["transport_attempts"] == 2
    assert record["status"] == "completed"


def test_provider_replaces_raw_exception_with_safe_failure_code():
    class FailingClient:
        def chat(self, **_):
            raise RuntimeError("401 authorization secret-private-detail")

    budget = CallBudget(1)
    budget.consume(stage="primary")
    with pytest.raises(ModelTransportError) as captured:
        OfficialClientProvider(FailingClient(), ModelCallGate(1)).chat(
            messages=[{"role": "user", "content": "short"}],
            temperature=0.0,
            max_tokens=1024,
            budget=budget,
            stage="primary",
        )

    assert captured.value.code == "auth_or_permission_failure"
    assert "secret-private-detail" not in str(captured.value)
    assert budget.model_call_failure_count == 1
    assert budget.model_call_records[0]["failure_code"] == (
        "auth_or_permission_failure"
    )


def test_truncated_candidate_is_rejected_and_observable():
    client = _RecordingClient(
        '{"method":"direct","solution_text":"partial","final_answer":"2"'
    )
    budget = CallBudget(1)
    request = SolverRequest(
        candidate_id="primary-1",
        problem=ProblemParser().parse("Compute 1+1."),
        route=RoutePlan(
            primary_subject="general-math",
            auxiliary_subject=None,
            problem_type="calculation",
            answer_type="integer",
            risk_level="medium",
            candidate_count=1,
        ),
        skill_context="",
        method_family="direct-deduction",
    )

    with pytest.raises(ModelResponseError) as captured:
        SolverExecutor(
            OfficialClientProvider(client, ModelCallGate(1)),
            SolutionParser(),
        ).execute(
            PrimarySolver(),
            request,
            budget,
            temperature=0.0,
            max_tokens=4096,
        )

    assert captured.value.code == "candidate_json_incomplete"
    assert budget.model_response_rejection_count == 1
    assert budget.model_call_records[0]["response_validation"] == (
        "candidate_json_incomplete"
    )


def test_complete_json_with_missing_candidate_fields_is_schema_invalid():
    candidate = SolutionParser().parse(
        '{"final_answer":"2"}',
        candidate_id="incomplete",
        role="PrimarySolver",
        answer_type="integer",
    )

    assert candidate_response_validation(candidate) == (
        "candidate_schema_invalid",
        True,
    )


def test_l0_rejects_wrong_identity_without_calling_provider():
    client = _RecordingClient('{"status":"ok"}')
    report = run_model_preflight(
        client,
        requested_model="intern-s2-preview",
    )

    assert report["status"] == "failed"
    assert report["failed_level"] == "L0"
    assert report["levels"][0]["error_code"] == "model_identity_invalid"
    assert client.calls == []


def test_l0_rejects_missing_client_without_exposing_environment_details():
    report = run_model_preflight(None)

    assert report["status"] == "failed"
    assert report["failed_level"] == "L0"
    assert report["levels"][0]["error_code"] == "model_client_unavailable"


def test_nonempty_unstructured_text_cannot_pass_l1():
    report = run_model_preflight(_RecordingClient("OK"))

    assert report["status"] == "failed"
    assert report["failed_level"] == "L1"
    assert report["levels"][-1]["error_code"] == "response_shape_invalid"


def test_preflight_failure_report_never_contains_raw_exception_text():
    class FailingClient:
        def chat(self, **_):
            raise RuntimeError("401 private-provider-detail")

    report = run_model_preflight(FailingClient())
    serialized = json.dumps(report)

    assert report["failed_level"] == "L1"
    assert report["levels"][-1]["error_code"] == "auth_or_permission_failure"
    assert "private-provider-detail" not in serialized
