from __future__ import annotations

from dataclasses import replace
import json

from mathforge.benchmark import BenchmarkCase, run_benchmark
from mathforge.config import HarnessConfig
from mathforge.harness.metrics import RunMetrics
from mathforge.harness.schemas import CandidateSolution, Claim, MethodStep, ProblemIR
from mathforge.runtime import MathForgeHarness
from mathforge.tool_prompt_examples import claim_prompt_examples
from mathforge.tools.executor import ToolExecutor
from mathforge.tools.registry import ToolRegistry, ToolResult
from mathforge.verification.arbitration import ArbitrationPolicy
from mathforge.verification.capabilities import (
    ClaimVerificationState,
    VerificationCapability,
)
from mathforge.verification.equivalence import EquivalenceStatus, equivalent_answers
from mathforge.verification.evidence import ClaimEvidenceVerifier, EvidenceLedger
from mathforge.verification.methods import candidate_method_signature
from mathforge.verification.tool_requests import claim_tool_statistics


def test_all_tool_examples_pass_the_same_input_schema_gate_as_runtime():
    registry = ToolRegistry()
    examples = claim_prompt_examples(registry.names(), limit=99)

    assert len(examples) == 9
    assert all(
        registry.validate_arguments(item["tool"], item["host_arguments"]) == []
        for item in examples
    )
    assert registry.validate_arguments(
        "symbolic_equivalence",
        {"left": "x", "unexpected": "x"},
    ) == ["right:missing", "unexpected:unexpected"]


def test_claim_tool_requests_have_reproducible_schema_and_outcome_statistics():
    candidate = CandidateSolution(
        "candidate",
        "PrimarySolver",
        "direct",
        "1",
        "expression",
        claims=[
            Claim(
                "identity",
                "x = x",
                check_type="symbolic_equivalence",
            ),
            Claim(
                "unsafe-density",
                "normalize whatever was intended",
                check_type="density_normalization",
            ),
        ],
    )
    records = ClaimEvidenceVerifier(ToolExecutor()).verify(
        candidate,
        EvidenceLedger(candidates=[candidate]),
        selected_tools=["symbolic_equivalence", "density_normalization"],
        domains={"x": "R"},
    )
    statistics = claim_tool_statistics(records)

    assert statistics == {
        "requests": 2,
        "argument_ready": 1,
        "schema_valid": 1,
        "executed": 1,
        "pass": 1,
        "fail": 0,
        "unknown": 1,
        "error": 0,
        "argument_success_rate": 0.5,
        "schema_success_rate": 0.5,
        "unknown_rate": 0.5,
        "error_rate": 0.0,
    }
    assert records[0].invocation["input_digest"]
    assert records[0].invocation["fatal_eligible"] is True
    assert records[1].payload["request_status"] == "argument_unavailable"


def _hard_result(capability: str) -> ToolResult:
    return ToolResult(
        "test",
        "fail",
        "hard",
        "counterexample",
        {},
        "1",
        capability,
        ClaimVerificationState.SEMANTICALLY_VERIFIED.value,
    )


def test_fatal_gate_requires_an_applicable_capability_and_complete_input():
    mismatched = EvidenceLedger()
    mismatched.record_tool_result(
        candidate_id="candidate",
        claim_id="claim",
        result=_hard_result(VerificationCapability.MATRIX_SHAPE.value),
        claim_kind="equality",
        input_complete=True,
        context_complete=True,
        request_status="ready",
        schema_valid=True,
    )
    applicable = EvidenceLedger()
    applicable.record_tool_result(
        candidate_id="candidate",
        claim_id="claim",
        result=_hard_result(
            VerificationCapability.EQUALITY_SYMBOLIC_UNDER_DOMAIN.value
        ),
        claim_kind="equality",
        input_complete=True,
        context_complete=True,
        request_status="ready",
        schema_valid=True,
    )
    shape_only = EvidenceLedger()
    shape_only.record_tool_result(
        candidate_id="candidate",
        claim_id=None,
        result=_hard_result(VerificationCapability.ANSWER_SHAPE.value),
        claim_kind="answer_shape",
        input_complete=True,
        context_complete=True,
        request_status="ready",
        schema_valid=True,
    )

    assert not mismatched.has_hard_fail("candidate")
    assert applicable.has_hard_fail("candidate")
    assert not shape_only.has_hard_fail("candidate")


def _candidate(identifier: str, answer: str, answer_type: str) -> CandidateSolution:
    return CandidateSolution(
        identifier,
        "PrimarySolver",
        "direct",
        answer,
        answer_type,
    )


