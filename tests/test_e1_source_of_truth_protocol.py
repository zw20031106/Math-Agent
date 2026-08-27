from __future__ import annotations

from dataclasses import replace
import inspect
import json
from pathlib import Path

import pytest

from mathforge.agent_runtime.action_registry import ActionRegistry
from mathforge.agent_runtime.definitions import AgentRegistry
from mathforge.agent_runtime.protocol import ACTION_TYPES
from mathforge.agent_runtime.runtime import SessionAgentRuntime
from mathforge.agents.finalizer import LLMFinalizer
from mathforge.agents.lemma_curator import LLMLemmaCuratorAgent, LLMLemmaRequest
from mathforge.agents.registry import PromptContractLoader
from mathforge.agents.repair import RepairAgent
from mathforge.agents.router_planner import RouterPlanner
from mathforge.agents.skill_selector import DynamicSkillSelector as FacadeSelector
from mathforge.agents.solver import PrimarySolver, SolverRequest
from mathforge.agents.verifier import VerifierSkepticAgent
from mathforge.harness.budget import CallBudget
from mathforge.harness.errors import (
    BudgetExceeded,
    ContractViolation,
    InternalErrorClass,
    ModelResponseError,
    ModelTransportError,
    classify_internal_error,
    should_reraise_in_test,
)
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.harness.problem_conditions import (
    ProblemConditionEnvelope,
    build_problem_condition_envelope,
)
from mathforge.harness.schemas import CandidateSolution, Claim
from mathforge.output.deterministic_formatter import DeterministicFormatter
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import SolutionParser
from mathforge.skills.selector import DynamicSkillSelector as CanonicalSelector


def _canary_problem():
    parsed = ProblemParser().parse("Find x.")
    return replace(
        parsed,
        definitions=["DEF_CANARY"],
        quantifiers=["QUANT_CANARY"],
        constraints=["CONSTRAINT_CANARY"],
        assumptions=["ASSUMPTION_CANARY"],
        domains={"x": "real"},
        target_phrase="TARGET_CANARY",
        target_kind="compute_value",
    )


def _candidate() -> CandidateSolution:
    return CandidateSolution(
        candidate_id="candidate-1",
        role="PrimarySolver",
        method="direct-deduction",
        final_answer="42",
        answer_type="integer",
        claims=[Claim("claim-1", "x = x")],
        public_solution_steps=["The public claim is established."],
        solution_text="The public claim is established.",
    )


