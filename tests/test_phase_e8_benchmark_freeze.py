from __future__ import annotations

import json

from mathforge.benchmark import (
    BenchmarkCase,
    load_jsonl,
    preflight_benchmark_cases,
    run_benchmark,
)
from mathforge.evaluation.e8 import (
    E8_METRIC_NAMES,
    evaluate_freeze_gate,
    summarize_ablation_arms,
    summarize_e8,
    validate_benchmark_suite,
    validate_paired_ablation,
)


def _records(repetition_count: int = 3):
    cases = [
        BenchmarkCase("a", "1", "1", "algebra", "calculation", "integer"),
        BenchmarkCase("b", "2", "2", "algebra", "calculation", "integer"),
    ]

    def solve(problem, metadata):
        return {
            "final_response": problem,
            "trace": [
                {
                    "event": "route_planned",
                    "plan_id": "plan-1",
                    "router_source": "rules",
                    "risk_level": "medium",
                    "primary_subject": "algebra",
                },
                {
                    "event": "candidate_fanout_completed",
                    "completed": ["candidate-1", "candidate-2"],
                },
                {"event": "candidate_generated", "candidate_id": "candidate-1", "method": "direct"},
                {"event": "candidate_generated", "candidate_id": "candidate-2", "method": "independent"},
                {"event": "peer_review_completed", "status": "completed"},
                {"event": "final_audit_completed", "status": "completed", "complete": True},
                {
                    "event": "verification_closure_recomputed",
                    "closures": {"candidate-1": {"complete": True}},
                },
                {"event": "candidate_selected", "candidate_id": "candidate-1"},
            ],
            "run_metrics": {
                "schema_version": "1.5",
                "session_id": f"session-{metadata['idx']}",
                "request_fingerprint": "fingerprint",
                "model_calls": 2,
                "estimated_tokens": 10,
                "prompt_tokens": 0,
                "prompt_component_tokens": {
                    "contract_tokens": 0,
                    "runtime_protocol_tokens": 0,
                    "skill_tokens": 0,
                    "state_tokens": 0,
                    "problem_tokens": 0,
                    "schema_tokens": 0,
                },
                "official_prompt_tokens": 0,
                "fallback_prompt_tokens": 0,
                "requested_output_tokens": 0,
                "observed_output_tokens": 0,
                "output_chars": 1,
                "model_call_timeout_count": 0,
                "model_queue_timeout_count": 0,
                "model_admission_rejection_count": 0,
                "transport_attempts": 2,
                "model_call_failure_count": 0,
                "model_response_rejection_count": 0,
                "background_tail_started": 0,
                "background_tail_active": 0,
                "background_tail_completed": 0,
                "provider_active_tails": 0,
                "provider_peak_tails": 0,
                "provider_circuit_trips": 0,
                "provider_fast_failures": 0,
                "per_case_wall_clock_timeout_count": 0,
                "final_response_tokens": 1,
                "context_window_tokens": 262144,
                "safety_margin_tokens": 8192,
                "model_call_elapsed_seconds": 0.1,
                "model_queue_wait_seconds": 0.0,
                "model_execution_seconds": 0.1,
                "provider_health_state": "healthy",
                "token_limit_mode": "",
                "final_response_counting_mode": "",
                "deadline_phase": "active",
                "claims": 0,
                "tool_calls": 0,
                "isolated_tool_calls": 0,
                "tool_seconds": 0.0,
                "evidence_records": 0,
                "prompt_chars": 0,
                "elapsed_seconds": 0.1,
                "outcome": "primary",
                "final_phase": "completed",
                "error_code": "",
                "error_class": "",
                "fallback_used": False,
                "terminalizer_failed_steps": [],
                "context_view_attempts": 0,
                "context_view_failures": 0,
                "tool_checks": 0,
                "tool_requests": 0,
                "tool_argument_ready": 0,
                "tool_schema_valid": 0,
                "tool_timeouts": 0,
                "tool_unknowns": 0,
                "tool_errors": 0,
                "lemma_checks": 0,
                "lemma_errors": 0,
                "repair_attempts": 0,
                "repair_successes": 0,
                "repair_rollbacks": 0,
                "repair_evidence_quality_rollbacks": 0,
                "rag_queries": 0,
                "rag_hits": 0,
            },
        }

    records = []
    for repetition in range(repetition_count):
        current, _ = run_benchmark(cases, solve, seed=42)
        records.extend(
            record.__class__(
                **{
                    **record.__dict__,
                    "repetition_index": repetition,
                }
            )
            for record in current
        )
    return records


