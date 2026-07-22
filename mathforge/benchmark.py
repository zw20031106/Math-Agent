from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from time import perf_counter
from typing import Callable

from mathforge.evaluation.scoring import ScoreResult, score_response
from mathforge.harness.fingerprints import request_fingerprint
from mathforge.parsing.problem_parser import ProblemParser


@dataclass(frozen=True)
class BenchmarkCase:
    idx: str
    problem: str
    expected_answer: str | None = None
    subject: str = "unknown"
    problem_type: str = "unknown"
    answer_type: str | None = None
    scorer: str | None = None


@dataclass
class BenchmarkRecord:
    case: BenchmarkCase
    result: dict
    latency_seconds: float
    json_valid: bool
    score: ScoreResult
    request_fingerprint: str


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
                    answer_type=(str(item["answer_type"]) if item.get("answer_type") else None),
                    scorer=(str(item["scorer"]) if item.get("scorer") else None),
                )
            )
    return cases


def run_benchmark(
    cases: list[BenchmarkCase],
    solve: Callable[[str, dict], dict],
    *,
    concurrency: int = 1,
) -> tuple[list[BenchmarkRecord], dict]:
    parser = ProblemParser()

    def run_case(index: int, case: BenchmarkCase) -> BenchmarkRecord:
        nonce = _case_nonce(index, case)
        fingerprint = request_fingerprint(case.problem, nonce)
        started = perf_counter()
        try:
            result = solve(
                case.problem,
                {
                    "idx": case.idx,
                    "benchmark_nonce": nonce,
                },
            )
            if not isinstance(result, dict):
                raise TypeError("solve result must be a JSON object")
            json.dumps(result)
            valid = True
        except Exception as error:
            result = {"final_response": "", "trace": [], "error_type": type(error).__name__}
            valid = False
        answer_type = case.answer_type or parser.parse(case.problem).answer_type
        score = score_response(
            case.expected_answer,
            str(result.get("final_response", "")),
            answer_type=answer_type,
            scorer=case.scorer,
        )
        return BenchmarkRecord(
            case,
            result,
            perf_counter() - started,
            valid,
            score,
            fingerprint,
        )

    records: list[BenchmarkRecord] = []
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        future_by_index = {
            pool.submit(run_case, index, case): index for index, case in enumerate(cases)
        }
        ordered: dict[int, BenchmarkRecord] = {}
        for future in as_completed(future_by_index):
            ordered[future_by_index[future]] = future.result()
        records = [ordered[index] for index in sorted(ordered)]
    return records, summarize(records)


def summarize(records: list[BenchmarkRecord]) -> dict:
    expected = [record for record in records if record.case.expected_answer is not None]
    scored = [record for record in expected if record.score.scored]
    correct = [record for record in scored if _is_correct(record)]
    latencies = sorted(record.latency_seconds for record in records)
    traces = [
        event
        for record in records
        for event in _trace_events(record)
    ]
    costs = [_record_cost(record) for record in records]
    tool_checks = [
        check
        for event in traces
        if event.get("event") == "tool_checks"
        for check in event.get("checks", [])
    ]
    lemma_events = [event for event in traces if event.get("event") == "lemma_loop_completed"]
    repair_events = [event for event in traces if event.get("event") == "repair_completed"]
    session_ids = [session_id for record in records if (session_id := _session_id(record))]
    fingerprints = [_trace_fingerprint(record) for record in records]
    fingerprint_missing = sum(value is None for value in fingerprints)
    fingerprint_mismatches = sum(
        value is not None and value != record.request_fingerprint
        for record, value in zip(records, fingerprints)
    )
    duplicate_sessions = len(session_ids) - len(set(session_ids))
    return {
        "case_count": len(records),
        "expected_count": len(expected),
        "scored_count": len(scored),
        "unscored_count": len(expected) - len(scored),
        "scoring_failure_rate": (
            sum(record.score.error for record in expected) / len(expected) if expected else 0.0
        ),
        "accuracy": len(correct) / len(scored) if scored else None,
        "accuracy_by_subject": _group_accuracy(scored, lambda item: item.case.subject),
        "accuracy_by_problem_type": _group_accuracy(scored, lambda item: item.case.problem_type),
        "average_model_calls": (
            sum(item[0] for item in costs) / len(records) if records else 0.0
        ),
        "average_estimated_tokens": (
            sum(item[1] for item in costs) / len(records) if records else 0.0
        ),
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
            sum(
                any(
                    event.get("event") == "fallback_used"
                    for event in _trace_events(record)
                )
                for record in records
            )
            / len(records)
            if records
            else 0.0
        ),
        "duplicate_session_count": duplicate_sessions,
        "fingerprint_missing_count": fingerprint_missing,
        "fingerprint_mismatch_count": fingerprint_mismatches,
        "concurrency_pollution_count": duplicate_sessions + fingerprint_mismatches,
    }


def _is_correct(record: BenchmarkRecord) -> bool:
    return record.score.scored and record.score.correct is True


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


def _case_nonce(index: int, case: BenchmarkCase) -> str:
    payload = f"{index}\0{case.idx}\0{case.problem}".encode("utf-8")
    return sha256(payload).hexdigest()[:24]


def _record_cost(record: BenchmarkRecord) -> tuple[int, int]:
    trace = _trace_events(record)
    summaries = [
        event
        for event in trace
        if isinstance(event, dict) and event.get("event") == "budget_summary"
    ]
    if summaries:
        return (
            _nonnegative_int(summaries[-1].get("model_calls", 0)),
            _nonnegative_int(summaries[-1].get("estimated_tokens", 0)),
        )
    completed = [
        event
        for event in trace
        if isinstance(event, dict) and event.get("event") == "primary_completed"
    ]
    if completed:
        return (
            _nonnegative_int(completed[-1].get("model_calls", 0)),
            _nonnegative_int(completed[-1].get("estimated_tokens", 0)),
        )
    return 0, 0


def _session_id(record: BenchmarkRecord) -> str | None:
    for event in _trace_events(record):
        if isinstance(event, dict) and event.get("event") == "session_started":
            value = event.get("session_id")
            return str(value) if value else None
    return None


def _trace_fingerprint(record: BenchmarkRecord) -> str | None:
    for event in _trace_events(record):
        if event.get("event") == "session_started":
            value = event.get("request_fingerprint")
            return str(value) if value else None
    return None


def _trace_events(record: BenchmarkRecord) -> list[dict]:
    trace = record.result.get("trace", [])
    if not isinstance(trace, list):
        return []
    return [event for event in trace if isinstance(event, dict)]


def _nonnegative_int(value) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
