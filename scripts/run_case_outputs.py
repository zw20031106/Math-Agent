from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Event, Lock, Thread
from time import perf_counter
from typing import Any, Callable
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm_client import InternChatClient  # noqa: E402
from mathforge.benchmark import (  # noqa: E402
    BenchmarkRecord,
    load_jsonl,
    preflight_benchmark_cases,
    run_benchmark,
)
from mathforge.harness.fingerprints import request_fingerprint  # noqa: E402
from mathforge.harness.metrics import RunMetrics  # noqa: E402
from mathforge.harness.trace import TraceBuilder  # noqa: E402
from mathforge.model_identity import require_exact_intern_model  # noqa: E402
from mathforge.output.public_result import build_public_result  # noqa: E402
from mathforge.runtime import MathForgeHarness  # noqa: E402
from scripts.run_benchmark import load_benchmark_config  # noqa: E402


PER_CASE_WALL_CLOCK_SECONDS = 900.0
RESULT_SERIALIZATION_RESERVE_SECONDS = 30.0
RUN_MANIFEST_SCHEMA_VERSION = "1.0"
RUN_MANIFEST_FILENAME = "run_manifest.json"


class PerCaseWallClockRunner:
    """Return a terminal result before the 15-minute persistence deadline."""

    def __init__(
        self,
        solve: Callable[[str, dict[str, Any]], dict[str, Any]],
        *,
        wall_clock_seconds: float = PER_CASE_WALL_CLOCK_SECONDS,
        serialization_reserve_seconds: float = RESULT_SERIALIZATION_RESERVE_SECONDS,
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

    def solve(self, problem: str, metadata: dict[str, Any]) -> dict[str, Any]:
        completed = Event()
        outcome: dict[str, Any] = {}
        outcome_lock = Lock()
        state = {"closed": False}
        started = perf_counter()

        def invoke() -> None:
            try:
                result = self._solve(problem, dict(metadata))
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
            "未能在单题 15 分钟墙钟限制内完成求解；"
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
        self._lock = Lock()

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
    ) -> tuple[list, CaseRunManifest]:
        if concurrency < 1:
            raise ValueError("concurrency must be positive")
        for case in cases:
            _validate_identifier(case.idx)
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / RUN_MANIFEST_FILENAME
        input_hash = _file_sha256(input_path)
        config_hash = _file_sha256(config_path)
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
            )
        elif any((output_dir / f"{case.idx}.json").exists() for case in cases):
            if not resume:
                raise FileExistsError(
                    "case outputs already exist; pass --resume to validate them"
                )

        now = _utc_now()
        payload = existing_payload or {
            "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
            "status": "running",
            "input_sha256": input_hash,
            "config_sha256": config_hash,
            "case_count": len(cases),
            "case_ids": [case.idx for case in cases],
            "seed": int(seed),
            "concurrency": int(concurrency),
            "started_at": now,
            "updated_at": now,
            "model_identity": {},
            "cases": {},
            "summary": {},
        }
        payload["status"] = "running"
        payload["updated_at"] = now
        payload["concurrency"] = int(concurrency)
        store = cls(manifest_path, payload)
        remaining = []
        entries = payload.setdefault("cases", {})
        for case in cases:
            case_path = output_dir / f"{case.idx}.json"
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
            store.resumed_case_ids.append(case.idx)
        store._persist()
        return remaining, store

    def record_model_identity(self, identity: dict[str, Any]) -> None:
        with self._lock:
            existing = self.payload.get("model_identity", {})
            if existing and existing != identity:
                raise ValueError("resume model identity does not match manifest")
            self.payload["model_identity"] = dict(identity)
            self._persist_locked()

    def record(self, record: BenchmarkRecord, output_path: Path) -> None:
        with self._lock:
            outcome = record.run_metrics.outcome
            self.payload.setdefault("cases", {})[record.case.idx] = {
                "status": _terminal_status(outcome),
                "terminal_outcome": outcome,
                "output_file": output_path.name,
                "output_sha256": _file_sha256(output_path),
                "latency_seconds": round(record.latency_seconds, 6),
                "run_metrics": record.run_metrics.to_dict(),
                "score": record.score.to_dict(),
                "request_fingerprint": record.request_fingerprint,
                "resume_source": "executed",
                "completed_at": _utc_now(),
            }
            self.payload["updated_at"] = _utc_now()
            self._persist_locked()

    def finalize(self, summary: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            lifecycle = self.lifecycle_summary()
            combined = {
                **dict(summary),
                "total_case_count": self.payload["case_count"],
                "executed_case_count": (
                    self.payload["case_count"] - len(self.resumed_case_ids)
                ),
                "resumed_case_count": len(self.resumed_case_ids),
                "terminal_status_counts": lifecycle[
                    "terminal_status_counts"
                ],
            }
            self.payload["summary"] = combined
            self.payload["status"] = (
                "completed"
                if lifecycle["completed_case_count"]
                == self.payload["case_count"]
                else "incomplete"
            )
            self.payload["updated_at"] = _utc_now()
            self._persist_locked()
            return combined

    def mark_failed(self, failure_type: str) -> None:
        with self._lock:
            self.payload["status"] = "failed"
            self.payload["failure_type"] = str(failure_type)
            self.payload["updated_at"] = _utc_now()
            self._persist_locked()

    def lifecycle_summary(self) -> dict[str, Any]:
        entries = self.payload.get("cases", {})
        counts: dict[str, int] = {}
        for entry in entries.values():
            status = str(entry.get("status", "unknown"))
            counts[status] = counts.get(status, 0) + 1
        return {
            "completed_case_count": len(entries),
            "terminal_status_counts": dict(sorted(counts.items())),
        }

    def _persist(self) -> None:
        with self._lock:
            self._persist_locked()

    def _persist_locked(self) -> None:
        _atomic_write_json(self.path, self.payload)


def main() -> int:
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
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="validate completed case files against the run manifest and skip them",
    )
    args = parser.parse_args()

    cases = load_jsonl(args.input)
    preflight_benchmark_cases(cases)
    remaining_cases, manifest = CaseRunManifest.prepare(
        cases=cases,
        input_path=args.input,
        config_path=args.config,
        output_dir=args.output_dir,
        seed=args.seed,
        concurrency=args.concurrency,
        resume=args.resume,
    )
    if not remaining_cases:
        summary = manifest.finalize({})
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        return 0

    try:
        model_identity = require_exact_intern_model()
        manifest.record_model_identity(model_identity.to_dict())
        config = load_benchmark_config(args.config)
        harness = MathForgeHarness(
            InternChatClient(),
            config,
            model_identity=model_identity,
        )
        wall_clock_runner = PerCaseWallClockRunner(harness.solve)

        def persist(record: BenchmarkRecord) -> None:
            path = write_case_output(record, args.output_dir)
            manifest.record(record, path)
            print(
                "CASE_COMPLETED "
                f"id={record.case.idx} "
                f"status={_terminal_status(record.run_metrics.outcome)} "
                f"elapsed={record.latency_seconds:.3f}s "
                f"path={path}",
                flush=True,
            )

        _, benchmark_summary = run_benchmark(
            remaining_cases,
            wall_clock_runner.solve,
            concurrency=args.concurrency,
            seed=args.seed,
            on_record_completed=persist,
        )
        summary = manifest.finalize(benchmark_summary)
    except BaseException as error:
        manifest.mark_failed(type(error).__name__)
        raise
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


