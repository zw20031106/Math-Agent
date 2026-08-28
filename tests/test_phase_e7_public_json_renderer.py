from __future__ import annotations

from pathlib import Path

from mathforge.evaluation.debug_artifact import (
    EVALUATION_ARTIFACT_SECTIONS,
    EvaluationArtifact,
    InMemoryEvaluationArtifactSink,
    JsonlEvaluationArtifactSink,
    build_evaluation_artifact,
)
from mathforge.harness.schemas import CandidateSolution, Claim
from mathforge.harness.trace import TRACE_PRIORITY, TraceBuilder
from mathforge.output.deterministic_formatter import (
    DeterministicFormatter,
    WORKED_SOLUTION_OUTPUT_STRATEGY,
    worked_solution_output_strategy,
)
from mathforge.output.public_result import (
    PUBLIC_RESULT_FIELDS,
    PublicContractError,
    build_public_result,
    validate_public_result,
)
from mathforge.output.verified_proof import VerifiedProofRenderer
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.runtime import MathForgeHarness
from tests.fake_client import FakeClient


def _proof_candidate(*, verified: bool = True) -> CandidateSolution:
    state = "semantically_verified" if verified else "unknown"
    status = "verified" if verified else "unverified"
    return CandidateSolution(
        "candidate-1",
        "PrimarySolver",
        "direct-deduction",
        "x=2",
        "expression",
        claims=[
            Claim("premise", "由题设得到 x=1。", status=status, verification_state=state),
            Claim(
                "conclusion",
                "代入方程后得到 x=2。",
                depends_on=["premise"],
                importance="critical",
                status=status,
                verification_state=state,
            ),
        ],
        public_solution_steps=["legacy model text"],
        solution_text="legacy model text",
    )


def test_verified_renderer_uses_dependency_order_and_exact_conclusion():
    rendered = VerifiedProofRenderer().render(_proof_candidate())

    assert rendered.structured is True
    assert rendered.complete is True
    assert rendered.rendered_claim_ids == ("premise", "conclusion")
    assert rendered.text.index("由题设") < rendered.text.index("代入方程")
    assert rendered.text.endswith("x=2")


def test_unverified_proof_is_explicit_legacy_fallback():
    rendered = VerifiedProofRenderer().render(_proof_candidate(verified=False))

    assert rendered.complete is False
    assert rendered.fallback_used is True
    assert "legacy model text" in rendered.text


def test_worked_solution_policy_is_explicit_and_answer_only():
    assert WORKED_SOLUTION_OUTPUT_STRATEGY == "exact_answer"
    assert worked_solution_output_strategy() == "exact_answer"
    assert worked_solution_output_strategy(scorer_contract="public_process") == (
        "verified_derivation_and_exact_answer"
    )
    problem = ProblemParser().parse("计算 1+1 并写出过程。")
    response = DeterministicFormatter().format(
        CandidateSolution(
            "candidate-1",
            "PrimarySolver",
            "direct-deduction",
            "2",
            "integer",
            solution_text="1+1=2，所以答案为 2。",
        ),
        problem,
    )
    assert response == "2"


def test_public_result_has_exactly_four_fields_and_sanitizes_controls():
    result = build_public_result(
        1,
        {
            "status": "success",
            "final_response": "2\x00",
            "trace": [{"step": "plan", "content": "safe\x01"}],
        },
    )

    assert set(result) == PUBLIC_RESULT_FIELDS
    validate_public_result(result)
    assert "\x00" not in result["final_response"]
    assert "\x01" not in str(result["trace"])


def test_public_contract_validator_rejects_top_level_debug_fields():
    try:
        validate_public_result(
            {
                "id": 1,
                "status": "success",
                "final_response": "2",
                "trace": [],
                "run_metrics": {},
            }
        )
    except PublicContractError:
        pass
    else:
        raise AssertionError("debug fields must not enter the public contract")


def test_trace_projection_failure_is_fail_closed_without_mutating_math_result():
    internal = {
        "status": "success",
        "final_response": "7",
        "trace": [{"step": "plan", "content": "missing finalize"}],
        "run_metrics": {"outcome": "primary", "hard_verified": True},
        "evaluation_artifact": {"outcome": "primary"},
    }
    public = build_public_result(1, internal)

    assert public["status"] == "failed"
    assert public["final_response"] == "7"
    assert internal["run_metrics"]["outcome"] == "primary"
    assert internal["evaluation_artifact"]["outcome"] == "primary"


def test_evaluation_artifact_is_separate_and_round_trips(tmp_path: Path):
    artifact = build_evaluation_artifact(
        case_id=1,
        session_id="session-1",
        outcome="primary",
        run_metrics={"model_calls": 2},
        internal_events=[
            {"event": "skills_selected", "skills": ["algebra"]},
            {"event": "run_completed", "outcome": "primary"},
        ],
        candidate_provenance=[_proof_candidate()],
    )
    payload = artifact.to_dict()
    assert set(EVALUATION_ARTIFACT_SECTIONS) <= set(payload)
    assert set(payload) != PUBLIC_RESULT_FIELDS
    assert EvaluationArtifact.from_dict(payload).to_dict() == payload

    memory = InMemoryEvaluationArtifactSink()
    memory.record(payload)
    assert memory.records[0]["session_id"] == "session-1"
    path = tmp_path / "evaluation.jsonl"
    JsonlEvaluationArtifactSink(path).record(payload)
    assert path.read_text(encoding="utf-8").count("\n") == 1


def test_runtime_emits_artifact_without_widening_public_result():
    sink = InMemoryEvaluationArtifactSink()
    internal = MathForgeHarness(FakeClient(), evaluation_sink=sink).solve(
        "1 + 1",
        {"idx": 7},
    )
    public = build_public_result(7, internal)

    assert "evaluation_artifact" in internal
    assert len(sink.records) == 1
    assert set(public) == PUBLIC_RESULT_FIELDS
    assert "evaluation_artifact" not in public


def test_trace_eviction_policy_ranks_model_activity_last():
    assert TRACE_PRIORITY["model_activity"] > TRACE_PRIORITY["repair_history"]
    events: list[dict] = []
    trace = TraceBuilder(events, max_events=1, max_chars=0)
    trace.add("model_activity", calls=[{"role": "PrimarySolver"}])
    trace.add("repair_completed", accepted=True)
    assert events[-1]["event"] == "repair_completed"