class _RecordingProvider:
    def __init__(self, response: str | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.messages: list[dict[str, str]] | None = None

    def chat(self, *, messages, **kwargs):
        del kwargs
        self.messages = messages
        if self.error is not None:
            raise self.error
        return self.response or ""


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def chat(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return "ok"


def _bound_provider(runtime: SessionAgentRuntime):
    budget = CallBudget(1, model_call_start_margin_seconds=0.0)
    budget.bind_scheduler_case(runtime.session_id)
    budget.bind_agent_runtime(runtime)
    client = _RecordingClient()
    provider = OfficialClientProvider(client, ModelCallGate(1))
    return provider, budget, client


def _provider_call(provider, budget, **kwargs):
    return provider.chat(
        messages=[{"role": "user", "content": "public input"}],
        temperature=0.0,
        max_tokens=32,
        budget=budget,
        **kwargs,
    )


def test_prompt_versions_are_loaded_from_contract_frontmatter_for_every_role():
    definitions = AgentRegistry.default()
    contracts = PromptContractLoader()

    for role in definitions.roles():
        definition = definitions.get(role)
        contract = contracts.load(definition.prompt_contract)
        assert definition.prompt_version == contract.fields["version"]

    source = inspect.getsource(AgentRegistry.default)
    assert "prompt_versions" not in source


def test_action_registry_is_the_complete_authorized_and_routable_action_set():
    registry = ActionRegistry()
    definitions = AgentRegistry.default()

    assert registry.declared_actions == ACTION_TYPES
    registry.validate()
    assert all(registry.has_handler(action) for action in ACTION_TYPES)
    for role in definitions.roles():
        assert set(definitions.get(role).allowed_action_types) == set(
            registry.actions_for(role)
        )

    for role, phase in (
        ("RouterPlanner", "router"),
        ("PrimarySolver", "solve"),
        ("PrimarySolver", "progress"),
        ("PrimarySolver", "candidate"),
        ("PrimarySolver", "peer_review_turn"),
        ("PrimarySolver", "rebuttal_turn"),
        ("LemmaCurator", "lemma_turn"),
        ("VerifierSkeptic", "verifier_turn"),
        ("VerifierSkeptic", "final_audit_turn"),
        ("RepairAgent", None),
        ("LLMFinalizer", None),
    ):
        expected = registry.actions_for(role, phase=phase)
        assert set(registry.prompt_actions(role, phase=phase)) == set(expected)
        assert expected <= registry.declared_actions


def test_problem_condition_envelope_preserves_categories_and_is_shared_by_roles():
    problem = _canary_problem()
    envelope = build_problem_condition_envelope(problem)
    assert isinstance(envelope, ProblemConditionEnvelope)
    assert envelope.to_dict()["definitions"] == ["DEF_CANARY"]
    assert envelope.to_dict()["quantifiers"] == ["QUANT_CANARY"]
    assert envelope.to_dict()["constraints"] == ["CONSTRAINT_CANARY"]

    route = RouterPlanner().plan(problem)
    solver_request = SolverRequest(
        "candidate-1",
        problem,
        route,
        "",
        route.method_families[0],
    )
    solver_text = json.dumps(PrimarySolver().build_messages(solver_request))
    verifier_payload = VerifierSkepticAgent._review_payload(
        problem,
        [_candidate()],
        {"candidate-1": []},
        [],
    )
    markers = (
        "DEF_CANARY",
        "QUANT_CANARY",
        "CONSTRAINT_CANARY",
        "ASSUMPTION_CANARY",
    )
    assert all(marker in solver_text for marker in markers)
    assert all(
        marker in json.dumps(verifier_payload, ensure_ascii=False)
        for marker in markers
    )

    lemma_provider = _RecordingProvider(
        json.dumps(
            {
                "protocol_version": "1.0",
                "task_result_type": "CheckpointArtifact",
                "action": "abstain",
                "public_state_delta": {},
                "result_payload": {},
                "outbound_intents": [],
                "progress_summary": "No additional lemma is required.",
                "stop_reason": "no_lemma_needed",
            }
        )
    )
    lemma_request = LLMLemmaRequest(
        problem=problem.normalized_problem,
        plan_id="plan-1",
        plan_summary="public plan",
        conditions=tuple(problem.assumptions),
        target_obligation_ids=(),
        request_text="check the supplied conditions",
        recipient_role="PrimarySolver",
        condition_envelope=envelope,
    )
    LLMLemmaCuratorAgent(lemma_provider).execute(
        lemma_request,
        CallBudget(1),
        max_tokens=256,
    )
    assert lemma_provider.messages is not None
    lemma_text = json.dumps(lemma_provider.messages, ensure_ascii=False)
    assert all(marker in lemma_text for marker in markers)

    repair_provider = _RecordingProvider(error=RuntimeError("stop after prompt"))
    with pytest.raises(RuntimeError, match="stop after prompt"):
        RepairAgent(repair_provider, SolutionParser()).repair(
            problem,
            _candidate(),
            ["claim-1"],
            [],
            CallBudget(1),
            max_tokens=256,
        )
    assert repair_provider.messages is not None
    repair_text = json.dumps(repair_provider.messages, ensure_ascii=False)
    assert all(marker in repair_text for marker in markers)

    finalizer_provider = _RecordingProvider(error=RuntimeError("stop after prompt"))
    finalizer = LLMFinalizer(
        finalizer_provider,
        SolutionParser(),
        DeterministicFormatter(),
    )
    finalizer.finalize(
        problem,
        _candidate(),
        "42",
        CallBudget(1),
        max_tokens=256,
    )
    assert finalizer_provider.messages is not None
    finalizer_text = json.dumps(finalizer_provider.messages, ensure_ascii=False)
    assert all(marker in finalizer_text for marker in markers)


def test_skill_selector_compatibility_path_is_an_alias_of_the_single_implementation():
    root = Path(__file__).resolve().parents[1]
    class_definitions = []
    for path in root.rglob("*.py"):
        class_definitions.extend(
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("class DynamicSkillSelector")
        )
    assert len(class_definitions) == 1
    assert FacadeSelector is CanonicalSelector


@pytest.mark.parametrize(
    ("stage", "turn_kind", "agent_id", "input_artifact_ids", "error_type"),
    [
        ("invalid_stage", "solver_candidate_standard", "PrimarySolver:candidate-1", (), ValueError),
        ("primary", "invalid_task", "PrimarySolver:candidate-1", (), ValueError),
        ("primary", "solver_candidate_standard", "UnknownRole:candidate-1", (), ValueError),
        ("verifier", "verifier", "VerifierSkeptic", ("missing-artifact",), KeyError),
    ],
)
def test_provider_begin_rejection_is_fail_closed(
    stage,
    turn_kind,
    agent_id,
    input_artifact_ids,
    error_type,
):
    provider, budget, client = _bound_provider(
        SessionAgentRuntime("e" * 32, AgentRegistry.default())
    )
    with pytest.raises(error_type):
        _provider_call(
            provider,
            budget,
            stage=stage,
            turn_kind=turn_kind,
            agent_id=agent_id,
            input_artifact_ids=input_artifact_ids,
        )
    assert client.calls == []


def test_provider_stale_plan_begin_rejection_is_fail_closed():
    problem = ProblemParser().parse(
        "Prove that x^2 is nonnegative for every real x."
    )
    first = RouterPlanner().plan_authoritative(problem)
    runtime = SessionAgentRuntime("s" * 32, AgentRegistry.default())
    runtime.publish_router_decision(
        route_payload=first.route_plan.to_dict(),
        plan=first.authoritative_plan,
    )
    old_turn = runtime.begin_model_turn(
        stage="primary",
        turn_kind="solver_progress",
        agent_hint="PrimarySolver:primary-1",
    )
    runtime.mark_dispatched(old_turn.turn_id)
    second = RouterPlanner().plan_authoritative(
        problem,
        previous_plan=first.authoritative_plan,
    )
    runtime.publish_router_decision(
        route_payload=second.route_plan.to_dict(),
        plan=second.authoritative_plan,
    )

    provider, budget, client = _bound_provider(runtime)
    with pytest.raises(RuntimeError, match="replan ACK barrier"):
        _provider_call(
            provider,
            budget,
            stage="primary",
            turn_kind="solver_candidate_standard",
            agent_id="PrimarySolver:primary-1",
        )
    assert client.calls == []


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ModelTransportError("provider_5xx"), InternalErrorClass.PROVIDER_FAILURE),
        (BudgetExceeded("deadline budget"), InternalErrorClass.DEADLINE),
        (TimeoutError("timed out"), InternalErrorClass.DEADLINE),
        (ModelResponseError("schema_invalid"), InternalErrorClass.EXPECTED_DEGRADATION),
        (ContractViolation("contract"), InternalErrorClass.EXPECTED_DEGRADATION),
        (AssertionError("invariant failed"), InternalErrorClass.INVARIANT_VIOLATION),
        (PermissionError("Agent phase cannot perform Action"), InternalErrorClass.INVARIANT_VIOLATION),
        (TypeError("programming failure"), InternalErrorClass.PROGRAMMING_ERROR),
    ],
)
def test_internal_error_classification_and_test_mode_reraise_policy(error, expected):
    actual = classify_internal_error(error)
    assert actual is expected
    assert should_reraise_in_test(actual) is (
        expected
        in {
            InternalErrorClass.INVARIANT_VIOLATION,
            InternalErrorClass.PROGRAMMING_ERROR,
        }
    )


