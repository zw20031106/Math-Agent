from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
import math
import re
from time import perf_counter
from typing import Callable


@dataclass(frozen=True)
class BenchmarkCase:
    idx: str
    problem: str
    expected_answer: str | None = None
    subject: str = "unknown"
    problem_type: str = "unknown"


@dataclass
class BenchmarkRecord:
    case: BenchmarkCase
    result: dict
    latency_seconds: float
    json_valid: bool


def load_jsonl(path) -> list[BenchmarkCase]:
    cases: list[BenchmarkCase] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle):
            if not line.strip():
                continue
            item = json.loads(line)
            cases.append(
                BenchmarkCase(
                    idx=str(item.get("idx", line_number)),
                    problem=str(item["problem"]),
                    expected_answer=(
                        str(item["expected_answer"]) if "expected_answer" in item else None
                    ),
                    subject=str(item.get("subject", "unknown")),
                    problem_type=str(item.get("problem_type", "unknown")),
                )
            )
    return cases


def run_benchmark(
    cases: list[BenchmarkCase],
    solve: Callable[[str, dict], dict],
    *,
    concurrency: int = 1,
) -> tuple[list[BenchmarkRecord], dict]:
    def run_case(case: BenchmarkCase) -> BenchmarkRecord:
        started = perf_counter()
        try:
            result = solve(case.problem, {"idx": case.idx})
            json.dumps(result)
            valid = True
        except Exception as error:
            result = {"final_response": "", "trace": [], "error_type": type(error).__name__}
            valid = False
        return BenchmarkRecord(case, result, perf_counter() - started, valid)

    records: list[BenchmarkRecord] = []
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        future_by_index = {pool.submit(run_case, case): index for index, case in enumerate(cases)}
        ordered: dict[int, BenchmarkRecord] = {}
        for future in as_completed(future_by_index):
            ordered[future_by_index[future]] = future.result()
        records = [ordered[index] for index in sorted(ordered)]
    return records, summarize(records)


def summarize(records: list[BenchmarkRecord]) -> dict:
    scored = [record for record in records if record.case.expected_answer is not None]
    correct = [record for record in scored if _is_correct(record)]
    latencies = sorted(record.latency_seconds for record in records)
    traces = [event for record in records for event in record.result.get("trace", [])]
    calls = [event.get("model_calls", 0) for event in traces if event.get("event") == "primary_completed"]
    tokens = [event.get("estimated_tokens", 0) for event in traces if event.get("event") == "primary_completed"]
    tool_checks = [
        check
        for event in traces
        if event.get("event") == "tool_checks"
        for check in event.get("checks", [])
    ]
    lemma_events = [event for event in traces if event.get("event") == "lemma_loop_completed"]
    repair_events = [event for event in traces if event.get("event") == "repair_completed"]
    session_ids = [
        record.result.get("trace", [{}])[0].get("session_id")
        for record in records
        if record.result.get("trace")
    ]
    return {
        "case_count": len(records),
        "scored_count": len(scored),
        "accuracy": len(correct) / len(scored) if scored else None,
        "accuracy_by_subject": _group_accuracy(scored, lambda item: item.case.subject),
        "accuracy_by_problem_type": _group_accuracy(scored, lambda item: item.case.problem_type),
        "average_model_calls": sum(calls) / len(calls) if calls else 0.0,
        "average_estimated_tokens": sum(tokens) / len(tokens) if tokens else 0.0,
        "latency_p50_seconds": _percentile(latencies, 0.50),
        "latency_p95_seconds": _percentile(latencies, 0.95),
        "json_failure_rate": (
            sum(not record.json_valid for record in records) / len(records) if records else 0.0
        ),
        "tool_timeout_rate": (
            sum(check.get("status") == "unknown" for check in tool_checks) / len(tool_checks)
            if tool_checks
            else 0.0
        ),
        "lemma_error_rate": (
            sum(float(event.get("error_rate", 0.0)) for event in lemma_events) / len(lemma_events)
            if lemma_events
            else 0.0
        ),
        "cepc_invariant_failure_rate": (
            sum(
                bool(event.get("invariant_failure"))
                for event in traces
                if event.get("event") == "compression_validated"
            )
            / max(1, sum(event.get("event") == "compression_validated" for event in traces))
        ),
        "repair_success_rate": (
            sum(not event.get("rolled_back", True) for event in repair_events) / len(repair_events)
            if repair_events
            else 0.0
        ),
        "fallback_rate": (
            sum(any(event.get("event") == "fallback_used" for event in record.result.get("trace", [])) for record in records)
            / len(records)
            if records
            else 0.0
        ),
        "concurrency_pollution_count": len(session_ids) - len(set(session_ids)),
    }


def _is_correct(record: BenchmarkRecord) -> bool:
    expected = _normalize(record.case.expected_answer or "")
    response = str(record.result.get("final_response", ""))
    matches = re.findall(r"(?:final\s*answer|answer|答案)\s*[:：]\s*(.+)$", response, re.I | re.M)
    actual = _normalize(matches[-1] if matches else response)
    return bool(expected) and (actual == expected or actual.endswith(expected))


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).strip(".$").lower()


def _group_accuracy(records: list[BenchmarkRecord], key) -> dict[str, dict]:
    groups: dict[str, list[BenchmarkRecord]] = {}
    for record in records:
        groups.setdefault(key(record), []).append(record)
    return {
        name: {
            "count": len(items),
            "accuracy": sum(_is_correct(item) for item in items) / len(items),
        }
        for name, items in sorted(groups.items())
    }


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, math.ceil(fraction * len(values)) - 1))
    return values[index]
