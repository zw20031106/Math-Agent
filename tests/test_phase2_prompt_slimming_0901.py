from __future__ import annotations

import json

import pytest

from mathforge.agents.prompt_compiler import (
    PromptCompiler,
    REQUIRED_REASONING_FIELDS,
    REQUIRED_STATE_FIELDS,
)
from mathforge.agents.router_planner import RouterRuleEngine
from mathforge.agents.solver import PrimarySolver, SolverRequest
from mathforge.harness.budget import CallBudget
from mathforge.harness.context_budget import (
    InternS2TokenCounter,
    OfficialTokenizerUnavailable,
)
from mathforge.harness.schemas import strip_prompt_descriptions
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.evaluation.production_preflight import run_production_preflight


def _request(problem_text: str = "Compute 1+1.") -> SolverRequest:
    problem = ProblemParser().parse(problem_text)
    route = RouterRuleEngine().plan(problem)
    return SolverRequest(
        "phase2",
        problem,
        route,
        "",
        route.method_families[0],
    )


def test_every_prompt_role_declares_a_nonempty_state_slice() -> None:
    assert set(REQUIRED_STATE_FIELDS) == {
        "router_planner",
        "primary_solver",
        "alternative_solver",
        "lemma_curator",
        "verifier_skeptic",
        "repair",
        "finalizer",
    }
    assert REQUIRED_REASONING_FIELDS[:3] == (
        "state_id",
        "version",
        "problem_frame",
    )
    assert PromptCompiler.required_state_fields("primary_solver") == REQUIRED_STATE_FIELDS[
        "primary_solver"
    ]


def test_prompt_compiler_slices_state_and_removes_description_prose() -> None:
    request = _request()
    context = {
        "context_snapshot_id": "ctx-1",
        "conditions": ["x>0"],
        "candidates": [{"candidate_id": "c1", "description": "discarded prose"}],
        "obligations": [
            {"obligation_id": "o1", "description": "prove x>0"}
        ],
        "secret_state": "must-not-be-sent",
    }
    state = {
        "state_id": "s1",
        "version": 2,
        "problem_frame": {"normalized_problem": "Compute 1+1."},
        "claim_ledger": {"items": []},
        "subgoal_ledger": {"items": []},
        "open_obligations": [],
        "evidence_refs": [],
        "contradictions": [],
        "strategy": "direct",
        "verified_fact_bank": {"facts": []},
        "proof_backbone": {},
        "private_state": "must-not-be-sent",
    }
    user = (
        "Problem:\n"
        + ("Given x>0, compute 1+1 while preserving the stated condition. " * 20)
        + "\nRequired core method family: direct-deduction.\n"
        "Authorized context view:\n"
        + json.dumps(context, ensure_ascii=False)
        + "\nPublic ReasoningState JSON:\n"
        + json.dumps(state, ensure_ascii=False)
    )
    compilation = PromptCompiler().compile_solver(
        "primary_solver",
        problem=request.problem,
        route=request.route,
        user_content=user,
    )
    rendered = compilation.messages[-1]["content"]
    assert compilation.state_slice_applied is True
    assert "secret_state" not in rendered
    assert "private_state" not in rendered
    assert '"description"' not in rendered
    assert '"statement":"prove x>0"' in rendered


def test_state_share_gate_trims_state_before_dispatch() -> None:
    request = _request()
    context = {"context_snapshot_id": "ctx", "candidates": [{"statement": "x" * 8000}]}
    state = {
        "state_id": "s",
        "version": 1,
        "problem_frame": {},
        "claim_ledger": {"items": ["y" * 8000]},
        "subgoal_ledger": {"items": []},
        "open_obligations": [],
        "evidence_refs": [],
        "contradictions": [],
        "strategy": "z" * 8000,
        "verified_fact_bank": {},
        "proof_backbone": {},
    }
    user = (
        "Problem:\nCompute 1+1.\nRequired core method family: direct-deduction.\n"
        "Authorized context view:\n" + json.dumps(context)
        + "\nPublic ReasoningState JSON:\n" + json.dumps(state)
    )
    compilation = PromptCompiler().compile_solver(
        "primary_solver",
        problem=request.problem,
        route=request.route,
        user_content=user,
    )
    components = compilation.prompt_component_tokens
    dynamic_total = sum(
        components[name]
        for name in ("problem_tokens", "state_tokens", "skill_tokens")
    )
    assert compilation.state_trimmed is True
    assert components["state_tokens"] == 0
    assert components["problem_tokens"] / dynamic_total >= 0.45


def test_finished_observed_usage_is_the_canonical_completion_api() -> None:
    budget = CallBudget(1)
    budget.consume(stage="primary")
    index = budget.record_model_call_started(
        "primary",
        {
            "prompt_tokens": 10,
            "max_output_tokens": 1000,
            "counting_mode": "multilingual_estimate",
        },
    )
    budget.record_model_call_finished(
        index,
        observed_output_tokens=7,
        output_counting_mode="multilingual_estimate",
        output_chars=7,
        elapsed_seconds=0.01,
    )
    assert budget.observed_output_tokens == 7
    assert budget.model_call_records[index]["status"] == "completed"


def test_tokenizer_fallback_warns_and_strict_preflight_fails(caplog) -> None:
    counter = InternS2TokenCounter()
    with caplog.at_level("WARNING"):
        counter.count_text("x")
    assert counter.fallback_invocations >= 1
    assert "tokenizer 回落" in caplog.text
    with pytest.raises(OfficialTokenizerUnavailable):
        counter.require_official_tokenizer()

    class Client:
        def chat(self, **_kwargs):
            raise AssertionError("strict tokenizer check must happen first")

    report = run_production_preflight(
        Client(),
        require_official_tokenizer=True,
    )
    assert report["status"] == "failed"
    assert report["failed_level"] == "L0"
    assert report["levels"][-1]["error_code"] == "official_tokenizer_unavailable"


def test_schema_prompt_description_stripper_is_recursive() -> None:
    payload = {
        "description": "schema prose",
        "nested": [{"evidence_id": "e1", "description": "x"}],
    }
    compact = strip_prompt_descriptions(payload)
    assert "description" not in compact
    assert compact["nested"][0] == {"evidence_id": "e1", "statement": "x"}