def test_competition_harness_returns_programming_error_class_without_hiding_it():
    from dataclasses import replace

    from mathforge.runtime import MathForgeHarness
    from mathforge.config import HarnessConfig

    harness = MathForgeHarness(
        _RecordingClient(),
        replace(
            HarnessConfig(),
            profile="e1-competition",
            status="candidate-unvalidated",
            enable_router=False,
        ),
    )

    def broken_parser(*args, **kwargs):
        del args, kwargs
        raise TypeError("programming failure")

    harness._problem_parser.parse = broken_parser
    result = harness.solve("1+1", {})

    assert result["run_metrics"]["error_class"] == "PROGRAMMING_ERROR"
    completed = [
        event for event in result["trace"] if event.get("event") == "run_completed"
    ]
    assert completed[-1]["error_class"] == "PROGRAMMING_ERROR"


def test_test_mode_reraises_invariant_and_programming_errors_at_public_boundary():
    from mathforge.config import HarnessConfig
    from user_agent import ReasoningAgent

    class RaisingHarness:
        def solve(self, problem, metadata, **kwargs):
            del problem, metadata, kwargs
            raise AssertionError("invariant failure")

        @staticmethod
        def last_raw_responses(response_key):
            del response_key
            return []

        @staticmethod
        def release_raw_responses(response_key):
            del response_key

    agent = ReasoningAgent.__new__(ReasoningAgent)
    agent._config = HarnessConfig(profile="e1-test", status="test")
    agent._harness = RaisingHarness()
    agent._case_gate = __import__("threading").BoundedSemaphore(1)

    with pytest.raises(AssertionError, match="invariant failure"):
        agent.solve("1+1", {})