def test_equivalent_answer_representations_are_normalized_before_hard_decisions():
    cases = [
        ("fraction", r"\boxed{\frac{2}{4}}", "1/2"),
        ("set", r"\{2, 1\}", "{1,2}"),
        ("vector", r"(0,e^{\pi/2})^T", r"[0,e^{\pi/2}]"),
        ("matrix", r"\begin{pmatrix}1&2\\3&4\end{pmatrix}", "[[1,2],[3,4]]"),
    ]
    for answer_type, left, right in cases:
        problem = ProblemIR(
            raw_problem="compare",
            normalized_problem="compare",
            problem_type="calculation",
            answer_type=answer_type,
        )
        assert equivalent_answers(
            _candidate("left", left, answer_type),
            _candidate("right", right, answer_type),
            problem,
        ) is EquivalenceStatus.EQUIVALENT


class _VerifierUnavailableProofClient:
    def chat(self, *, messages, temperature, max_tokens):
        del temperature, max_tokens
        role = messages[0]["content"]
        if role.startswith("You are VerifierSkeptic"):
            raise TimeoutError("private provider detail")
        return json.dumps(
            {
                "method": "direct",
                "method_steps": [
                    {
                        "step_id": "s1",
                        "kind": "conclusion",
                        "claim_ids": ["identity"],
                        "theorem": "",
                    }
                ],
                "solution_text": "Both sides are the same expression.",
                "public_solution_steps": ["Compare the two identical sides."],
                "final_answer": "QED",
                "assumptions": [],
                "theorems": [],
                "claims": [
                    {
                        "claim_id": "identity",
                        "statement": "x = x",
                        "depends_on": [],
                        "check_type": "symbolic_equivalence",
                        "importance": "critical",
                    }
                ],
                "unresolved_obligations": [],
            }
        )


def test_verifier_unavailability_keeps_best_deterministically_verified_candidate():
    config = HarnessConfig(
        max_model_calls=2,
        model_max_concurrency=1,
        enable_router=False,
        enable_skills=False,
        enable_alternatives=False,
        enable_tools=True,
        enable_evidence=True,
        enable_proof_obligations=True,
        enable_verifier=True,
        enable_memory=False,
        enable_lemma_loop=False,
        enable_rag=False,
        enable_repair=False,
        enable_finalizer=False,
    )
    result = MathForgeHarness(
        _VerifierUnavailableProofClient(),
        config,
    ).solve("Prove that x equals x.", {})
    verifier = next(
        event for event in result["trace"] if event["event"] == "verifier_completed"
    )
    gate = next(
        event for event in result["trace"] if event["event"] == "proof_completion_gate"
    )

    assert verifier["reason"] == "verifier_unavailable"
    assert gate["mode"] == "deterministic_degraded"
    assert gate["accepted"] == ["primary-1"]
    assert result["run_metrics"]["outcome"] == "primary"
    assert "Both sides are the same expression" in result["final_response"]


def test_method_independence_uses_claim_topology_even_with_model_step_labels():
    shared_step = [MethodStep("s1", "conclusion", ["finish"])]
    direct = CandidateSolution(
        "direct",
        "PrimarySolver",
        "renamed",
        "1",
        "integer",
        claims=[
            Claim("base", "base"),
            Claim("finish", "finish", ["base"]),
        ],
        method_steps=shared_step,
    )
    unrelated = replace(
        direct,
        candidate_id="unrelated",
        claims=[
            Claim("other", "other"),
            Claim("finish", "finish", ["other"]),
        ],
    )
    assert candidate_method_signature(direct) != candidate_method_signature(unrelated)
    result = ArbitrationPolicy().select([direct, unrelated], [], {})
    assert all(rank.independent_agreement == 1 for rank in result.ranks)


def test_benchmark_reports_tool_schema_and_repair_rollback_rates():
    metrics = RunMetrics(
        outcome="primary",
        tool_checks=4,
        tool_requests=2,
        tool_argument_ready=1,
        tool_schema_valid=1,
        repair_attempts=2,
        repair_successes=1,
        repair_rollbacks=1,
        repair_evidence_quality_rollbacks=1,
    )
    _, summary = run_benchmark(
        [BenchmarkCase("1", "1", "1", answer_type="integer")],
        lambda *_: {
            "final_response": "Final answer: 1",
            "trace": [],
            "run_metrics": metrics.to_dict(),
        },
    )
    assert summary["tool_argument_success_rate"] == 0.5
    assert summary["tool_schema_success_rate"] == 0.5
    assert summary["repair_success_rate"] == 0.5
    assert summary["repair_rollback_rate"] == 0.5
    assert summary["repair_evidence_quality_rollback_count"] == 1
