from __future__ import annotations

from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from hashlib import sha256
import json
import math
import random
from threading import Event, Lock
from time import perf_counter
from typing import Any, Callable, Mapping

from mathforge.evaluation.scoring import ScoreResult, score_response
from mathforge.evaluation.failure_attribution import (
    aggregate_failure_attribution,
    attribute_case_failure,
)
from mathforge.harness.fingerprints import request_fingerprint
from mathforge.harness.metrics import RunMetrics
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


@dataclass(frozen=True)
class BenchmarkPreflight:
    case_count: int
    expected_count: int
    auto_scored_count: int
    manual_count: int
    invalid_expected_count: int
    auto_score_coverage: float
    invalid_reasons: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_count": self.case_count,
            "expected_count": self.expected_count,
            "auto_scored_count": self.auto_scored_count,
            "manual_count": self.manual_count,
            "invalid_expected_count": self.invalid_expected_count,
            "auto_score_coverage": self.auto_score_coverage,
            "invalid_reasons": dict(self.invalid_reasons),
        }


@dataclass(frozen=True)
class BenchmarkPollution:
    nonce_seen_in_messages: bool | None = None
    foreign_nonce_in_messages: bool = False
    foreign_nonce_in_result: bool = False
    candidate_ownership_mismatch: bool = False
    result_mutated_after_return: bool = False
    probe_error: bool = False

    def to_dict(self) -> dict[str, bool | None]:
        return {
            "nonce_seen_in_messages": self.nonce_seen_in_messages,
            "foreign_nonce_in_messages": self.foreign_nonce_in_messages,
            "foreign_nonce_in_result": self.foreign_nonce_in_result,
            "candidate_ownership_mismatch": self.candidate_ownership_mismatch,
            "result_mutated_after_return": self.result_mutated_after_return,
            "probe_error": self.probe_error,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> BenchmarkPollution:
        return cls(
            nonce_seen_in_messages=_optional_bool(
                payload.get("nonce_seen_in_messages")
            ),
            foreign_nonce_in_messages=bool(
                payload.get("foreign_nonce_in_messages", False)
            ),
            foreign_nonce_in_result=bool(
                payload.get("foreign_nonce_in_result", False)
            ),
            candidate_ownership_mismatch=bool(
                payload.get("candidate_ownership_mismatch", False)
            ),
            result_mutated_after_return=bool(
                payload.get("result_mutated_after_return", False)
            ),
            probe_error=bool(payload.get("probe_error", False)),
        )

    @property
    def contaminated(self) -> bool:
        return (
            self.nonce_seen_in_messages is False
            or self.foreign_nonce_in_messages
            or self.foreign_nonce_in_result
            or self.candidate_ownership_mismatch
            or self.result_mutated_after_return
            or self.probe_error
        )


@dataclass
class BenchmarkRecord:
    case: BenchmarkCase
    result: dict[str, Any]
    latency_seconds: float
    json_valid: bool
    score: ScoreResult
    request_fingerprint: str
    run_metrics: RunMetrics
    pollution: BenchmarkPollution = BenchmarkPollution()
    repetition_index: int = 0
    random_seed: int = 0


PollutionProbe = Callable[[str, tuple[str, ...]], Mapping[str, Any]]


def load_jsonl(path) -> list[BenchmarkCase]:
    cases: list[BenchmarkCase] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle):
            if not line.strip():
                continue
            item = json.loads(line)
            has_expected = "expected_answer" in item
            has_answer = "answer" in item
            if (
                has_expected
                and has_answer
                and str(item["expected_answer"]).strip()
                != str(item["answer"]).strip()
            ):
                raise ValueError(
                    "conflicting expected_answer and answer "
                    f"at JSONL line {line_number + 1}"
                )
            expected = (
                item["expected_answer"]
                if has_expected
                else item["answer"]
                if has_answer
                else None
            )
            cases.append(
                BenchmarkCase(
                    idx=str(item.get("idx", line_number)),
                    problem=str(item["problem"]),
                    expected_answer=(
                        str(expected) if expected is not None else None
                    ),
                    subject=str(item.get("subject", "unknown")),
                    problem_type=str(item.get("problem_type", "unknown")),
                    answer_type=(str(item["answer_type"]) if item.get("answer_type") else None),
                    scorer=(str(item["scorer"]) if item.get("scorer") else None),
                )
            )
    return cases