def test_loader_accepts_official_json_array(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps([{"id": 7, "problem": "1+1", "answer": "2"}]),
        encoding="utf-8",
    )
    cases = load_jsonl(path)
    assert cases[0].idx == "7"
    assert cases[0].expected_answer == "2"


def test_preflight_can_explicitly_run_unscorable_boundary_cases():
    cases = [
        BenchmarkCase("latex", "x", r"\frac13", answer_type="expression"),
    ]
    report = preflight_benchmark_cases(
        cases,
        allow_invalid_expected=True,
        minimum_auto_score_coverage=0.0,
    )
    assert report.invalid_expected_count == 1
    assert report.relaxed_invalid_expected is True


def test_benchmark_suite_contracts_cover_required_shapes():
    b1 = [BenchmarkCase(str(i), "1", "1", problem_type="protocol_canary") for i in range(8)]
    assert validate_benchmark_suite("B1", b1).valid
    b2 = [
        BenchmarkCase(name, "1", "1", problem_type=name, answer_type="exact")
        for name in ("calculation", "proof", "derivation", "multiple_choice", "fill_blank", "mixed")
    ]
    assert validate_benchmark_suite("B2", b2).valid
    b3 = [
        BenchmarkCase(str(i), "1", "1", problem_type=f"failure {tag}")
        for i, tag in enumerate(
            (
                "truncation",
                "ambiguity",
                "wrong_lemma",
                "counterexample",
                "repair",
                "rollback",
                "final_audit",
                "long_horizon",
                "domain_tool_boundary",
            )
        )
    ]
    assert validate_benchmark_suite("B3", b3).valid


def test_e8_metrics_have_all_required_names_and_ablation_is_interleaved():
    records = _records()
    metrics = summarize_e8(records)
    assert set(E8_METRIC_NAMES) <= set(metrics)
    assert metrics["overall_accuracy"] == 1.0
    rows = {
        "V0": [
            {"case_id": record.case.idx, "repetition_index": record.repetition_index, "run_metrics": {"provider_health_state": "healthy"}}
            for record in records
        ],
        "V1": [
            {"case_id": record.case.idx, "repetition_index": record.repetition_index, "run_metrics": {"provider_health_state": "healthy"}}
            for record in records
        ],
    }
    validation = validate_paired_ablation(
        "verification",
        rows,
        execution_order=("V0", "V1", "V0", "V1"),
    )
    assert validation.valid
    report = summarize_ablation_arms(
        "verification",
        {"V0": records, "V1": records},
        execution_order=("V0", "V1", "V0", "V1"),
    )
    assert report["validation"]["valid"] is True
    grouped = validate_paired_ablation(
        "verification",
        rows,
        execution_order=("V0", "V0", "V1", "V1"),
    )
    assert grouped.valid is False
    assert grouped.interleaved is False


def test_independent_candidate_metric_never_promotes_correlated_agreement():
    records = _records(1)
    records[0].result["trace"].extend(
        [
            {
                "event": "candidate_generated",
                "candidate_id": "candidate-3",
                "branch_id": "branch-3",
                "model_identity": "intern-s2-preview-397b",
                "independent_model_call": True,
            },
            {
                "event": "candidate_generated",
                "candidate_id": "candidate-4",
                "branch_id": "branch-4",
                "model_identity": "intern-s2-preview-397b",
                "independent_model_call": True,
            },
        ]
    )
    assert summarize_e8(records)["independent_candidate_rate"] == 0.0


def test_freeze_gate_is_fail_closed_until_all_evidence_is_present():
    blocked = evaluate_freeze_gate(
        engineering={"compileall": True, "pytest": True},
        architecture={"model_call_graph_mapping_rate": 1.0},
        summary={"overall_accuracy": 1.0, "zero_candidate_rate": 0.0, "fallback_rate": 0.0, "format_caused_success_wrong": 0},
        human_review=False,
    )
    assert blocked.eligible is False
    assert "human mathematical review is incomplete" in blocked.blockers
