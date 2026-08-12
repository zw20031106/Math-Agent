from __future__ import annotations

import json

import pytest

from mathforge.agents.solver import PrimarySolver, SolverExecutor, SolverRequest
from mathforge.harness.budget import CallBudget
from mathforge.harness.deadline import DeadlineController
from mathforge.harness.errors import ModelResponseError, ModelTransportError
from mathforge.harness.model_policy import (
    PROVIDER_CALL_TIMEOUT_SECONDS,
    PROVIDER_HTTP_TIMEOUT_SECONDS,
    PROVIDER_RESPONSE_LIMIT_SECONDS,
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
        ("router", 8192, 180.0),
        ("primary", 32768, 420.0),
        ("alternative", 32768, 420.0),
        ("verifier", 16384, 300.0),
        ("repair", 24576, 360.0),
        ("lemma", 16384, 300.0),
        ("finalizer", 8192, 180.0),
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
    assert effective_call_timeout(stage, 900.0) == min(
        expected_timeout,
        PROVIDER_CALL_TIMEOUT_SECONDS,
    )
    assert effective_call_timeout(stage, 10.0) == 10.0


def test_provider_timeout_layers_leave_transport_and_gate_grace():
    assert PROVIDER_RESPONSE_LIMIT_SECONDS == 390.0
    assert PROVIDER_HTTP_TIMEOUT_SECONDS == 420.0
    assert PROVIDER_CALL_TIMEOUT_SECONDS == 435.0


def test_solver_keeps_a_valid_candidate_that_arrives_at_finalize_cutoff():
    now = [0.0]
    response = json.dumps(
        {
            "method": "direct-deduction",
            "method_steps": [
                {
                    "step_id": "s1",
                    "kind": "conclusion",
                    "claim_ids": ["c1"],
                    "theorem": "",
                }
            ],
            "solution_text": "Adding one and one gives two.",
            "public_solution_steps": ["Compute 1+1=2."],
            "final_answer": "2",
            "assumptions": [],
            "theorems": [],
            "claims": [
                {
                    "claim_id": "c1",
                    "statement": "The sum equals 2.",
                    "depends_on": [],
                    "check_type": "reasoning",
                    "importance": "critical",
                }
            ],
            "unresolved_obligations": [],
        }
    )

    class CutoffClient:
        def chat(self, **_kwargs):
            now[0] = 8.0
            return response

    budget = CallBudget(1)
    budget.deadline = DeadlineController(
        soft_deadline_seconds=5.0,
        exploration_deadline_seconds=8.0,
        hard_deadline_seconds=10.0,
        deterministic_finalize_reserve_seconds=2.0,
        model_call_start_margin_seconds=0.0,
        clock=lambda: now[0],
    )
    request = SolverRequest(
        candidate_id="primary-cutoff",
        problem=ProblemParser().parse("Compute 1+1."),
        route=RoutePlan(
            primary_subject="general-math",
            auxiliary_subject=None,
            problem_type="calculation",
            answer_type="integer",
            risk_level="low",
            candidate_count=1,
        ),
        skill_context="",
        method_family="direct-deduction",
    )

    candidate = SolverExecutor(
        OfficialClientProvider(CutoffClient(), ModelCallGate(1)),
        SolutionParser(),
    ).execute(
        PrimarySolver(),
        request,
        budget,
        temperature=0.0,
        max_tokens=8192,
    )

    assert budget.must_finalize()
    assert candidate.final_answer == "2"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (RuntimeError("401 unauthorized"), "auth_or_permission_failure"),
        (RuntimeError("429 too many requests"), "rate_limited"),
        (RuntimeError("503 server error"), "provider_5xx"),
        (RuntimeError("DNS name resolution failed"), "network_connect_failure"),
        (
            RuntimeError("SSLError: UNEXPECTED_EOF_WHILE_READING"),
            "network_connect_failure",
        ),
        (RuntimeError("ProxyError"), "network_connect_failure"),
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


def test_truncated_candidate_with_answer_is_degraded_and_observable():
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

    candidate = SolverExecutor(
        OfficialClientProvider(client, ModelCallGate(1)),
        SolutionParser(),
    ).execute(
        PrimarySolver(),
        request,
        budget,
        temperature=0.0,
        max_tokens=4096,
    )

    assert candidate.final_answer == "2"
    assert candidate.degraded is True
    assert budget.model_response_rejection_count == 0
    assert budget.model_call_records[0]["response_validation"] in {
        "candidate_json_incomplete",
        "candidate_method_deviation",
    }


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


def test_primary_retries_one_contract_rejection_at_zero_temperature():
    valid = json.dumps(
        {
            "method": "direct-deduction",
            "method_steps": [
                {
                    "step_id": "s1",
                    "kind": "conclusion",
                    "claim_ids": ["c1"],
                    "theorem": "",
                }
            ],
            "solution_text": "Adding one and one gives two.",
            "public_solution_steps": ["Compute 1+1=2."],
            "final_answer": "2",
            "assumptions": [],
            "theorems": [],
            "claims": [
                {
                    "claim_id": "c1",
                    "statement": "The sum equals 2.",
                    "depends_on": [],
                    "check_type": "reasoning",
                    "importance": "critical",
                }
            ],
            "unresolved_obligations": [],
        }
    )

    class SequenceClient:
        def __init__(self):
            self.responses = ['{"final_answer":"2"}', valid]
            self.calls = []

        def chat(self, **kwargs):
            self.calls.append(kwargs)
            return self.responses.pop(0)

    client = SequenceClient()
    budget = CallBudget(2)
    request = SolverRequest(
        candidate_id="primary-retry",
        problem=ProblemParser().parse("Compute 1+1."),
        route=RoutePlan(
            primary_subject="general-math",
            auxiliary_subject=None,
            problem_type="calculation",
            answer_type="integer",
            risk_level="low",
            candidate_count=1,
        ),
        skill_context="",
        method_family="direct-deduction",
    )

    candidate = SolverExecutor(
        OfficialClientProvider(client, ModelCallGate(1)),
        SolutionParser(),
    ).execute(
        PrimarySolver(),
        request,
        budget,
        temperature=0.2,
        max_tokens=8192,
    )

    assert candidate.final_answer == "2"
    assert [call["temperature"] for call in client.calls] == [0.2, 0.0]
    retry_message = client.calls[1]["messages"][-1]["content"]
    assert "claims:missing" in retry_message
    assert "method_steps:missing" not in retry_message
    assert "Regenerate it from scratch" in retry_message
    assert budget.used_calls == 2
    assert budget.model_response_rejection_count == 1


def test_primary_retries_nested_schema_validation_failure():
    invalid = json.dumps(
        {
            "method": "direct-deduction",
            "method_steps": [],
            "solution_text": "Invalid duplicate Claim identifiers.",
            "public_solution_steps": ["Invalid duplicate Claim identifiers."],
            "final_answer": "2",
            "assumptions": [],
            "theorems": [],
            "claims": [
                {
                    "claim_id": "c1",
                    "statement": "First.",
                    "depends_on": [],
                    "check_type": "reasoning",
                    "importance": "supporting",
                },
                {
                    "claim_id": "c1",
                    "statement": "Duplicate.",
                    "depends_on": [],
                    "check_type": "reasoning",
                    "importance": "critical",
                },
            ],
            "unresolved_obligations": [],
        }
    )
    valid = json.dumps(
        {
            "method": "direct-deduction",
            "method_steps": [
                {
                    "step_id": "s1",
                    "kind": "conclusion",
                    "claim_ids": ["c1"],
                    "theorem": "",
                }
            ],
            "solution_text": "Adding one and one gives two.",
            "public_solution_steps": ["Compute 1+1=2."],
            "final_answer": "2",
            "assumptions": [],
            "theorems": [],
            "claims": [
                {
                    "claim_id": "c1",
                    "statement": "The sum equals 2.",
                    "depends_on": [],
                    "check_type": "reasoning",
                    "importance": "critical",
                }
            ],
            "unresolved_obligations": [],
        }
    )

    class SequenceClient:
        def __init__(self):
            self.responses = [invalid, valid]
            self.calls = []

        def chat(self, **kwargs):
            self.calls.append(kwargs)
            return self.responses.pop(0)

    client = SequenceClient()
    request = SolverRequest(
        candidate_id="primary-nested-retry",
        problem=ProblemParser().parse("Compute 1+1."),
        route=RoutePlan(
            primary_subject="general-math",
            auxiliary_subject=None,
            problem_type="calculation",
            answer_type="integer",
            risk_level="low",
            candidate_count=1,
        ),
        skill_context="",
        method_family="direct-deduction",
    )
    candidate = SolverExecutor(
        OfficialClientProvider(client, ModelCallGate(1)),
        SolutionParser(),
    ).execute(
        PrimarySolver(),
        request,
        CallBudget(2),
        temperature=0.2,
        max_tokens=8192,
    )

    assert candidate.final_answer == "2"
    assert "nested_schema_invariant:invalid" in (
        client.calls[1]["messages"][-1]["content"]
    )


def test_primary_preserves_schema_details_when_retry_transport_fails():
    class SequenceClient:
        def __init__(self):
            self.calls = 0

        def chat(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return '{"final_answer":"2"}'
            raise RuntimeError("503 private provider detail")

    request = SolverRequest(
        candidate_id="primary-retry-transport",
        problem=ProblemParser().parse("Compute 1+1."),
        route=RoutePlan(
            primary_subject="general-math",
            auxiliary_subject=None,
            problem_type="calculation",
            answer_type="integer",
            risk_level="low",
            candidate_count=1,
        ),
        skill_context="",
        method_family="direct-deduction",
    )
    with pytest.raises(ModelResponseError) as captured:
        SolverExecutor(
            OfficialClientProvider(SequenceClient(), ModelCallGate(1)),
            SolutionParser(),
        ).execute(
            PrimarySolver(),
            request,
            CallBudget(2),
            temperature=0.2,
            max_tokens=8192,
        )

    assert captured.value.code == "candidate_schema_invalid"
    assert "claims:missing" in captured.value.details
    assert "retry_transport:provider_5xx" in captured.value.details
    assert "private provider detail" not in str(captured.value)


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


def test_l0_to_l5_preflight_uses_the_production_candidate_contract_retry():
    valid = json.dumps(
        {
            "method": "direct-deduction",
            "method_steps": [
                {
                    "step_id": "s1",
                    "kind": "conclusion",
                    "claim_ids": ["c1"],
                    "theorem": "",
                }
            ],
            "solution_text": "One plus one equals two.",
            "public_solution_steps": ["Compute 1+1=2."],
            "final_answer": "2",
            "assumptions": [],
            "theorems": [],
            "claims": [
                {
                    "claim_id": "c1",
                    "statement": "The sum is 2.",
                    "depends_on": [],
                    "check_type": "reasoning",
                    "importance": "critical",
                }
            ],
            "unresolved_obligations": [],
        }
    )

    class PreflightClient:
        def __init__(self):
            self.responses = [
                '{"status":"ok"}',
                json.dumps(
                    {
                        "protocol_version": "1.0",
                        "task_result_type": "PreflightArtifact",
                        "action": "complete",
                        "public_state_delta": {},
                        "result_payload": {"status": "ok"},
                        "outbound_intents": [],
                        "progress_summary": "preflight ok",
                        "stop_reason": "preflight complete",
                    }
                ),
                json.dumps(
                    {
                        "primary_domain": "general-math",
                        "secondary_domain": None,
                        "risk": "medium",
                        "patterns": ["decisive-relation"],
                        "preferred_methods": ["direct-deduction"],
                        "alternative_methods": ["constructive-computation"],
                        "needs_long_horizon": False,
                    }
                ),
                '{"final_answer":"2"}',
                valid,
                json.dumps(
                    {
                        "findings": [
                            {
                                "candidate_id": "preflight-l4",
                                "claim_id": "c1",
                                "obligation_ids": [
                                    "preflight-l4:sufficiency"
                                ],
                                "review_target_ids": [],
                                "review_level": "obligation",
                                "status": "pass",
                                "public_rationale": "The final claim supports 2.",
                                "missing_condition": "",
                                "counterexample_summary": "",
                            }
                        ]
                    }
                ),
            ]

        def chat(self, **_kwargs):
            return self.responses.pop(0)

    report = run_model_preflight(PreflightClient())

    assert report["status"] == "passed"
    assert [item["level"] for item in report["levels"]] == [
        "L0",
        "L1",
        "L2",
        "L3",
        "L4",
        "L5",
    ]
    assert report["levels"][4]["transport_attempts"] == 2