def preflight_benchmark_cases(
    cases: list[BenchmarkCase],
    *,
    require_expected: bool = True,
    minimum_auto_score_coverage: float = 0.95,
) -> BenchmarkPreflight:
    if not 0.0 <= minimum_auto_score_coverage <= 1.0:
        raise ValueError("minimum auto-score coverage must be in [0, 1]")
    parser = ProblemParser()
    validate_unique_case_ids(cases)
    invalid: dict[str, str] = {}
    expected_count = 0
    auto_scored_count = 0
    manual_count = 0
    for case in cases:
        if case.expected_answer is None or not str(case.expected_answer).strip():
            if require_expected:
                invalid[case.idx] = "missing_expected_answer"
            continue
        expected_count += 1
        parsed_type = case.answer_type or parser.parse(case.problem).answer_type
        probe = score_response(
            case.expected_answer,
            f"Final answer: {case.expected_answer}",
            answer_type=parsed_type,
            scorer=case.scorer,
        )
        if probe.error or probe.reason.startswith("invalid_expected"):
            invalid[case.idx] = probe.reason
        elif probe.scored:
            auto_scored_count += 1
        else:
            manual_count += 1
    denominator = expected_count or len(cases)
    coverage = auto_scored_count / denominator if denominator else 0.0
    result = BenchmarkPreflight(
        case_count=len(cases),
        expected_count=expected_count,
        auto_scored_count=auto_scored_count,
        manual_count=manual_count,
        invalid_expected_count=len(invalid),
        auto_score_coverage=coverage,
        invalid_reasons=invalid,
    )
    if invalid:
        details = ", ".join(
            f"{case_id}:{reason}"
            for case_id, reason in sorted(invalid.items())
        )
        raise ValueError(f"benchmark preflight failed: {details}")
    if coverage < minimum_auto_score_coverage:
        raise ValueError(
            "benchmark auto-score coverage below threshold: "
            f"{coverage:.6f} < {minimum_auto_score_coverage:.6f}"
        )
    return result


