from __future__ import annotations

from mathforge.benchmark import BenchmarkCase, run_benchmark
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
