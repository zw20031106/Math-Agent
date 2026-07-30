from __future__ import annotations

import json

import pytest

from mathforge.config import HarnessConfig
from mathforge.harness.context_budget import ModelContextBudget
from mathforge.harness.reasoning_state import (
    ProgressDeltaParser,
    ReasoningState,
    ReasoningStateCompressor,
    ReasoningStateValidationError,
)
from mathforge.output.judge_trace import project_judge_trace
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.runtime import MathForgeHarness


HARD_PROBLEM = (
    "Evaluate the convergent series sum_{n=1}^infinity H_n^{(2)}/2^n, "
    "where H_n^{(2)}=sum_{k=1}^n 1/k^2."
)


def _config(**overrides) -> HarnessConfig:
    values = {
        "profile": "phase4-test",
        "status": "test",
        "max_model_calls": 3,
        "enable_router": False,
        "enable_skills": False,
        "enable_alternatives": False,
        "enable_tools": False,
        "enable_evidence": False,
        "enable_proof_obligations": False,
        "enable_verifier": False,
        "enable_memory": False,
        "enable_lemma_loop": False,
        "enable_rag": False,
        "enable_repair": False,
        "enable_finalizer": False,
        "enable_shadow": False,
        "enable_frozen_lemma_store": False,
        "enable_long_horizon": True,
    }
    values.update(overrides)
    return HarnessConfig(**values)


def _progress_payload(*, continued: bool = False) -> str:
    subgoal = {
        "subgoal_id": "g1",
        "statement": "Transform the nested series into a summable expression.",
        "depends_on": [],
        "exit_condition": "The series is reduced to standard constants.",
        "status": "closed" if continued else "open",
    }
    if continued:
        claims = [
            {
                "claim_id": "r2-c1",
                "statement": (
                    "The transformed expression evaluates to "
                    "pi^2/6-(ln 2)^2."
                ),
                "depends_on": ["r1-c1"],
                "subgoal_ids": ["g1"],
                "importance": "critical",
            }
        ]
        obligations = []
        closed = ["o1"]
        next_step = "Synthesize the public derivation."
    else:
        claims = [
            {
                "claim_id": "r1-c1",
                "statement": (
                    "Interchanging the absolutely convergent sums reduces the "
                    "target to a standard dilogarithm identity."
                ),
                "depends_on": [],
                "subgoal_ids": ["g1"],
                "importance": "supporting",
            }
        ]
        obligations = [
            {
                "obligation_id": "o1",
                "statement": "Justify the interchange and evaluate the identity.",
                "depends_on": ["r1-c1"],
            }
        ]
        closed = []
        next_step = "Close o1 using the standard integral representation."
    return json.dumps(
        {
            "public_summary": (
                "The key transformation is complete."
                if continued
                else "A concrete transformation and obligation were identified."
            ),
            "strategy": "structural-transform",
            "subgoals": [subgoal],
            "claims": claims,
            "open_obligations": obligations,
            "closed_obligation_ids": closed,
            "contradictions": [],
            "next_step": next_step,
            "stop_reason": "",
        }
    )


def _candidate_payload() -> str:
    return json.dumps(
        {
            "method": "structural-transform",
            "final_answer": r"\pi^2/6-(\ln 2)^2",
            "public_solution_steps": [
                "Interchange the absolutely convergent sums.",
                "Evaluate the resulting standard logarithmic integral.",
            ],
            "claims": [
                {
                    "claim_id": "c1",
                    "statement": (
                        "The convergent series equals "
                        "pi^2/6-(ln 2)^2."
                    ),
                    "depends_on": [],
                    "check_type": "reasoning",
                    "importance": "critical",
                }
            ],
            "solution_text": (
                "Absolute convergence permits the sum interchange. "
                "The resulting dilogarithm identity gives the stated value."
            ),
            "assumptions": [],
            "theorems": [],
            "unresolved_obligations": [],
        }
    )


