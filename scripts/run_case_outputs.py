from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
import platform
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from threading import Event, Lock, Thread
from time import perf_counter, sleep
from typing import Any, Callable
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm_client import InternChatClient  # noqa: E402
from mathforge.agents.router_planner import RouterRuleEngine  # noqa: E402
from mathforge.agents.solver import (  # noqa: E402
    PrimarySolver,
    SolverExecutor,
    SolverRequest,
)
from mathforge.benchmark import (  # noqa: E402
    BenchmarkRecord,
    load_jsonl,
    preflight_benchmark_cases,
    run_benchmark,
    summarize,
)
from mathforge.evaluation.scoring import score_response  # noqa: E402
from mathforge.harness.orchestration import candidate_trace_payload  # noqa: E402
from mathforge.harness.budget import CallBudget  # noqa: E402
from mathforge.harness.errors import (  # noqa: E402
    ModelResponseError,
    ModelTransportError,
)
from mathforge.harness.fingerprints import request_fingerprint  # noqa: E402
from mathforge.harness.metrics import RunMetrics  # noqa: E402
from mathforge.harness.model_policy import (  # noqa: E402
    PROVIDER_HTTP_TIMEOUT_SECONDS,
)
from mathforge.harness.provider import (  # noqa: E402
    ModelCallGate,
    OfficialClientProvider,
)
from mathforge.harness.trace import TraceBuilder  # noqa: E402
from mathforge.harness.cancellation import CancellationToken  # noqa: E402
from mathforge.harness.trace_journal import TraceJournalFactory  # noqa: E402
from mathforge.harness.transport import (  # noqa: E402
    ObservedModelResponse,
    RETRYABLE_TRANSPORT_FAILURE_CODES,
    classify_transport_failure,
    transport_attempts,
)
from mathforge.model_identity import (  # noqa: E402
    EXACT_INTERN_MODEL,
    exact_model_identity,
)
from mathforge.output.public_result import build_public_result  # noqa: E402
from mathforge.output.judge_trace import (  # noqa: E402
    JUDGE_TRACE_SCHEMA_VERSION,
)
from mathforge.output.deterministic_formatter import (  # noqa: E402
    DeterministicFormatter,
)
from mathforge.parsing.problem_parser import ProblemParser  # noqa: E402
from mathforge.parsing.solution_parser import SolutionParser  # noqa: E402
from mathforge.runtime import MathForgeHarness  # noqa: E402
from scripts.run_benchmark import load_benchmark_config  # noqa: E402


PER_CASE_WALL_CLOCK_SECONDS = 1200.0
RESULT_SERIALIZATION_RESERVE_SECONDS = 50.0
RUN_MANIFEST_SCHEMA_VERSION = "1.3"
COMPATIBLE_RUN_MANIFEST_SCHEMA_VERSIONS = frozenset({"1.1", "1.2", "1.3"})
RUN_MANIFEST_FILENAME = "run_manifest.json"
MODEL_PREFLIGHT_SCHEMA_VERSION = "1.0"
MODEL_PREFLIGHT_L1_MAX_TOKENS = 4096
MODEL_PREFLIGHT_MAX_TOKENS = 2048
MODEL_FAST_FAILURE_ATTEMPTS = 1
MODEL_FAST_FAILURE_SECONDS = 10.0
MODEL_FAST_FAILURE_BACKOFF_SECONDS = 1.0
DEFAULT_MAX_CONSECUTIVE_PROVIDER_FAILURES = 3
DEFAULT_RERUN_STATUSES = frozenset({"failed", "timeout"})
PUBLIC_CASE_STATUSES = frozenset({"success", "failed", "timeout"})

_PROVIDER_CIRCUIT_REASONS = frozenset(
    {
        "auth_or_permission_failure",
        "rate_limited",
        "provider_5xx",
        "network_connect_failure",
        "network_read_timeout",
        "response_shape_invalid",
        "empty_response",
        "model_response_deadline_exceeded",
        "model_concurrency_wait_exceeded",
        "unknown_provider_failure",
        "candidate_json_incomplete",
        "candidate_json_invalid",
        "candidate_schema_invalid",
    }
)