def validate_unique_case_ids(cases: list[BenchmarkCase]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for case in cases:
        if case.idx in seen:
            duplicates.add(case.idx)
        seen.add(case.idx)
    if duplicates:
        raise ValueError(
            "duplicate benchmark case IDs: "
            + ", ".join(sorted(duplicates))
        )


def run_benchmark(
    cases: list[BenchmarkCase],
    solve: Callable[[str, dict], dict],
    *,
    concurrency: int = 1,
    repetitions: int = 1,
    seed: int = 0,
    pollution_probe: PollutionProbe | None = None,
    late_mutation_grace_seconds: float = 0.0,
    on_record_completed: Callable[[BenchmarkRecord], None] | None = None,
    should_stop_scheduling: Callable[[], bool] | None = None,
) -> tuple[list[BenchmarkRecord], dict]:
    validate_unique_case_ids(cases)
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    if late_mutation_grace_seconds < 0:
        raise ValueError("late mutation grace must be nonnegative")
    parser = ProblemParser()
    tasks = [
        (
            repeat_index * len(cases) + case_index,
            repeat_index,
            case_index,
            case,
        )
        for repeat_index in range(repetitions)
        for case_index, case in enumerate(cases)
    ]
    raw_results: dict[int, tuple[dict[str, Any], str]] = {}
    raw_results_lock = Lock()
    nonces = {
        ordinal: _case_nonce(case_index, case, repeat_index, seed)
        for ordinal, repeat_index, case_index, case in tasks
    }

    def run_case(
        ordinal: int,
        repeat_index: int,
        case_index: int,
        case: BenchmarkCase,
    ) -> BenchmarkRecord:
        nonce = nonces[ordinal]
        fingerprint = request_fingerprint(case.problem, nonce)
        started = perf_counter()
        try:
            raw_result = solve(
                case.problem,
                {
                    "idx": case.idx,
                    "benchmark_nonce": nonce,
                    "benchmark_repetition": repeat_index,
                    "benchmark_seed": seed,
                },
            )
            if not isinstance(raw_result, dict):
                raise TypeError("solve result must be a JSON object")
            result = _json_copy(raw_result)
            valid = True
        except Exception as error:
            raw_result = {
                "final_response": "",
                "trace": [],
                "error_type": type(error).__name__,
            }
            result = _json_copy(raw_result)
            valid = False
        latency = perf_counter() - started
        with raw_results_lock:
            raw_results[ordinal] = (raw_result, _json_digest(raw_result))
        answer_type = case.answer_type or parser.parse(case.problem).answer_type
        score = score_response(
            case.expected_answer,
            str(result.get("final_response", "")),
            answer_type=answer_type,
            scorer=case.scorer,
        )
        metrics = _metrics_from_result(result, latency)
        return BenchmarkRecord(
            case=case,
            result=result,
            latency_seconds=latency,
            json_valid=valid,
            score=score,
            request_fingerprint=fingerprint,
            run_metrics=metrics,
            repetition_index=repeat_index,
            random_seed=seed,
        )

    ordered: dict[int, BenchmarkRecord] = {}
    max_workers = max(1, concurrency)
    task_iterator = iter(tasks)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_by_index = {}

        def submit_next() -> bool:
            try:
                ordinal, repeat_index, case_index, case = next(task_iterator)
            except StopIteration:
                return False
            future = pool.submit(
                run_case,
                ordinal,
                repeat_index,
                case_index,
                case,
            )
            future_by_index[future] = ordinal
            return True

        for _ in range(max_workers):
            if not submit_next():
                break
        while future_by_index:
            completed, _ = wait(
                tuple(future_by_index),
                return_when=FIRST_COMPLETED,
            )
            for future in sorted(
                completed,
                key=lambda item: future_by_index[item],
            ):
                ordinal = future_by_index.pop(future)
                record = future.result()
                ordered[ordinal] = record
                if on_record_completed is not None:
                    on_record_completed(record)
            if should_stop_scheduling is not None and should_stop_scheduling():
                continue
            while len(future_by_index) < max_workers and submit_next():
                pass
    records = [ordered[index] for index in sorted(ordered)]

    if late_mutation_grace_seconds:
        Event().wait(late_mutation_grace_seconds)
    all_nonces = tuple(nonces[index] for index in sorted(nonces))
    for ordinal, record in enumerate(records):
        nonce = nonces[ordinal]
        raw_result, initial_digest = raw_results[ordinal]
        pollution = BenchmarkPollution(
            foreign_nonce_in_result=_contains_foreign_nonce(
                record.result, nonce, all_nonces
            ),
            result_mutated_after_return=_json_digest(raw_result) != initial_digest,
        )
        if pollution_probe is not None:
            try:
                probe_result = pollution_probe(nonce, all_nonces)
                pollution = replace(
                    pollution,
                    nonce_seen_in_messages=_optional_bool(
                        probe_result.get("nonce_seen_in_messages")
                    ),
                    foreign_nonce_in_messages=bool(
                        probe_result.get("foreign_nonce_in_messages", False)
                    ),
                    candidate_ownership_mismatch=bool(
                        probe_result.get("candidate_ownership_mismatch", False)
                    ),
                )
            except Exception:
                pollution = replace(pollution, probe_error=True)
        record.pollution = pollution
    return records, summarize(records)


def summarize(records: list[BenchmarkRecord]) -> dict:
    expected = [record for record in records if record.case.expected_answer is not None]
    scored = [record for record in expected if record.score.scored]
    correct = [record for record in scored if _is_correct(record)]
    latencies = sorted(record.latency_seconds for record in records)
    metrics = [record.run_metrics for record in records]
    session_ids = [item.session_id for item in metrics if item.session_id]
    fingerprint_missing = sum(not item.request_fingerprint for item in metrics)
    fingerprint_mismatches = sum(
        bool(item.request_fingerprint)
        and item.request_fingerprint != record.request_fingerprint
        for record, item in zip(records, metrics)
    )
    duplicate_sessions = len(session_ids) - len(set(session_ids))
    context_attempts = sum(item.context_view_attempts for item in metrics)
    context_failures = sum(item.context_view_failures for item in metrics)
    tool_checks = sum(item.tool_checks for item in metrics)
    tool_requests = sum(item.tool_requests for item in metrics)
    lemma_checks = sum(item.lemma_checks for item in metrics)
    repair_attempts = sum(item.repair_attempts for item in metrics)
    rag_queries = sum(item.rag_queries for item in metrics)
    seeds = sorted({record.random_seed for record in records})
    repetition_indexes = {record.repetition_index for record in records}
    pollution_records = sum(record.pollution.contaminated for record in records)
    failure_attributions = [attribute_case_failure(record) for record in records]
    return {
        "case_count": len(records),
        "expected_count": len(expected),
        "scored_count": len(scored),
        "unscored_count": len(expected) - len(scored),
        "manual_count": sum(
            record.score.reason == "manual_or_rubric_scoring_required"
            for record in expected
        ),
        "invalid_expected_count": sum(
            record.score.error
            and record.score.reason.startswith("invalid_expected")
            for record in expected
        ),
        "auto_score_coverage": (
            len(scored) / len(expected) if expected else 0.0
        ),
        "score_reason_counts": dict(
            sorted(Counter(record.score.reason for record in expected).items())
        ),
        "repetitions": len(repetition_indexes),
        "random_seed": seeds[0] if len(seeds) == 1 else seeds,
        "scoring_failure_rate": (
            sum(record.score.error for record in expected) / len(expected) if expected else 0.0
        ),
        "accuracy": len(correct) / len(scored) if scored else None,
        "accuracy_wilson_95": _wilson_interval(len(correct), len(scored)),
        "accuracy_bootstrap_95": _bootstrap_accuracy(
            scored,
            seeds[0] if len(seeds) == 1 else 0,
        ),
        "accuracy_by_subject": _group_accuracy(scored, lambda item: item.case.subject),
        "accuracy_by_problem_type": _group_accuracy(scored, lambda item: item.case.problem_type),
        "average_model_calls": (
            sum(item.model_calls for item in metrics) / len(records) if records else 0.0
        ),
        "average_estimated_tokens": (
            sum(item.estimated_tokens for item in metrics) / len(records)
            if records
            else 0.0
        ),
        "average_prompt_tokens": (
            sum(item.prompt_tokens for item in metrics) / len(records)
            if records
            else 0.0
        ),
        "average_official_prompt_tokens": (
            sum(item.official_prompt_tokens for item in metrics) / len(records)
            if records
            else 0.0
        ),
        "average_fallback_prompt_tokens": (
            sum(item.fallback_prompt_tokens for item in metrics) / len(records)
            if records
            else 0.0
        ),
        "average_requested_output_tokens": (
            sum(item.requested_output_tokens for item in metrics) / len(records)
            if records
            else 0.0
        ),
        "average_observed_output_tokens": (
            sum(item.observed_output_tokens for item in metrics) / len(records)
            if records
            else 0.0
        ),
        "average_output_chars": (
            sum(item.output_chars for item in metrics) / len(records)
            if records
            else 0.0
        ),
        "model_call_timeout_count": sum(
            item.model_call_timeout_count for item in metrics
        ),
        "transport_attempt_count": sum(
            item.transport_attempts for item in metrics
        ),
        "model_call_failure_count": sum(
            item.model_call_failure_count for item in metrics
        ),
        "model_response_rejection_count": sum(
            item.model_response_rejection_count for item in metrics
        ),
        "per_case_wall_clock_timeout_count": sum(
            item.per_case_wall_clock_timeout_count for item in metrics
        ),
        "timeout_rate": (
            sum(item.outcome == "timeout" for item in metrics) / len(records)
            if records
            else 0.0
        ),
        "latency_p50_seconds": _percentile(latencies, 0.50),
        "latency_p95_seconds": _percentile(latencies, 0.95),
        "json_failure_rate": (
            sum(not record.json_valid for record in records) / len(records)
            if records
            else 0.0
        ),
        "tool_timeout_rate": (
            sum(item.tool_timeouts for item in metrics) / tool_checks
            if tool_checks
            else 0.0
        ),
        "tool_argument_success_rate": (
            sum(item.tool_argument_ready for item in metrics) / tool_requests
            if tool_requests
            else 0.0
        ),
        "tool_schema_success_rate": (
            sum(item.tool_schema_valid for item in metrics) / tool_requests
            if tool_requests
            else 0.0
        ),
        "tool_unknown_rate": (
            sum(item.tool_unknowns for item in metrics) / tool_checks
            if tool_checks
            else 0.0
        ),
        "tool_error_rate": (
            sum(item.tool_errors for item in metrics) / tool_checks
            if tool_checks
            else 0.0
        ),
        "lemma_error_rate": (
            sum(item.lemma_errors for item in metrics) / lemma_checks
            if lemma_checks
            else 0.0
        ),
        "cepc_invariant_failure_rate": (
            context_failures / context_attempts if context_attempts else 0.0
        ),
        "context_view_failure_rate": (
            context_failures / context_attempts if context_attempts else 0.0
        ),
        "repair_success_rate": (
            sum(item.repair_successes for item in metrics) / repair_attempts
            if repair_attempts
            else 0.0
        ),
        "repair_rollback_rate": (
            sum(item.repair_rollbacks for item in metrics) / repair_attempts
            if repair_attempts
            else 0.0
        ),
        "repair_evidence_quality_rollback_count": sum(
            item.repair_evidence_quality_rollbacks for item in metrics
        ),
        "rag_hit_rate": (
            sum(item.rag_hits for item in metrics) / rag_queries
            if rag_queries
            else 0.0
        ),
        "fallback_rate": (
            sum(item.fallback_used for item in metrics) / len(records)
            if records
            else 0.0
        ),
        "error_code_counts": _error_code_counts(metrics),
        "duplicate_session_count": duplicate_sessions,
        "fingerprint_missing_count": fingerprint_missing,
        "fingerprint_mismatch_count": fingerprint_mismatches,
        "nonce_probe_missing_count": sum(
            record.pollution.nonce_seen_in_messages is None for record in records
        ),
        "nonce_missing_from_messages_count": sum(
            record.pollution.nonce_seen_in_messages is False for record in records
        ),
        "foreign_nonce_in_messages_count": sum(
            record.pollution.foreign_nonce_in_messages for record in records
        ),
        "foreign_nonce_in_result_count": sum(
            record.pollution.foreign_nonce_in_result for record in records
        ),
        "candidate_ownership_mismatch_count": sum(
            record.pollution.candidate_ownership_mismatch for record in records
        ),
        "result_mutation_count": sum(
            record.pollution.result_mutated_after_return for record in records
        ),
        "pollution_probe_error_count": sum(
            record.pollution.probe_error for record in records
        ),
        "concurrency_pollution_count": (
            duplicate_sessions + fingerprint_mismatches + pollution_records
        ),
        "failure_attribution": aggregate_failure_attribution(
            failure_attributions,
            case_count=len(records),
        ),
    }


def paired_significance(
    treatment: list[BenchmarkRecord],
    control: list[BenchmarkRecord],
) -> dict[str, int | float]:
    treatment_by_key = {
        (record.case.idx, record.repetition_index): record for record in treatment
    }
    control_by_key = {
        (record.case.idx, record.repetition_index): record for record in control
    }
    pairs = [
        (treatment_by_key[key], control_by_key[key])
        for key in sorted(set(treatment_by_key) & set(control_by_key))
        if treatment_by_key[key].score.scored and control_by_key[key].score.scored
    ]
    wins = sum(_is_correct(left) and not _is_correct(right) for left, right in pairs)
    losses = sum(not _is_correct(left) and _is_correct(right) for left, right in pairs)
    ties = len(pairs) - wins - losses
    discordant = wins + losses
    p_value = _two_sided_binomial_p_value(wins, losses)
    return {
        "pair_count": len(pairs),
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "accuracy_difference": (
            (wins - losses) / len(pairs) if pairs else 0.0
        ),
        "discordant_count": discordant,
        "p_value": p_value,
    }


def benchmark_record_to_dict(record: BenchmarkRecord) -> dict:
    return {
        "case": {
            "idx": record.case.idx,
            "problem": record.case.problem,
            "expected_answer": record.case.expected_answer,
            "subject": record.case.subject,
            "problem_type": record.case.problem_type,
            "answer_type": record.case.answer_type,
            "scorer": record.case.scorer,
        },
        "result": {
            "final_response": record.result.get("final_response", ""),
            "trace": record.result.get("trace", []),
            "run_metrics": record.result.get("run_metrics", {}),
            "provenance": record.result.get("provenance", {}),
        },
        "latency_seconds": record.latency_seconds,
        "json_valid": record.json_valid,
        "score": record.score.to_dict(),
        "failure_attribution": attribute_case_failure(record).to_dict(),
        "request_fingerprint": record.request_fingerprint,
        "run_metrics": record.run_metrics.to_dict(),
        "pollution": record.pollution.to_dict(),
        "repetition_index": record.repetition_index,
        "random_seed": record.random_seed,
    }


def benchmark_record_from_dict(payload: dict) -> BenchmarkRecord:
    case_payload = dict(payload["case"])
    score_payload = dict(payload["score"])
    result = dict(payload["result"])
    metrics_payload = payload.get("run_metrics", result.get("run_metrics", {}))
    metrics = _metrics_from_payload(metrics_payload, result, float(payload["latency_seconds"]))
    return BenchmarkRecord(
        case=BenchmarkCase(
            idx=str(case_payload["idx"]),
            problem=str(case_payload["problem"]),
            expected_answer=case_payload.get("expected_answer"),
            subject=str(case_payload.get("subject", "unknown")),
            problem_type=str(case_payload.get("problem_type", "unknown")),
            answer_type=case_payload.get("answer_type"),
            scorer=case_payload.get("scorer"),
        ),
        result=result,
        latency_seconds=float(payload["latency_seconds"]),
        json_valid=bool(payload["json_valid"]),
        score=ScoreResult(**score_payload),
        request_fingerprint=str(payload["request_fingerprint"]),
        run_metrics=metrics,
        pollution=BenchmarkPollution.from_dict(payload.get("pollution", {})),
        repetition_index=int(payload.get("repetition_index", 0)),
        random_seed=int(payload.get("random_seed", 0)),
    )


def _metrics_from_result(result: dict[str, Any], latency: float) -> RunMetrics:
    return _metrics_from_payload(result.get("run_metrics", {}), result, latency)


def _metrics_from_payload(
    payload: Any,
    result: dict[str, Any],
    latency: float,
) -> RunMetrics:
    if isinstance(payload, dict) and payload.get("schema_version") == RunMetrics.SCHEMA_VERSION:
        return RunMetrics.from_dict(payload)
    trace = _trace_events(result)
    session_id = _first_event_value(trace, "session_started", "session_id")
    fingerprint = _first_event_value(
        trace, "session_started", "request_fingerprint"
    )
    budget_summary = _last_event(trace, "budget_summary")
    primary_summary = _last_event(trace, "primary_completed")
    cost_source = payload if isinstance(payload, dict) and payload else budget_summary
    if not cost_source:
        cost_source = primary_summary
    context_successes = sum(
        event.get("event") == "context_view_built" for event in trace
    )
    context_failures = sum(
        event.get("event") == "context_budget_infeasible" for event in trace
    )
    checks = [
        check
        for event in trace
        if event.get("event") == "tool_checks"
        for check in event.get("checks", [])
        if isinstance(check, dict)
    ]
    repairs = [event for event in trace if event.get("event") == "repair_completed"]
    lemma_events = [
        event for event in trace if event.get("event") == "lemma_loop_completed"
    ]
    retrievals = [
        event for event in trace if event.get("event") == "retrieval_completed"
    ]
    legacy = payload if isinstance(payload, dict) else {}
    terminal = _last_event(trace, "run_completed")
    outcome = str(
        legacy.get(
            "outcome",
            terminal.get(
                "outcome",
                "error"
                if result.get("error_type")
                else "fallback"
                if _last_event(trace, "fallback_used")
                else "primary",
            ),
        )
    )
    if outcome not in {"primary", "fallback", "error", "timeout"}:
        outcome = "error"
    return RunMetrics(
        session_id=str(legacy.get("session_id", session_id or "")),
        request_fingerprint=str(
            legacy.get("request_fingerprint", fingerprint or "")
        ),
        model_calls=_nonnegative_int(cost_source.get("model_calls", 0)),
        estimated_tokens=_nonnegative_int(
            cost_source.get("estimated_tokens", 0)
        ),
        prompt_tokens=_nonnegative_int(
            legacy.get("prompt_tokens", cost_source.get("prompt_tokens", 0))
        ),
        official_prompt_tokens=_nonnegative_int(
            legacy.get(
                "official_prompt_tokens",
                cost_source.get("official_prompt_tokens", 0),
            )
        ),
        fallback_prompt_tokens=_nonnegative_int(
            legacy.get(
                "fallback_prompt_tokens",
                cost_source.get("fallback_prompt_tokens", 0),
            )
        ),
        requested_output_tokens=_nonnegative_int(
            legacy.get(
                "requested_output_tokens",
                cost_source.get("requested_output_tokens", 0),
            )
        ),
        observed_output_tokens=_nonnegative_int(
            legacy.get(
                "observed_output_tokens",
                cost_source.get("observed_output_tokens", 0),
            )
        ),
        output_chars=_nonnegative_int(
            legacy.get("output_chars", cost_source.get("output_chars", 0))
        ),
        model_call_timeout_count=_nonnegative_int(
            legacy.get(
                "model_call_timeout_count",
                cost_source.get("model_call_timeout_count", 0),
            )
        ),
        transport_attempts=_nonnegative_int(
            legacy.get(
                "transport_attempts",
                cost_source.get("transport_attempts", 0),
            )
        ),
        model_call_failure_count=_nonnegative_int(
            legacy.get(
                "model_call_failure_count",
                cost_source.get("model_call_failure_count", 0),
            )
        ),
        model_response_rejection_count=_nonnegative_int(
            legacy.get(
                "model_response_rejection_count",
                cost_source.get("model_response_rejection_count", 0),
            )
        ),
        per_case_wall_clock_timeout_count=_nonnegative_int(
            legacy.get(
                "per_case_wall_clock_timeout_count",
                int(outcome == "timeout"),
            )
        ),
        final_response_tokens=_nonnegative_int(
            legacy.get(
                "final_response_tokens",
                cost_source.get("final_response_tokens", 0),
            )
        ),
        context_window_tokens=_nonnegative_int(
            legacy.get(
                "context_window_tokens",
                cost_source.get("model_context_window_tokens", 0),
            )
        ),
        safety_margin_tokens=_nonnegative_int(
            legacy.get(
                "safety_margin_tokens",
                cost_source.get("context_safety_margin_tokens", 0),
            )
        ),
        model_call_elapsed_seconds=_nonnegative_float(
            legacy.get(
                "model_call_elapsed_seconds",
                cost_source.get("model_call_elapsed_seconds", 0.0),
            )
        ),
        token_limit_mode=str(
            legacy.get(
                "token_limit_mode",
                cost_source.get("token_limit_mode", ""),
            )
        ),
        final_response_counting_mode=str(
            legacy.get(
                "final_response_counting_mode",
                cost_source.get("final_response_counting_mode", ""),
            )
        ),
        deadline_phase=str(
            legacy.get(
                "deadline_phase",
                cost_source.get("deadline_phase", ""),
            )
        ),
        claims=_nonnegative_int(legacy.get("claims", 0)),
        tool_calls=_nonnegative_int(legacy.get("tool_calls", 0)),
        isolated_tool_calls=_nonnegative_int(
            legacy.get("isolated_tool_calls", 0)
        ),
        tool_seconds=_nonnegative_float(legacy.get("tool_seconds", 0.0)),
        evidence_records=_nonnegative_int(
            legacy.get("evidence_records", 0)
        ),
        prompt_chars=_nonnegative_int(legacy.get("prompt_chars", 0)),
        elapsed_seconds=_nonnegative_float(
            legacy.get("elapsed_seconds", latency)
        ),
        outcome=outcome,
        final_phase=str(legacy.get("final_phase", "")),
        error_code=str(legacy.get("error_code", "")),
        fallback_used=bool(
            legacy.get("fallback_used", outcome == "fallback")
        ),
        context_view_attempts=_nonnegative_int(
            legacy.get(
                "context_view_attempts",
                context_successes + context_failures,
            )
        ),
        context_view_failures=_nonnegative_int(
            legacy.get("context_view_failures", context_failures)
        ),
        tool_checks=_nonnegative_int(legacy.get("tool_checks", len(checks))),
        tool_requests=_nonnegative_int(
            legacy.get(
                "tool_requests",
                sum(check.get("claim_id") is not None for check in checks),
            )
        ),
        tool_argument_ready=_nonnegative_int(
            legacy.get(
                "tool_argument_ready",
                sum(
                    check.get("claim_id") is not None
                    and check.get("request_status") == "ready"
                    for check in checks
                ),
            )
        ),
        tool_schema_valid=_nonnegative_int(
            legacy.get(
                "tool_schema_valid",
                sum(
                    check.get("claim_id") is not None
                    and check.get("schema_valid") is True
                    for check in checks
                ),
            )
        ),
        tool_timeouts=_nonnegative_int(
            legacy.get(
                "tool_timeouts",
                sum(check.get("outcome_reason") == "timeout" for check in checks),
            )
        ),
        tool_unknowns=_nonnegative_int(
            legacy.get(
                "tool_unknowns",
                sum(
                    check.get("status") == "unknown"
                    and check.get("outcome_reason") != "timeout"
                    for check in checks
                ),
            )
        ),
        tool_errors=_nonnegative_int(
            legacy.get(
                "tool_errors",
                sum(
                    check.get("status") == "error"
                    or check.get("outcome_reason") == "error"
                    for check in checks
                ),
            )
        ),
        lemma_checks=_nonnegative_int(
            legacy.get(
                "lemma_checks",
                sum(_nonnegative_int(event.get("checked_count", 0)) for event in lemma_events),
            )
        ),
        lemma_errors=_nonnegative_int(
            legacy.get(
                "lemma_errors",
                sum(_nonnegative_int(event.get("error_count", 0)) for event in lemma_events),
            )
        ),
        repair_attempts=_nonnegative_int(
            legacy.get("repair_attempts", len(repairs))
        ),
        repair_successes=_nonnegative_int(
            legacy.get(
                "repair_successes",
                sum(not event.get("rolled_back", True) for event in repairs),
            )
        ),
        repair_rollbacks=_nonnegative_int(
            legacy.get(
                "repair_rollbacks",
                sum(bool(event.get("rolled_back", True)) for event in repairs),
            )
        ),
        repair_evidence_quality_rollbacks=_nonnegative_int(
            legacy.get(
                "repair_evidence_quality_rollbacks",
                sum(
                    event.get("reason") == "evidence_quality_decreased"
                    for event in repairs
                ),
            )
        ),
        rag_queries=_nonnegative_int(
            legacy.get("rag_queries", len(retrievals))
        ),
        rag_hits=_nonnegative_int(
            legacy.get(
                "rag_hits",
                sum(
                    bool(event.get("card_ids", []))
                    for event in retrievals
                    if isinstance(event.get("card_ids", []), list)
                ),
            )
        ),
    )


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


def _wilson_interval(successes: int, total: int) -> dict[str, float] | None:
    if total == 0:
        return None
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / total
            + z * z / (4 * total * total)
        )
        / denominator
    )
    return {"lower": max(0.0, center - margin), "upper": min(1.0, center + margin)}