class LongHorizonClient:
    def __init__(self, *, invalid_first_progress: bool = False) -> None:
        self.calls: list[list[dict[str, str]]] = []
        self.invalid_first_progress = invalid_first_progress

    def chat(self, *, messages, temperature, max_tokens) -> str:
        del temperature, max_tokens
        self.calls.append(messages)
        system = messages[0]["content"]
        if "Public protocol mode is explore" in system:
            if self.invalid_first_progress:
                return "{}"
            return _progress_payload()
        if "Public protocol mode is continue" in system:
            assert "r1-c1" in messages[-1]["content"]
            assert "o1" in messages[-1]["content"]
            return _progress_payload(continued=True)
        return _candidate_payload()


def test_reasoning_state_round_trip_preserves_problem_and_dependencies():
    problem = ProblemParser().parse(HARD_PROBLEM)
    state = ReasoningState.initialize(problem, strategy="structural-transform")
    delta = ProgressDeltaParser().parse(
        _progress_payload(),
        round_index=1,
        mode="explore",
    )
    advanced, summary = state.apply(delta)
    restored = ReasoningState.from_dict(advanced.to_dict())

    assert restored == advanced
    assert restored.schema_version == "1.1"
    assert restored.problem_frame.original_problem == problem.raw_problem
    assert restored.problem_frame.target == problem.target_phrase
    assert restored.claim_ledger.items[0].subgoal_ids == ("g1",)
    assert restored.open_obligations[0].depends_on == ("r1-c1",)
    assert summary["information_gain"] == 3


def test_reasoning_state_rejects_private_fields_and_unknown_dependencies():
    private = json.loads(_progress_payload())
    private["scratchpad"] = "hidden"
    with pytest.raises(ReasoningStateValidationError, match="private"):
        ProgressDeltaParser().parse(
            json.dumps(private),
            round_index=1,
            mode="explore",
        )

    invalid = json.loads(_progress_payload())
    invalid["claims"][0]["depends_on"] = ["missing-claim"]
    state = ReasoningState.initialize(ProblemParser().parse(HARD_PROBLEM))
    delta = ProgressDeltaParser().parse(
        json.dumps(invalid),
        round_index=1,
        mode="explore",
    )
    with pytest.raises(
        ReasoningStateValidationError,
        match="unknown PublicClaim dependency",
    ):
        state.apply(delta)


def test_token_compression_preserves_semantic_core():
    state = ReasoningState.initialize(ProblemParser().parse(HARD_PROBLEM))
    state, _ = state.apply(
        ProgressDeltaParser().parse(
            _progress_payload(),
            round_index=1,
            mode="explore",
        )
    )
    for index in range(2, 22):
        payload = json.loads(_progress_payload(continued=True))
        payload["public_summary"] = f"round-{index}:" + ("x" * 800)
        payload["claims"][0]["claim_id"] = f"r{index}-c1"
        payload["claims"][0]["depends_on"] = [
            "r1-c1" if index == 2 else f"r{index - 1}-c1"
        ]
        payload["closed_obligation_ids"] = []
        state, _ = state.apply(
            ProgressDeltaParser().parse(
                json.dumps(payload),
                round_index=index,
                mode="continue",
            )
        )

    compressed = ReasoningStateCompressor().compress(
        state,
        max_tokens=6000,
    )
    projection = json.loads(compressed.prompt_json)

    assert compressed.state_tokens <= 6000
    assert compressed.compressed
    assert projection["problem_frame"] == state.problem_frame.to_dict()
    assert projection["subgoal_ledger"] == state.subgoal_ledger.to_dict()
    assert projection["claim_ledger"] == state.claim_ledger.to_dict()
    assert projection["open_obligations"] == [
        item.to_dict() for item in state.open_obligations
    ]


