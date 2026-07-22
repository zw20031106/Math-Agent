from __future__ import annotations

from mathforge.benchmark import BenchmarkCase, run_benchmark


def test_benchmark_reports_accuracy_cost_latency_and_isolation():
    def solve(problem, metadata):
        return {
            "final_response": f"Final answer: {problem}",
            "trace": [
                {"event": "session_started", "session_id": f"s-{metadata['idx']}"},
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
    assert summary["concurrency_pollution_count"] == 0


def test_empty_benchmark_has_defined_zero_metrics():
    _, summary = run_benchmark([], lambda *_: {})
    assert summary["accuracy"] is None
    assert summary["latency_p95_seconds"] == 0