def write_case_output(record: BenchmarkRecord, output_dir: Path) -> Path:
    identifier = record.case.idx
    _validate_identifier(identifier)
    payload = build_public_result(_json_identifier(identifier), record.result)
    _validate_public_payload(payload, identifier)
    destination = output_dir / f"{identifier}.json"
    _atomic_write_json(destination, payload)
    return destination


def validate_case_output(path: Path, identifier: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"case output is unreadable: {path.name}") from error
    _validate_public_payload(payload, identifier)
    build_public_result(payload["id"], payload)
    return payload


def _validate_public_payload(payload: Any, identifier: str) -> None:
    if not isinstance(payload, dict) or set(payload) != {
        "id",
        "final_response",
        "trace",
    }:
        raise ValueError("case output must contain exactly id, final_response, trace")
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
) -> None:
    if payload.get("schema_version") != RUN_MANIFEST_SCHEMA_VERSION:
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
    if not isinstance(payload.get("cases"), dict):
        raise ValueError("run manifest case records are invalid")


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
    if outcome == "error":
        return "failed"
    return "success"


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


def _json_identifier(identifier: str) -> int | str:
    try:
        numeric = int(identifier)
    except ValueError:
        return identifier
    return numeric if str(numeric) == identifier else identifier


if __name__ == "__main__":
    raise SystemExit(main())