def _bootstrap_accuracy(
    records: list[BenchmarkRecord],
    seed: int,
    samples: int = 1000,
) -> dict[str, float] | None:
    if not records:
        return None
    values = [1.0 if _is_correct(record) else 0.0 for record in records]
    generator = random.Random(seed)
    estimates = sorted(
        sum(generator.choice(values) for _ in values) / len(values)
        for _ in range(samples)
    )
    return {
        "lower": estimates[math.floor(0.025 * (samples - 1))],
        "upper": estimates[math.ceil(0.975 * (samples - 1))],
    }


def _two_sided_binomial_p_value(wins: int, losses: int) -> float:
    total = wins + losses
    if total == 0:
        return 1.0
    tail = min(wins, losses)
    probability = sum(
        math.comb(total, value) for value in range(tail + 1)
    ) / (2**total)
    return min(1.0, 2 * probability)


def _case_nonce(
    index: int,
    case: BenchmarkCase,
    repetition_index: int = 0,
    seed: int = 0,
) -> str:
    payload = (
        f"{seed}\0{repetition_index}\0{index}\0{case.idx}\0{case.problem}"
    ).encode("utf-8")
    return sha256(payload).hexdigest()[:24]


def _trace_events(result: dict[str, Any]) -> list[dict[str, Any]]:
    trace = result.get("trace", [])
    if not isinstance(trace, list):
        return []
    return [event for event in trace if isinstance(event, dict)]


def _last_event(events: list[dict[str, Any]], name: str) -> dict[str, Any]:
    matches = [event for event in events if event.get("event") == name]
    return matches[-1] if matches else {}


def _first_event_value(
    events: list[dict[str, Any]],
    event_name: str,
    field_name: str,
) -> str | None:
    for event in events:
        if event.get("event") == event_name and event.get(field_name):
            return str(event[field_name])
    return None


def _contains_foreign_nonce(
    result: dict[str, Any],
    own_nonce: str,
    all_nonces: tuple[str, ...],
) -> bool:
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
    return any(nonce != own_nonce and nonce in serialized for nonce in all_nonces)


def _json_copy(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _json_digest(value: dict[str, Any]) -> str:
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        serialized = repr(value)
    return sha256(serialized.encode("utf-8", errors="replace")).hexdigest()


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _nonnegative_float(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _error_code_counts(metrics: list[RunMetrics]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in metrics:
        if item.error_code:
            counts[item.error_code] = counts.get(item.error_code, 0) + 1
    return dict(sorted(counts.items()))