def test_high_difficulty_two_round_synthesis_reuses_public_state():
    client = LongHorizonClient()
    result = MathForgeHarness(client, _config()).solve(HARD_PROBLEM, {})
    rounds = [
        event
        for event in result["trace"]
        if event["event"] == "round_summary"
    ]
    calls = next(
        event
        for event in result["trace"]
        if event["event"] == "budget_summary"
    )["model_call_records"]

    assert len(client.calls) == 2
    assert [item["mode"] for item in rounds] == ["explore", "synthesize"]
    assert "r1-c1" in client.calls[1][-1]["content"]
    assert "o1" in client.calls[1][-1]["content"]
    assert result["final_response"].strip()
    assert all(
        item["prompt_tokens"]
        + item["max_output_tokens"]
        + item["safety_margin_tokens"]
        <= item["context_window_tokens"]
        == 262144
        for item in calls
    )


def test_three_round_path_continues_only_with_public_information_gain():
    client = LongHorizonClient()
    result = MathForgeHarness(
        client,
        _config(max_model_calls=4),
    ).solve(HARD_PROBLEM, {})
    rounds = [
        event
        for event in result["trace"]
        if event["event"] == "round_summary"
    ]

    assert len(client.calls) == 3
    assert [item["mode"] for item in rounds] == [
        "explore",
        "continue",
        "synthesize",
    ]
    assert rounds[0]["information_gain"] > 0
    assert rounds[1]["closed_obligation_ids"] == ["o1"]
    assert "r2-c1" in client.calls[2][-1]["content"]


def test_simple_problem_stays_single_round_and_progress_failure_falls_back():
    simple_client = LongHorizonClient()
    simple = MathForgeHarness(simple_client, _config()).solve(
        "Compute 2+2.",
        {},
    )
    assert len(simple_client.calls) == 1
    simple_plan = next(
        event
        for event in simple["trace"]
        if event["event"] == "long_horizon_planned"
    )
    assert not simple_plan["enabled"]

    fallback_client = LongHorizonClient(invalid_first_progress=True)
    recovered = MathForgeHarness(fallback_client, _config()).solve(
        HARD_PROBLEM,
        {},
    )
    completed = next(
        event
        for event in recovered["trace"]
        if event["event"] == "reasoning_loop_completed"
    )

    assert len(fallback_client.calls) == 2
    assert recovered["final_response"].strip()
    assert completed["degraded_reason"] == "progress_delta_invalid"
    assert completed["candidate_id"] == "primary-1"


def test_judge_trace_exposes_round_deltas_without_private_reasoning():
    result = MathForgeHarness(LongHorizonClient(), _config()).solve(
        HARD_PROBLEM,
        {},
    )
    public = project_judge_trace(
        result["trace"],
        final_response=result["final_response"],
    )
    serialized = json.dumps(public, ensure_ascii=False).lower()
    rounds = [event for event in public if event["event"] == "round_summary"]
    budget = ModelContextBudget(
        context_window_tokens=262144,
        safety_margin_tokens=8192,
    )

    assert [item["mode"] for item in rounds] == ["explore", "synthesize"]
    assert "scratchpad" not in serialized
    assert "chain_of_thought" not in serialized
    assert "private_reasoning" not in serialized
    allocation = budget.allocate(
        [{"role": "user", "content": json.dumps(rounds)}],
        configured_max_output_tokens=20000,
    )
    assert (
        allocation.prompt_tokens
        + allocation.max_output_tokens
        + allocation.safety_margin_tokens
        <= allocation.context_window_tokens
    )


def test_reasoning_state_is_solve_local_on_a_shared_harness():
    client = LongHorizonClient()
    harness = MathForgeHarness(client, _config())
    first = harness.solve(HARD_PROBLEM, {})
    second = harness.solve(
        "Evaluate the limit lim_{n->infinity} "
        "n^4(ln(1+1/n)-1/n+1/(2n^2)-1/(3n^3)).",
        {},
    )
    first_state = next(
        event
        for event in first["trace"]
        if event["event"] == "reasoning_state_initialized"
    )
    second_state = next(
        event
        for event in second["trace"]
        if event["event"] == "reasoning_state_initialized"
    )

    assert first_state["state_id"] != second_state["state_id"]
    assert "H_n^{(2)}" not in client.calls[2][-1]["content"]
    assert len(client.calls) == 4
