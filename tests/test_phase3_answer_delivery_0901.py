from __future__ import annotations

import json

import pytest

from mathforge.agent_runtime.router_protocol import parse_router_intent
from mathforge.harness.answer_ladder import AnswerLadder
from mathforge.harness.budget import CallBudget
from mathforge.harness.metrics import RunMetrics
from mathforge.harness.schemas import CandidateSolution, MathSession
from mathforge.harness.terminalizer import (
    NoThrowTerminalizer,
    minimal_fallback_metrics,
)
from mathforge.output.public_result import build_public_result
from mathforge.parsing.answer_extraction import (
    enforce_answer_form,
    extract_final_answer_text,
    sanitize_final_answer,
)
from mathforge.parsing.solution_parser import (
    SolutionParser,
    candidate_response_validation,
)


def _candidate(answer: str, *, candidate_id: str = "c1") -> CandidateSolution:
    return CandidateSolution(
        candidate_id=candidate_id,
        role="PrimarySolver",
        method="direct-deduction",
        final_answer=answer,
        answer_type="expression",
    )


def test_answer_ladder_never_skips_a_usable_level() -> None:
    ladder = AnswerLadder()

    l1 = ladder.resolve(
        validated_candidates=[_candidate("1")],
        unverified_candidates=[_candidate("2", candidate_id="c2")],
        raw_model_outputs=[r"\boxed{3}"],
    )
    assert l1.source == "L1"
    assert l1.answer == "1"

    l2 = ladder.resolve(unverified_candidates=[_candidate("2")], raw_model_outputs=[r"\boxed{3}"])
    assert l2.source == "L2"
    assert l2.answer == "2"

    l3 = ladder.resolve(raw_model_outputs=["<think>scratch only \\boxed{3}</think>"])
    assert l3.source == "L3"
    assert l3.answer == "3"

    l4 = ladder.resolve(raw_model_outputs=["推导结束。\n最终答案：-1/3"])
    assert l4.source == "L4"
    assert l4.answer == "-1/3"

    l5 = ladder.resolve(raw_model_outputs=[], fallback="<exact answer>")
    assert l5.source == "L5"
    assert l5.answer == "0"
    assert l5.status == "failed"


def test_ladder_skips_rejected_candidate_but_keeps_unverified_answer() -> None:
    result = AnswerLadder().resolve(
        validated_candidates=[_candidate("bad")],
        unverified_candidates=[_candidate("4")],
        validator=lambda value: value == "4",
    )
    assert result.source == "L2"
    assert result.answer == "4"


def test_l2_is_deliverable_even_when_full_validator_rejects_it() -> None:
    result = AnswerLadder().resolve(
        unverified_candidates=[_candidate("4")],
        raw_model_outputs=[r"\boxed{9}"],
        validator=lambda _value: False,
    )
    assert result.source == "L2"
    assert result.answer == "4"


def test_raw_boxed_and_unclosed_think_are_salvageable_before_public_strip() -> None:
    assert extract_final_answer_text("<think>private \\boxed{1}</think>\n答案：2") == "2"
    assert extract_final_answer_text("<think>unfinished\n\\boxed{3}") == "3"
    assert extract_final_answer_text("<think>only private \\boxed{4}</think>") == "4"
    assert extract_final_answer_text("Therefore, \\frac{1}{2}") == r"\frac{1}{2}"
    assert extract_final_answer_text("The result is 5") == "5"


def test_answer_sanitizer_removes_instruction_leaks_and_placeholders() -> None:
    answer, issues = sanitize_final_answer("-1/30. Provide solution text in JSON")
    assert answer == "-1/30"
    assert "instruction_leak_trimmed" in issues

    answer, issues = sanitize_final_answer("<exact answer>")
    assert answer == ""
    assert issues == ["placeholder_leak"]

    answer, issues = sanitize_final_answer("请输出最终答案")
    assert answer == ""
    assert "instruction_leak" in issues


def test_long_non_expression_is_recovered_from_its_answer_tail() -> None:
    long_text = "这是一段不应作为最终答案输出的说明文字。" * 40
    value, issues = enforce_answer_form(long_text + "\n答案：7")
    assert value == "7"
    assert "answer_form_recovered" in issues


def test_degraded_validation_downgrades_schema_failure_in_solver_mode() -> None:
    candidate = SolutionParser().parse(
        '{"final_answer":"2"}',
        candidate_id="degraded",
        role="PrimarySolver",
        answer_type="integer",
        planned_method_family="direct-deduction",
        response_mode="answer_only",
    )
    code, rejected = candidate_response_validation(candidate, allow_degraded=True)
    assert rejected is False
    assert code == "candidate_schema_degraded"
    assert candidate.degraded is True


class _TruncatedRouterText(str):
    finish_reason = "length"


def test_router_uses_real_truncation_and_salvages_top_level_fields() -> None:
    response = _TruncatedRouterText(
        '{"primary_domain":"general-math",'
        '"risk":"low",'
        '"preferred_methods":["direct-deduction"],'
    )
    intent, tier, reason, degradation = parse_router_intent(
        response,
        allowed_domains={"general-math"},
    )
    assert intent.primary_domain == "general-math"
    assert intent.risk == "low"
    assert intent.preferred_methods == ("direct-deduction",)
    assert tier == "salvaged_top_level_fields"
    assert "salvage_top_level_fields" in reason
    assert degradation == "high"


def test_terminalizer_placeholder_falls_back_to_l3_and_marks_failure_path() -> None:
    result = NoThrowTerminalizer().build_result(
        final_response="<exact answer>",
        trace_factory=lambda: [{"event": "run_completed"}],
        metrics_factory=minimal_fallback_metrics,
        provenance={},
        outcome="primary",
        raw_model_outputs=[r"\boxed{7}"],
        fallback_answer="0",
    )
    assert result["final_response"] == "7"
    assert result["run_metrics"]["answer_source"] == "L3"
    assert result["run_metrics"]["answer_source_counts"] == {
        "L1": 0,
        "L2": 0,
        "L3": 1,
        "L4": 0,
        "L5": 0,
    }
    assert result["run_metrics"]["outcome"] == "fallback"


def test_public_projection_marks_placeholder_as_failed() -> None:
    result = build_public_result(
        17,
        {
            "status": "success",
            "final_response": "<exact answer>",
            "trace": [],
        },
    )
    assert result["status"] == "failed"
    assert result["final_response"] == "0"


def test_raw_outputs_are_retained_in_case_context_but_not_required_for_trace() -> None:
    budget = CallBudget(1)
    session = MathSession("s1", "计算 1+1", {}, budget)
    session.raw_model_outputs.append('{"final_answer":"2"}')
    payload = session.to_dict()
    assert payload["raw_model_outputs"] == ['{"final_answer":"2"}']


def test_metrics_emit_all_answer_ladder_levels() -> None:
    metrics = RunMetrics(
        outcome="fallback",
        fallback_used=True,
        answer_source="L4",
        answer_source_counts={"L1": 0, "L2": 0, "L3": 0, "L4": 1, "L5": 0},
    )
    assert set(metrics.to_dict()["answer_source_counts"]) == {
        "L1",
        "L2",
        "L3",
        "L4",
        "L5",
    }


def test_router_malformed_without_truncation_remains_fail_closed() -> None:
    with pytest.raises(ValueError):
        parse_router_intent(
            "this is not a router object",
            allowed_domains={"general-math"},
        )