class FastRetryClient:
    """Retry one bounded provider-side failure without serializing callers."""

    def __init__(
        self,
        client: Any,
        *,
        max_attempts: int = MODEL_FAST_FAILURE_ATTEMPTS,
        fast_failure_seconds: float = MODEL_FAST_FAILURE_SECONDS,
        backoff_seconds: float = MODEL_FAST_FAILURE_BACKOFF_SECONDS,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if fast_failure_seconds < 0 or backoff_seconds < 0:
            raise ValueError("retry timing must be nonnegative")
        chat = getattr(client, "chat", None)
        if not callable(chat):
            raise TypeError("client must expose a callable chat method")
        self._chat = chat
        self._max_attempts = max_attempts
        self._fast_failure_seconds = fast_failure_seconds
        self._backoff_seconds = backoff_seconds

    def chat(self, *, messages, temperature, max_tokens) -> Any:
        for attempt in range(self._max_attempts):
            started = perf_counter()
            try:
                response = self._chat(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if not isinstance(response, str):
                    return response
                return ObservedModelResponse(
                    response,
                    transport_attempts=attempt + 1,
                )
            except Exception as error:
                elapsed = perf_counter() - started
                failure_code = classify_transport_failure(error)
                if (
                    attempt + 1 >= self._max_attempts
                    or elapsed > self._fast_failure_seconds
                    or failure_code not in RETRYABLE_TRANSPORT_FAILURE_CODES
                ):
                    raise ModelTransportError(
                        failure_code,
                        attempts=attempt + 1,
                    ) from error
                sleep(self._backoff_seconds * (2**attempt))
        raise RuntimeError("unreachable model retry state")


class ConsecutiveProviderFailureCircuitBreaker:
    def __init__(
        self,
        max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_PROVIDER_FAILURES,
    ) -> None:
        if max_consecutive_failures < 1:
            raise ValueError("max_consecutive_failures must be positive")
        self.max_consecutive_failures = int(max_consecutive_failures)
        self.consecutive_failures = 0
        self.opened = False
        self.last_failure_reasons: list[str] = []

    def observe(self, record: BenchmarkRecord) -> bool:
        reasons = _provider_failure_reasons(record)
        if reasons:
            self.consecutive_failures += 1
            self.last_failure_reasons = reasons
        else:
            self.consecutive_failures = 0
            self.last_failure_reasons = []
        self.opened = self.consecutive_failures >= self.max_consecutive_failures
        return self.opened

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_consecutive_failures": self.max_consecutive_failures,
            "consecutive_failures": self.consecutive_failures,
            "opened": self.opened,
            "last_failure_reasons": list(self.last_failure_reasons),
        }


class RunStopController:
    """Record an external stop request without interrupting the active case write."""

    def __init__(self) -> None:
        self._requested = Event()
        self._lock = Lock()
        self.reason = ""
        self.exit_code = 0
        self._previous_handlers: dict[int, Any] = {}

    @property
    def requested(self) -> bool:
        return self._requested.is_set()

    def request(self, reason: str, exit_code: int) -> None:
        with self._lock:
            if self._requested.is_set():
                return
            self.reason = str(reason)
            self.exit_code = int(exit_code)
            self._requested.set()

    def install(self) -> None:
        for name, exit_code in (("SIGINT", 130), ("SIGTERM", 143)):
            signum = getattr(signal, name, None)
            if signum is None:
                continue
            self._previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(
                signum,
                lambda _signum, _frame, reason=name.lower(), code=exit_code: (
                    self.request(reason, code)
                ),
            )

    def restore(self) -> None:
        for signum, handler in self._previous_handlers.items():
            signal.signal(signum, handler)
        self._previous_handlers.clear()


class PerCaseWallClockRunner:
    """Return a terminal result before the configured persistence deadline."""

    def __init__(
        self,
        solve: Callable[[str, dict[str, Any]], dict[str, Any]],
        *,
        wall_clock_seconds: float = PER_CASE_WALL_CLOCK_SECONDS,
        serialization_reserve_seconds: float = RESULT_SERIALIZATION_RESERVE_SECONDS,
        cancellation_token_factory: Callable[[], CancellationToken] | None = None,
    ) -> None:
        if wall_clock_seconds <= 0:
            raise ValueError("wall_clock_seconds must be positive")
        if not 0 < serialization_reserve_seconds < wall_clock_seconds:
            raise ValueError(
                "serialization_reserve_seconds must be positive and below the wall clock"
            )
        self._solve = solve
        self.wall_clock_seconds = float(wall_clock_seconds)
        self.serialization_reserve_seconds = float(serialization_reserve_seconds)
        self.harness_return_seconds = (
            self.wall_clock_seconds - self.serialization_reserve_seconds
        )
        self._cancellation_token_factory = cancellation_token_factory

    def solve(self, problem: str, metadata: dict[str, Any]) -> dict[str, Any]:
        completed = Event()
        outcome: dict[str, Any] = {}
        outcome_lock = Lock()
        state = {"closed": False}
        started = perf_counter()
        cancellation_token = (
            self._cancellation_token_factory()
            if self._cancellation_token_factory is not None
            else None
        )

        def invoke() -> None:
            try:
                if cancellation_token is None:
                    result = self._solve(problem, dict(metadata))
                else:
                    result = self._solve(
                        problem,
                        dict(metadata),
                        cancellation_token=cancellation_token,
                    )
            except BaseException as error:
                result = self._failure_result(
                    problem,
                    metadata,
                    perf_counter() - started,
                    type(error).__name__,
                )
            with outcome_lock:
                if not state["closed"]:
                    outcome["result"] = result
            completed.set()

        Thread(
            target=invoke,
            name="mathforge-per-case-wall-clock",
            daemon=True,
        ).start()
        if not completed.wait(self.harness_return_seconds):
            if cancellation_token is not None:
                cancellation_token.cancel("per_case_wall_clock_exceeded")
            with outcome_lock:
                state["closed"] = True
            return self._timeout_result(
                problem,
                metadata,
                perf_counter() - started,
            )
        with outcome_lock:
            state["closed"] = True
            result = outcome.get("result")
        if not isinstance(result, dict):
            return self._failure_result(
                problem,
                metadata,
                perf_counter() - started,
                "InvalidSolveResult",
            )
        return result

    def _timeout_result(
        self,
        problem: str,
        metadata: dict[str, Any],
        elapsed_seconds: float,
    ) -> dict[str, Any]:
        elapsed = max(0.0, float(elapsed_seconds))
        final_response = (
            "未能在单题 20 分钟墙钟限制内完成求解；"
            "为避免输出未经验证的结论，本题返回确定性超时结果。"
        )
        session_id = f"timeout-{uuid4().hex}"
        fingerprint = _case_request_fingerprint(problem, metadata, session_id)
        events: list[dict[str, Any]] = []
        trace_builder = TraceBuilder(events, max_chars=0, max_events=0)
        trace_builder.add(
            "session_started",
            session_id=session_id,
            request_fingerprint=fingerprint,
        )
        trace_builder.add(
            "per_case_wall_clock_timeout",
            elapsed_seconds=round(elapsed, 6),
            wall_clock_seconds=self.wall_clock_seconds,
            serialization_reserve_seconds=self.serialization_reserve_seconds,
            error_code="per_case_wall_clock_exceeded",
        )
        trace_builder.add(
            "deadline_finalize",
            stage="wall_clock_timeout",
            disabled=["unfinished_harness_run"],
        )
        trace_builder.add(
            "budget_summary",
            outcome="timeout",
            wall_clock_seconds=self.wall_clock_seconds,
            elapsed_seconds=round(elapsed, 6),
        )
        trace_builder.add(
            "run_completed",
            outcome="timeout",
            final_phase="timeout_completed",
            error_code="per_case_wall_clock_exceeded",
        )
        trace = trace_builder.build(final_response=final_response)
        metrics = RunMetrics(
            session_id=session_id,
            request_fingerprint=fingerprint,
            elapsed_seconds=round(elapsed, 6),
            outcome="timeout",
            final_phase="timeout_completed",
            error_code="per_case_wall_clock_exceeded",
            per_case_wall_clock_timeout_count=1,
            deadline_phase="hard_expired",
        )
        return {
            "final_response": final_response,
            "trace": trace,
            "run_metrics": metrics.to_dict(),
        }

    @staticmethod
    def _failure_result(
        problem: str,
        metadata: dict[str, Any],
        elapsed_seconds: float,
        failure_type: str,
    ) -> dict[str, Any]:
        elapsed = max(0.0, float(elapsed_seconds))
        final_response = "本题执行过程中发生内部失败，未生成可验证的数学结论。"
        session_id = f"failed-{uuid4().hex}"
        fingerprint = _case_request_fingerprint(problem, metadata, session_id)
        events: list[dict[str, Any]] = []
        trace_builder = TraceBuilder(events, max_chars=0, max_events=0)
        trace_builder.add(
            "session_started",
            session_id=session_id,
            request_fingerprint=fingerprint,
        )
        trace_builder.add(
            "case_execution_failed",
            failure_type=str(failure_type),
            elapsed_seconds=round(elapsed, 6),
            error_code="case_execution_failed",
        )
        trace_builder.add(
            "budget_summary",
            outcome="error",
            elapsed_seconds=round(elapsed, 6),
        )
        trace_builder.add(
            "run_completed",
            outcome="error",
            final_phase="case_execution_failed",
            error_code="case_execution_failed",
        )
        trace = trace_builder.build(final_response=final_response)
        metrics = RunMetrics(
            session_id=session_id,
            request_fingerprint=fingerprint,
            elapsed_seconds=round(elapsed, 6),
            outcome="error",
            final_phase="case_execution_failed",
            error_code="case_execution_failed",
        )
        return {
            "final_response": final_response,
            "trace": trace,
            "run_metrics": metrics.to_dict(),
        }


class CaseRunManifest:
    def __init__(self, path: Path, payload: dict[str, Any]) -> None:
        self.path = path
        self.payload = payload
        self.resumed_case_ids: list[str] = []
        self.rerun_case_ids: list[str] = []
        self._lock = Lock()

    @property
    def attempt_id(self) -> str:
        attempts = self.payload.get("attempts", [])
        if not isinstance(attempts, list) or not attempts:
            raise RuntimeError("run manifest has no current attempt")
        return str(attempts[-1]["attempt_id"])

    @classmethod
    def prepare(
        cls,
        *,
        cases,
        input_path: Path,
        config_path: Path,
        output_dir: Path,
        seed: int,
        concurrency: int,
        resume: bool,
        rerun_statuses: frozenset[str] = DEFAULT_RERUN_STATUSES,
    ) -> tuple[list, CaseRunManifest]:
        if concurrency < 1 or concurrency > 4:
            raise ValueError("case runner concurrency must be between 1 and 4")
        invalid_rerun_statuses = set(rerun_statuses) - PUBLIC_CASE_STATUSES
        if invalid_rerun_statuses:
            raise ValueError(
                "invalid rerun statuses: "
                + ", ".join(sorted(invalid_rerun_statuses))
            )
        for case in cases:
            _validate_identifier(case.idx)
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / RUN_MANIFEST_FILENAME
        input_hash = _file_sha256(input_path)
        config_hash = _file_sha256(config_path)
        run_contract = _current_run_contract()
        expected_ids = {case.idx for case in cases}
        unknown_files = sorted(
            path.name
            for path in output_dir.glob("*.json")
            if path.name != RUN_MANIFEST_FILENAME
            and path.stem not in expected_ids
        )
        if unknown_files:
            raise ValueError(
                f"output directory contains unknown case files: {unknown_files}"
            )

        existing_payload = None
        if manifest_path.exists():
            if not resume:
                raise FileExistsError(
                    "run manifest already exists; pass --resume to continue"
                )
            existing_payload = _read_manifest(manifest_path)
            _validate_manifest_compatibility(
                existing_payload,
                input_hash=input_hash,
                config_hash=config_hash,
                case_ids=expected_ids,
                seed=seed,
                concurrency=concurrency,
                run_contract=run_contract,
            )
        elif any(
            _contained_case_path(output_dir, case.idx).exists()
            for case in cases
        ):
            if not resume:
                raise FileExistsError(
                    "case outputs already exist; pass --resume to validate them"
                )

        now = _utc_now()
        payload = existing_payload or {
            "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
            "status": "created",
            "input_sha256": input_hash,
            "config_sha256": config_hash,
            "case_count": len(cases),
            "case_ids": [case.idx for case in cases],
            "seed": int(seed),
            "concurrency": int(concurrency),
            "started_at": now,
            "updated_at": now,
            "model_identity": {},
            "preflight": {
                "schema_version": MODEL_PREFLIGHT_SCHEMA_VERSION,
                "status": "not_started",
                "levels": [],
            },
            "circuit_breaker": {},
            "cases": {},
            "summary": {},
            "attempt_count": 0,
            "attempts": [],
            "run_contract": run_contract,
        }
        _migrate_attempt_history(payload, now=now)
        attempts = payload["attempts"]
        if attempts and attempts[-1].get("status") == "running":
            attempts[-1]["status"] = "interrupted"
            attempts[-1]["stop_reason"] = "superseded_by_resume"
            attempts[-1]["ended_at"] = now
            attempts[-1]["updated_at"] = now
        payload["schema_version"] = RUN_MANIFEST_SCHEMA_VERSION
        payload["run_contract"] = run_contract
        payload["status"] = "created"
        payload["updated_at"] = now
        payload["concurrency"] = int(concurrency)
        payload["attempt_count"] = (
            max(int(payload.get("attempt_count", 0)), len(attempts)) + 1
        )
        attempt_id = f"attempt-{payload['attempt_count']:04d}"
        attempts.append(
            {
                "attempt_id": attempt_id,
                "status": "created",
                "started_at": now,
                "updated_at": now,
                "heartbeat_at": now,
                "run_pid": os.getpid(),
                "host_fingerprint": _host_fingerprint(),
                "concurrency": int(concurrency),
                "seed": int(seed),
                "model_request_policy": run_contract[
                    "model_request_policy"
                ],
                "code_identity": run_contract["code_identity"],
                "output_contract": run_contract["output_contract"],
                "cases": {},
            }
        )
        payload.pop("failure_type", None)
        payload.pop("stop_reason", None)
        payload.pop("ended_at", None)
        payload["summary"] = {}
        store = cls(manifest_path, payload)
        remaining = []
        entries = payload.setdefault("cases", {})
        for case in cases:
            case_path = _contained_case_path(output_dir, case.idx)
            if not case_path.exists():
                remaining.append(case)
                continue
            if not resume:
                raise FileExistsError(
                    f"case output already exists: {case_path.name}"
                )
            public_payload = validate_case_output(case_path, case.idx)
            digest = _file_sha256(case_path)
            entry = entries.get(case.idx)
            if isinstance(entry, dict) and entry.get("output_sha256"):
                if entry["output_sha256"] != digest:
                    raise ValueError(
                        f"case output hash mismatch: {case_path.name}"
                    )
            else:
                terminal = public_payload["trace"][-1]
                terminal_outcome = str(terminal.get("outcome", "error"))
                entries[case.idx] = {
                    "status": _terminal_status(terminal_outcome),
                    "terminal_outcome": terminal_outcome,
                    "output_file": case_path.name,
                    "output_sha256": digest,
                    "latency_seconds": None,
                    "run_metrics": {},
                    "score": {},
                    "request_fingerprint": "",
                    "resume_source": "validated_orphan_output",
                    "completed_at": now,
                }
            entry = entries[case.idx]
            if entry.get("status") != public_payload["status"]:
                raise ValueError(
                    f"case output status conflicts with manifest: {case_path.name}"
                )
            if public_payload["status"] in rerun_statuses:
                entries.pop(case.idx)
                store.rerun_case_ids.append(case.idx)
                remaining.append(case)
            else:
                store.resumed_case_ids.append(case.idx)
        if remaining:
            payload["preflight"] = {
                "schema_version": MODEL_PREFLIGHT_SCHEMA_VERSION,
                "status": "not_started",
                "levels": [],
            }
        store._persist()
        return remaining, store

    def record_model_identity(self, identity: dict[str, Any]) -> None:
        with self._lock:
            existing = self.payload.get("model_identity", {})
            if existing and existing != identity:
                raise ValueError("resume model identity does not match manifest")
            self.payload["model_identity"] = dict(identity)
            self._update_attempt_locked(model_identity=dict(identity))
            self._persist_locked()

    def record_preflight(self, report: dict[str, Any]) -> None:
        with self._lock:
            self.payload["preflight"] = dict(report)
            if report.get("status") == "passed":
                self.payload["status"] = "preflight_passed"
            self.payload["updated_at"] = _utc_now()
            self._update_attempt_locked(preflight=dict(report))
            self._persist_locked()

    def mark_running(self) -> None:
        with self._lock:
            if self.payload.get("preflight", {}).get("status") != "passed":
                raise RuntimeError("cannot start cases before model preflight passes")
            self.payload["status"] = "running"
            self.payload["updated_at"] = _utc_now()
            self._update_attempt_locked(status="running")
            self._persist_locked()

    def record(self, record: BenchmarkRecord, output_path: Path) -> None:
        with self._lock:
            outcome = record.run_metrics.outcome
            case_record = {
                "status": _terminal_status(outcome),
                "terminal_outcome": outcome,
                "output_file": output_path.name,
                "output_sha256": _file_sha256(output_path),
                "latency_seconds": round(record.latency_seconds, 6),
                "run_metrics": record.run_metrics.to_dict(),
                "score": record.score.to_dict(),
                "request_fingerprint": record.request_fingerprint,
                "resume_source": (
                    "rerun"
                    if record.case.idx in self.rerun_case_ids
                    else "executed"
                ),
                "attempt_id": self.attempt_id,
                "completed_at": _utc_now(),
            }
            self.payload.setdefault("cases", {})[record.case.idx] = case_record
            self._update_attempt_locked(
                case_id=record.case.idx,
                case_record=case_record,
            )
            self.payload["updated_at"] = _utc_now()
            self._persist_locked()

    def finalize(self, summary: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            lifecycle = self.lifecycle_summary()
            combined = {
                **dict(summary),
                "total_case_count": self.payload["case_count"],
                "executed_case_count": max(
                    0,
                    len(self.payload.get("cases", {}))
                    - len(self.resumed_case_ids),
                ),
                "resumed_case_count": len(self.resumed_case_ids),
                "rerun_case_count": len(self.rerun_case_ids),
                "pending_case_count": lifecycle["pending_case_count"],
                "terminal_status_counts": lifecycle[
                    "terminal_status_counts"
                ],
            }
            self.payload["summary"] = combined
            if self.payload.get("status") not in {
                "failed",
                "degraded",
                "aborted",
            }:
                self.payload["status"] = (
                    "completed"
                    if lifecycle["completed_case_count"]
                    == self.payload["case_count"]
                    else "degraded"
                )
                if self.payload["status"] == "degraded":
                    self.payload["stop_reason"] = "partial_run"
            self.payload["ended_at"] = _utc_now()
            self.payload["updated_at"] = _utc_now()
            self._update_attempt_locked(
                status=(
                    "interrupted"
                    if self.payload["status"] == "aborted"
                    else self.payload["status"]
                ),
                summary=combined,
                ended=True,
            )
            self._persist_locked()
            return combined

    def mark_failed(self, failure_type: str) -> None:
        with self._lock:
            self.payload["status"] = "failed"
            self.payload["failure_type"] = str(failure_type)
            self.payload["ended_at"] = _utc_now()
            self.payload["updated_at"] = _utc_now()
            self._update_attempt_locked(
                status="failed",
                failure_type=str(failure_type),
                ended=True,
            )
            self._persist_locked()

    def mark_degraded(self, reason: str) -> None:
        with self._lock:
            self.payload["status"] = "degraded"
            self.payload["stop_reason"] = str(reason)
            self.payload["updated_at"] = _utc_now()
            self._update_attempt_locked(
                status="degraded",
                stop_reason=str(reason),
            )
            self._persist_locked()

    def mark_aborted(self, reason: str) -> None:
        with self._lock:
            self.payload["status"] = "aborted"
            self.payload["stop_reason"] = str(reason)
            self.payload["updated_at"] = _utc_now()
            self._update_attempt_locked(
                status="interrupted",
                stop_reason=str(reason),
                ended=True,
            )
            self._persist_locked()

    def mark_provider_circuit_open(
        self,
        circuit_breaker: dict[str, Any],
    ) -> None:
        with self._lock:
            self.payload["status"] = "degraded"
            self.payload["stop_reason"] = "provider_circuit_open"
            self.payload["circuit_breaker"] = dict(circuit_breaker)
            self.payload["updated_at"] = _utc_now()
            self._update_attempt_locked(
                status="degraded",
                stop_reason="provider_circuit_open",
            )
            self._persist_locked()

    def lifecycle_summary(self) -> dict[str, Any]:
        entries = self.payload.get("cases", {})
        counts: dict[str, int] = {}
        for entry in entries.values():
            status = str(entry.get("status", "unknown"))
            counts[status] = counts.get(status, 0) + 1
        return {
            "completed_case_count": len(entries),
            "pending_case_count": max(
                0,
                int(self.payload["case_count"]) - len(entries),
            ),
            "terminal_status_counts": dict(sorted(counts.items())),
        }

    def _persist(self) -> None:
        with self._lock:
            self._persist_locked()

    def _persist_locked(self) -> None:
        _atomic_write_json(self.path, self.payload)

    def _update_attempt_locked(
        self,
        *,
        status: str | None = None,
        case_id: str | None = None,
        case_record: dict[str, Any] | None = None,
        ended: bool = False,
        **details: Any,
    ) -> None:
        attempts = self.payload.get("attempts", [])
        if not isinstance(attempts, list) or not attempts:
            return
        attempt = attempts[-1]
        now = _utc_now()
        if status is not None:
            attempt["status"] = status
        if case_id is not None and case_record is not None:
            attempt.setdefault("cases", {})[case_id] = dict(case_record)
        attempt.update(details)
        attempt["heartbeat_at"] = now
        attempt["updated_at"] = now
        if ended:
            attempt["ended_at"] = now


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run MathForge and atomically write one flat JSON file per case."
    )
    parser.add_argument("--input", type=Path, required=True, help="JSONL cases")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config" / "competition.json",
    )
    parser.add_argument(
        "--concurrency",
        type=_case_concurrency,
        default=3,
        help="number of concurrently active cases (1-3, default: 3)",
    )
    parser.add_argument(
        "--model",
        type=_exact_model_id,
        default=EXACT_INTERN_MODEL,
        help=f"exact local model ID (default: {EXACT_INTERN_MODEL})",
    )
    parser.add_argument(
        "--max-consecutive-provider-failures",
        type=int,
        default=DEFAULT_MAX_CONSECUTIVE_PROVIDER_FAILURES,
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        help="stop cleanly after this many cases have executed in this attempt",
    )
    parser.add_argument(
        "--stop-after-case",
        help="stop cleanly after the named case has been persisted",
    )
    parser.add_argument(
        "--rerun-status",
        type=_parse_rerun_statuses,
        default=DEFAULT_RERUN_STATUSES,
        help="comma-separated existing statuses to rerun (default: failed,timeout)",
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="validate existing files, skip success, and rerun failed/timeout",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    if args.max_consecutive_provider_failures < 1:
        parser.error("--max-consecutive-provider-failures must be positive")
    if args.max_cases is not None and args.max_cases < 1:
        parser.error("--max-cases must be positive")

    cases = load_jsonl(args.input)
    preflight_benchmark_cases(cases)
    if args.stop_after_case is not None:
        _validate_identifier(args.stop_after_case)
        if args.stop_after_case not in {case.idx for case in cases}:
            parser.error("--stop-after-case must name an input case")
    remaining_cases, manifest = CaseRunManifest.prepare(
        cases=cases,
        input_path=args.input,
        config_path=args.config,
        output_dir=args.output_dir,
        seed=args.seed,
        concurrency=args.concurrency,
        resume=args.resume,
        rerun_statuses=args.rerun_status,
    )
    if not remaining_cases:
        summary = manifest.finalize({})
        _safe_print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    stop_controller = RunStopController()
    stop_controller.install()
    summary: dict[str, Any] = {}
    exit_code = 0
    try:
        model_identity = exact_model_identity(
            args.model,
            request_source="argument:--model",
        )
        manifest.record_model_identity(model_identity.to_dict())
        config = load_benchmark_config(args.config)
        try:
            base_client = InternChatClient(
                timeout=model_http_timeout_seconds(config),
                retry=1,
            )
            base_client.model = args.model
        except Exception:
            preflight_report = run_model_preflight(
                None,
                requested_model=model_identity.requested_model,
            )
            manifest.record_preflight(preflight_report)
            raise RuntimeError("model preflight failed at L0") from None
        client = FastRetryClient(base_client)
        preflight_report = run_model_preflight(
            client,
            requested_model=model_identity.requested_model,
        )
        manifest.record_preflight(preflight_report)
        if stop_controller.requested:
            manifest.mark_aborted(stop_controller.reason)
            summary = manifest.finalize({})
            exit_code = stop_controller.exit_code
            return _print_summary(summary, exit_code)
        if preflight_report["status"] != "passed":
            raise RuntimeError(
                f"model preflight failed at {preflight_report['failed_level']}"
            )
        _safe_print("MODEL_PREFLIGHT_L0_L1_L2_OK")
        manifest.mark_running()
        harness = MathForgeHarness(
            client,
            config,
            model_identity=model_identity,
            trace_sink_factory=TraceJournalFactory(
                args.output_dir / ".trace-journal",
                attempt_id=manifest.attempt_id,
            ),
        )
        wall_clock_runner = PerCaseWallClockRunner(
            harness.solve,
            wall_clock_seconds=config.outer_platform_limit_seconds,
            serialization_reserve_seconds=(
                config.outer_platform_limit_seconds
                - config.hard_deadline_seconds
            ),
            cancellation_token_factory=CancellationToken,
        )

        def persist(record: BenchmarkRecord) -> None:
            path = write_case_output(record, args.output_dir)
            manifest.record(record, path)
            _safe_print(
                "CASE_COMPLETED "
                f"id={record.case.idx} "
                f"status={_terminal_status(record.run_metrics.outcome)} "
                f"elapsed={record.latency_seconds:.3f}s "
                f"path={path}"
            )

        breaker = ConsecutiveProviderFailureCircuitBreaker(
            args.max_consecutive_provider_failures
        )
        attempted_cases, planned_stop = _planned_case_batch(
            remaining_cases,
            stop_after_case=args.stop_after_case,
            max_cases=args.max_cases,
        )
        provider_circuit_open = Event()

        def persist_and_observe(record: BenchmarkRecord) -> None:
            persist(record)
            if (
                not provider_circuit_open.is_set()
                and breaker.observe(record)
                and manifest.lifecycle_summary()["pending_case_count"] > 0
            ):
                manifest.mark_provider_circuit_open(breaker.to_dict())
                provider_circuit_open.set()
                _safe_print(
                    "PROVIDER_CIRCUIT_OPEN "
                    f"consecutive_failures={breaker.consecutive_failures}"
                )

        completed_records, _ = run_benchmark(
            attempted_cases,
            wall_clock_runner.solve,
            concurrency=args.concurrency,
            seed=args.seed,
            on_record_completed=persist_and_observe,
            should_stop_scheduling=lambda: (
                stop_controller.requested or provider_circuit_open.is_set()
            ),
        )
        pending_case_count = manifest.lifecycle_summary()["pending_case_count"]
        if stop_controller.requested and pending_case_count:
            manifest.mark_aborted(stop_controller.reason)
            exit_code = stop_controller.exit_code
        elif planned_stop and pending_case_count:
            manifest.mark_degraded(planned_stop)
            _safe_print(f"CONTROLLED_STOP reason={planned_stop}")
        benchmark_summary = summarize(completed_records)
        benchmark_summary["circuit_breaker"] = breaker.to_dict()
        summary = manifest.finalize(benchmark_summary)
    except BaseException as error:
        if stop_controller.requested:
            manifest.mark_aborted(stop_controller.reason)
            summary = manifest.finalize({})
            exit_code = stop_controller.exit_code
        else:
            manifest.mark_failed(type(error).__name__)
            raise
    finally:
        stop_controller.restore()
    return _print_summary(summary, exit_code)


def _case_concurrency(value: str) -> int:
    concurrency = int(value)
    if concurrency < 1 or concurrency > 3:
        raise argparse.ArgumentTypeError(
            "--concurrency must be between 1 and 3"
        )
    return concurrency


def _exact_model_id(value: str) -> str:
    if value != EXACT_INTERN_MODEL:
        raise argparse.ArgumentTypeError(
            f"--model must be exactly {EXACT_INTERN_MODEL}"
        )
    return value


def _parse_rerun_statuses(value: str) -> frozenset[str]:
    statuses = frozenset(
        part.strip().lower()
        for part in value.split(",")
        if part.strip()
    )
    invalid = statuses - PUBLIC_CASE_STATUSES
    if invalid:
        raise argparse.ArgumentTypeError(
            "--rerun-status contains unsupported values: "
            + ", ".join(sorted(invalid))
        )
    return statuses


def _planned_stop_reason(
    *,
    case_id: str,
    executed_case_count: int,
    stop_after_case: str | None,
    max_cases: int | None,
) -> str:
    if stop_after_case is not None and case_id == stop_after_case:
        return "stop_after_case"
    if max_cases is not None and executed_case_count >= max_cases:
        return "max_cases_reached"
    return ""


def _planned_case_batch(
    cases: list,
    *,
    stop_after_case: str | None,
    max_cases: int | None,
) -> tuple[list, str]:
    planned = []
    reason = ""
    for case in cases:
        planned.append(case)
        reason = _planned_stop_reason(
            case_id=case.idx,
            executed_case_count=len(planned),
            stop_after_case=stop_after_case,
            max_cases=max_cases,
        )
        if reason:
            break
    if len(planned) == len(cases):
        reason = ""
    return planned, reason


def _print_summary(summary: dict[str, Any], exit_code: int) -> int:
    _safe_print(json.dumps(summary, ensure_ascii=False, indent=2))
    return int(exit_code)


def _safe_print(message: str) -> None:
    try:
        print(message, flush=True)
    except (BrokenPipeError, OSError, UnicodeError):
        pass


def write_case_output(record: BenchmarkRecord, output_dir: Path) -> Path:
    identifier = record.case.idx
    _validate_identifier(identifier)
    try:
        payload = build_public_result(
            _json_identifier(identifier),
            record.result,
        )
    except ValueError:
        failure_result = PerCaseWallClockRunner._failure_result(
            record.case.problem,
            {"idx": identifier},
            record.latency_seconds,
            "PublicOutputContractError",
        )
        answer_type = record.case.answer_type or ProblemParser().parse(
            record.case.problem
        ).answer_type
        record.result = failure_result
        record.json_valid = False
        record.run_metrics = RunMetrics.from_dict(
            failure_result["run_metrics"]
        )
        record.score = score_response(
            record.case.expected_answer,
            failure_result["final_response"],
            answer_type=answer_type,
            scorer=record.case.scorer,
        )
        payload = build_public_result(
            _json_identifier(identifier),
            failure_result,
        )
    _validate_public_payload(payload, identifier)
    destination = _contained_case_path(output_dir, identifier)
    _atomic_write_json(destination, payload)
    return destination


def run_model_preflight(
    client: Any,
    *,
    requested_model: str = EXACT_INTERN_MODEL,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": MODEL_PREFLIGHT_SCHEMA_VERSION,
        "status": "running",
        "failed_level": "",
        "levels": [],
    }
    l0_error = ""
    if requested_model != EXACT_INTERN_MODEL:
        l0_error = "model_identity_invalid"
    elif not callable(getattr(client, "chat", None)):
        l0_error = "model_client_unavailable"
    if l0_error:
        report["levels"].append(
            {
                "level": "L0",
                "status": "failed",
                "error_code": l0_error,
                "elapsed_seconds": 0.0,
                "max_tokens": 0,
                "transport_attempts": 0,
            }
        )
        report["status"] = "failed"
        report["failed_level"] = "L0"
        return report
    report["levels"].append(
        {
            "level": "L0",
            "status": "passed",
            "error_code": "",
            "elapsed_seconds": 0.0,
            "max_tokens": 0,
            "transport_attempts": 0,
        }
    )

    l1_started = perf_counter()
    try:
        l1_response = client.chat(
            messages=[
                {
                    "role": "system",
                    "content": "Return only the exact JSON object requested by the user.",
                },
                {
                    "role": "user",
                    "content": 'Return exactly {"status":"ok"}.',
                },
            ],
            temperature=0.0,
            max_tokens=MODEL_PREFLIGHT_L1_MAX_TOKENS,
        )
        if not isinstance(l1_response, str):
            raise ModelTransportError("response_shape_invalid")
        if not l1_response.strip():
            raise ModelTransportError(
                "empty_response",
                attempts=transport_attempts(l1_response),
            )
        l1_payload = json.loads(l1_response)
        if l1_payload != {"status": "ok"}:
            raise ModelTransportError(
                "response_shape_invalid",
                attempts=transport_attempts(l1_response),
            )
    except Exception as error:
        _record_preflight_failure(
            report,
            "L1",
            error,
            l1_started,
            MODEL_PREFLIGHT_L1_MAX_TOKENS,
        )
        return report
    report["levels"].append(
        _passed_preflight_level(
            "L1",
            l1_started,
            MODEL_PREFLIGHT_L1_MAX_TOKENS,
            transport_attempts(l1_response),
        )
    )

    l2_started = perf_counter()
    l2_budget = CallBudget(2)
    try:
        l2_problem = ProblemParser().parse("Compute 1+1.")
        l2_route = RouterRuleEngine().plan(l2_problem)
        l2_method_family = l2_route.method_families[0]
        l2_request = SolverRequest(
            candidate_id="preflight-l2",
            problem=l2_problem,
            route=l2_route,
            skill_context="",
            method_family=l2_method_family,
        )
        candidate = SolverExecutor(
            OfficialClientProvider(client, ModelCallGate(1)),
            SolutionParser(),
        ).execute(
            PrimarySolver(),
            l2_request,
            l2_budget,
            temperature=0.0,
            max_tokens=MODEL_PREFLIGHT_MAX_TOKENS,
        )
        if (
            candidate.final_answer.strip() != "2"
            or not candidate.claims
            or not candidate.method_steps
        ):
            raise ModelResponseError(
                "candidate_schema_invalid",
                details=tuple(candidate.contract_deviations),
            )
        _validate_l2_pipeline(candidate)
    except Exception as error:
        _record_preflight_failure(
            report,
            "L2",
            error,
            l2_started,
            MODEL_PREFLIGHT_MAX_TOKENS,
            transport_attempt_count=l2_budget.transport_attempts,
        )
        return report
    report["levels"].append(
        _passed_preflight_level(
            "L2",
            l2_started,
            MODEL_PREFLIGHT_MAX_TOKENS,
            l2_budget.transport_attempts,
        )
    )
    report["status"] = "passed"
    return report


def verify_model_availability(client: Any) -> dict[str, Any]:
    report = run_model_preflight(client)
    if report["status"] != "passed":
        raise RuntimeError(f"model preflight failed at {report['failed_level']}")
    return report


def model_http_timeout_seconds(config: Any) -> int:
    available = (
        float(config.hard_deadline_seconds)
        - float(config.deterministic_finalize_reserve_seconds)
    )
    if available < 1:
        raise ValueError("model HTTP timeout window is not positive")
    return max(1, int(min(available, PROVIDER_HTTP_TIMEOUT_SECONDS)))


def _validate_l2_pipeline(candidate: Any) -> None:
    problem = ProblemParser().parse("Compute 1+1.")
    final_response = DeterministicFormatter().format(candidate, problem)
    if not final_response.strip():
        raise ModelResponseError("candidate_formatter_invalid")

    events: list[dict[str, Any]] = []
    trace = TraceBuilder(events, max_chars=0, max_events=0)
    candidate_id = str(candidate.candidate_id)
    trace.add("session_started", session_id="preflight-l2")
    trace.add("problem_parsed")
    trace.add("route_planned")
    trace.add("skills_selected", skills=[])
    trace.add("resource_plan_created", stage_quotas_enforced=False)
    trace.add(
        "candidate_generation_started",
        candidate_id=candidate_id,
        role=candidate.role,
    )
    trace.add("candidate_generated", **candidate_trace_payload(candidate))
    trace.add(
        "candidate_evidence_completed",
        candidate_id=candidate_id,
        status="passed",
        claim_results=[],
    )
    trace.add("hard_evidence_gate", accepted=[candidate_id], rejected=[])
    trace.add(
        "proof_completion_gate",
        accepted=[candidate_id],
        rejected=[],
        mode="preflight",
        verifier_reason="preflight_contract_validated",
        decisions=[
            {
                "candidate_id": candidate_id,
                "status": "complete_hard",
                "unresolved_obligation_ids": [],
                "failed_obligation_ids": [],
                "failed_claim_ids": [],
            }
        ],
    )
    trace.add(
        "candidate_arbitrated",
        selected=candidate_id,
        viable_candidates=[candidate_id],
    )
    trace.add(
        "final_answer_selected",
        candidate_id=candidate_id,
        public_solution={
            "public_solution_steps": list(candidate.public_solution_steps),
            "final_answer": candidate.final_answer,
            "final_response": final_response,
        },
    )
    trace.add("budget_summary")
    trace.add(
        "run_completed",
        outcome="primary",
        final_phase="completed",
        error_code="",
    )
    internal_trace = trace.build(final_response=final_response)
    public = build_public_result(
        "preflight-l2",
        {
            "final_response": final_response,
            "trace": internal_trace,
            "run_metrics": {"outcome": "primary"},
        },
    )
    if (
        set(public) != {"id", "status", "final_response", "trace"}
        or public["status"] != "success"
    ):
        raise ModelResponseError("candidate_public_contract_invalid")


def _passed_preflight_level(
    level: str,
    started: float,
    max_tokens: int,
    attempts: int,
) -> dict[str, Any]:
    return {
        "level": level,
        "status": "passed",
        "error_code": "",
        "elapsed_seconds": round(max(0.0, perf_counter() - started), 6),
        "max_tokens": max_tokens,
        "transport_attempts": max(1, int(attempts)),
    }


def _record_preflight_failure(
    report: dict[str, Any],
    level: str,
    error: Exception,
    started: float,
    max_tokens: int,
    *,
    transport_attempt_count: int | None = None,
) -> None:
    code = getattr(error, "code", None) or classify_transport_failure(error)
    report["levels"].append(
        {
            "level": level,
            "status": "failed",
            "error_code": str(code),
            "elapsed_seconds": round(max(0.0, perf_counter() - started), 6),
            "max_tokens": max_tokens,
            "transport_attempts": (
                transport_attempts(error)
                if transport_attempt_count is None
                else max(1, int(transport_attempt_count))
            ),
        }
    )
    report["status"] = "failed"
    report["failed_level"] = level


def _provider_failure_reasons(record: BenchmarkRecord) -> list[str]:
    if record.run_metrics.outcome == "primary":
        return []
    reasons = {
        str(event.get("reason", ""))
        for event in record.result.get("trace", [])
        if isinstance(event, dict)
        and event.get("event") == "candidate_generation_failed"
        and str(event.get("reason", "")) in _PROVIDER_CIRCUIT_REASONS
    }
    if not reasons and record.run_metrics.model_call_failure_count:
        reasons.add("unknown_provider_failure")
    return sorted(reasons)


def validate_case_output(path: Path, identifier: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"case output is unreadable: {path.name}") from error
    _validate_public_payload(payload, identifier)
    schema_versions = {
        event.get("schema_version")
        for event in payload["trace"]
        if isinstance(event, dict)
    }
    if schema_versions != {JUDGE_TRACE_SCHEMA_VERSION}:
        raise ValueError("case output Judge Trace schema is incompatible")
    build_public_result(payload["id"], payload)
    return payload


def _validate_public_payload(payload: Any, identifier: str) -> None:
    if not isinstance(payload, dict) or set(payload) != {
        "id",
        "status",
        "final_response",
        "trace",
    }:
        raise ValueError(
            "case output must contain exactly id, status, final_response, trace"
        )
    if payload["id"] != _json_identifier(identifier):
        raise ValueError("case output id does not match filename")
    if (
        not isinstance(payload["final_response"], str)
        or not payload["final_response"].strip()
    ):
        raise ValueError("case output final_response must be non-empty")
    trace = payload["trace"]
    if (
        not isinstance(trace, list)
        or not trace
        or not isinstance(trace[-1], dict)
        or trace[-1].get("event") != "run_completed"
    ):
        raise ValueError("case output trace must have a terminal run_completed event")
    expected_status = _terminal_status(str(trace[-1].get("outcome", "")))
    if payload["status"] != expected_status:
        raise ValueError("case output status conflicts with terminal outcome")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("run manifest is unreadable") from error
    if not isinstance(payload, dict):
        raise ValueError("run manifest must be an object")
    return payload


def _validate_manifest_compatibility(
    payload: dict[str, Any],
    *,
    input_hash: str,
    config_hash: str,
    case_ids: set[str],
    seed: int,
    concurrency: int,
    run_contract: dict[str, Any],
) -> None:
    if (
        payload.get("schema_version")
        not in COMPATIBLE_RUN_MANIFEST_SCHEMA_VERSIONS
    ):
        raise ValueError("run manifest schema version is incompatible")
    if payload.get("input_sha256") != input_hash:
        raise ValueError("resume input hash does not match manifest")
    if payload.get("config_sha256") != config_hash:
        raise ValueError("resume config hash does not match manifest")
    if set(payload.get("case_ids", [])) != case_ids:
        raise ValueError("resume case IDs do not match manifest")
    if payload.get("case_count") != len(case_ids):
        raise ValueError("resume case count does not match manifest")
    if payload.get("seed") != int(seed):
        raise ValueError("resume seed does not match manifest")
    if payload.get("concurrency") != int(concurrency):
        raise ValueError("resume concurrency does not match manifest")
    if not isinstance(payload.get("cases"), dict):
        raise ValueError("run manifest case records are invalid")
    recorded_contract = payload.get("run_contract")
    if payload.get("schema_version") == RUN_MANIFEST_SCHEMA_VERSION:
        if recorded_contract != run_contract:
            raise ValueError("resume run contract does not match manifest")
    elif recorded_contract not in (None, {}, run_contract):
        raise ValueError("resume legacy run contract does not match")


def _migrate_attempt_history(
    payload: dict[str, Any],
    *,
    now: str,
) -> None:
    attempts = payload.get("attempts")
    if isinstance(attempts, list):
        return
    count = max(0, int(payload.get("attempt_count", 0)))
    migrated: list[dict[str, Any]] = []
    for number in range(1, count + 1):
        is_last = number == count
        migrated.append(
            {
                "attempt_id": f"attempt-{number:04d}",
                "status": (
                    str(payload.get("status", "unknown"))
                    if is_last
                    else "historical"
                ),
                "started_at": str(payload.get("started_at", now)),
                "updated_at": str(payload.get("updated_at", now)),
                "heartbeat_at": str(payload.get("updated_at", now)),
                "ended_at": str(payload.get("ended_at", "")),
                "run_pid": 0,
                "host_fingerprint": "",
                "cases": (
                    dict(payload.get("cases", {})) if is_last else {}
                ),
                "migrated_from_legacy_manifest": True,
            }
        )
    payload["attempts"] = migrated


def _current_run_contract() -> dict[str, Any]:
    return {
        "model_request_policy": {
            "requested_model": EXACT_INTERN_MODEL,
            "source": "internal_explicit_default_or_cli_argument",
            "interface": "client.chat",
        },
        "code_identity": _code_identity(),
        "output_contract": {
            "judge_trace_schema_version": JUDGE_TRACE_SCHEMA_VERSION,
            "top_level_fields": [
                "id",
                "status",
                "final_response",
                "trace",
            ],
            "case_statuses": sorted(PUBLIC_CASE_STATUSES),
        },
        "manifest_schema_version": RUN_MANIFEST_SCHEMA_VERSION,
    }


def _code_identity() -> dict[str, Any]:
    source_paths = sorted(
        [
            *ROOT.joinpath("mathforge").rglob("*.py"),
            ROOT / "scripts" / "run_case_outputs.py",
            ROOT / "user_agent.py",
        ],
        key=lambda path: path.as_posix(),
    )
    digest = sha256()
    for path in source_paths:
        if not path.is_file():
            continue
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    commit = _git_output("rev-parse", "HEAD")
    dirty_status = _git_output(
        "status",
        "--porcelain",
        "--untracked-files=no",
    )
    return {
        "commit": commit or "unavailable",
        "dirty": bool(dirty_status),
        "source_sha256": digest.hexdigest(),
    }


def _git_output(*arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _host_fingerprint() -> str:
    host = platform.node().strip().casefold()
    return sha256(host.encode("utf-8")).hexdigest() if host else ""


def _case_request_fingerprint(
    problem: str,
    metadata: dict[str, Any],
    fallback_nonce: str,
) -> str:
    nonce = str(metadata.get("benchmark_nonce", fallback_nonce))
    return request_fingerprint(problem, nonce)


def _terminal_status(outcome: str) -> str:
    if outcome == "timeout":
        return "timeout"
    if outcome in {"primary", "success"}:
        return "success"
    return "failed"


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_identifier(identifier: str) -> None:
    if (
        not identifier
        or identifier in {".", ".."}
        or Path(identifier).name != identifier
        or f"{identifier}.json" == RUN_MANIFEST_FILENAME
        or any(character in '<>:"/\\|?*' for character in identifier)
    ):
        raise ValueError("case id is not safe for a filename")


def _contained_case_path(output_dir: Path, identifier: str) -> Path:
    _validate_identifier(identifier)
    root = output_dir.resolve()
    destination = (root / f"{identifier}.json").resolve()
    if destination.parent != root:
        raise ValueError("case output path escapes the output directory")
    return destination


def _json_identifier(identifier: str) -> int | str:
    try:
        numeric = int(identifier)
    except ValueError:
        return identifier
    return numeric if str(numeric) == identifier else identifier


if __name__ == "__main__":
    raise SystemExit(main())
