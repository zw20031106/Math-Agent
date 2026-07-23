from __future__ import annotations

from mathforge.benchmark import (
    BenchmarkCase,
    benchmark_record_from_dict,
    benchmark_record_to_dict,
    run_benchmark,
    summarize,
)
from mathforge.harness.fingerprints import request_fingerprint


def test_benchmark_reports_accuracy_cost_latency_and_isolation():
    def solve(problem, metadata):
        return {
            "final_response": f"Final answer: {problem}",
            "trace": [
                {
                    "event": "session_started",
                    "session_id": f"s-{metadata['idx']}",
                    "request_fingerprint": request_fingerprint(
                        problem, metadata["benchmark_nonce"]
                    ),
                },
                {"event": "primary_completed", "model_calls": 2, "estimated_tokens": 10},
            ],
        }

    cases = [
        BenchmarkCase("1", "2", "2", "algebra", "calculation"),
        BenchmarkCase("2", "3", "4", "algebra", "calculation"),
    ]
    records, summary = run_benchmark(cases, solve, concurrency=2)
    assert len(records) == 2
    assert summary["accuracy"] == 0.5
    assert summary["average_model_calls"] == 2
    assert summary["average_estimated_tokens"] == 10
    assert summary["json_failure_rate"] == 0
    assert summary["fingerprint_missing_count"] == 0
    assert summary["concurrency_pollution_count"] == 0


def test_empty_benchmark_has_defined_zero_metrics():
    _, summary = run_benchmark([], lambda *_: {})
    assert summary["accuracy"] is None
    assert summary["latency_p95_seconds"] == 0


def test_benchmark_rejects_suffix_match_counterexample():
    records, summary = run_benchmark(
        [BenchmarkCase("1", "Return an expression", "2", answer_type="expression")],
        lambda *_: {"final_response": "Final answer: 42", "trace": []},
    )
    assert records[0].score.correct is False
    assert summary["accuracy"] == 0


def test_fallback_cost_is_included_in_per_case_average():
    def solve(problem, metadata):
        del metadata
        calls, tokens = (1, 10) if problem == "primary" else (3, 30)
        return {
            "final_response": "Final answer: 1",
            "trace": [
                {
                    "event": "budget_summary",
                    "model_calls": calls,
                    "estimated_tokens": tokens,
                    "outcome": problem,
                },
                *([{"event": "fallback_used"}] if problem == "fallback" else []),
            ],
        }

    _, summary = run_benchmark(
        [
            BenchmarkCase("1", "primary", "1", answer_type="integer"),
            BenchmarkCase("2", "fallback", "1", answer_type="integer"),
        ],
        solve,
    )
    assert summary["average_model_calls"] == 2
    assert summary["average_estimated_tokens"] == 20
    assert summary["fallback_rate"] == 0.5


def test_fingerprint_mismatch_is_reported_as_concurrency_pollution():
    _, summary = run_benchmark(
        [BenchmarkCase("1", "1", "1", answer_type="integer")],
        lambda *_: {
            "final_response": "Final answer: 1",
            "trace": [
                {
                    "event": "session_started",
                    "session_id": "s-1",
                    "request_fingerprint": "fingerprint-from-another-request",
                }
            ],
        },
    )
    assert summary["fingerprint_mismatch_count"] == 1
    assert summary["concurrency_pollution_count"] == 1


def test_context_and_tool_failure_metrics_use_explicit_event_reasons():
    def solve(*_):
        return {
            "final_response": "Final answer: 1",
            "trace": [
                {"event": "context_view_built", "role": "PrimarySolver"},
                {
                    "event": "context_budget_infeasible",
                    "role": "VerifierSkeptic",
                },
                {
                    "event": "tool_checks",
                    "checks": [
                        {"status": "unknown", "outcome_reason": "timeout"},
                        {"status": "unknown", "outcome_reason": "domain_unknown"},
                        {"status": "error", "outcome_reason": "error"},
                    ],
                },
            ],
        }

    _, summary = run_benchmark(
        [BenchmarkCase("1", "1", "1", answer_type="integer")],
        solve,
    )
    assert summary["cepc_invariant_failure_rate"] == 0.5
    assert summary["context_view_failure_rate"] == 0.5
    assert summary["tool_timeout_rate"] == 1 / 3
    assert summary["tool_unknown_rate"] == 1 / 3
    assert summary["tool_error_rate"] == 1 / 3


def test_serialized_benchmark_records_recompute_the_same_summary():
    records, summary = run_benchmark(
        [BenchmarkCase("1", "1", "1", "algebra", "calculation", "integer")],
        lambda *_: {
            "final_response": "Final answer: 1",
            "trace": [
                {
                    "event": "budget_summary",
                    "model_calls": 1,
                    "estimated_tokens": 9,
                }
            ],
            "run_metrics": {
                "model_calls": 1,
                "estimated_tokens": 9,
                "outcome": "primary",
            },
        },
    )
    restored = [
        benchmark_record_from_dict(benchmark_record_to_dict(record))
        for record in records
    ]
    assert summarize(restored) == summary
