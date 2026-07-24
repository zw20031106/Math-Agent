from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Event, Thread
from time import perf_counter
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm_client import InternChatClient  # noqa: E402
from mathforge.benchmark import BenchmarkRecord, load_jsonl, run_benchmark  # noqa: E402
from mathforge.harness.metrics import RunMetrics  # noqa: E402
from mathforge.model_identity import require_exact_intern_model  # noqa: E402
from mathforge.output.public_result import build_public_result  # noqa: E402
from mathforge.runtime import MathForgeHarness  # noqa: E402
from scripts.run_benchmark import load_benchmark_config  # noqa: E402


PER_CASE_WALL_CLOCK_SECONDS = 900.0
RESULT_SERIALIZATION_RESERVE_SECONDS = 30.0


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
        started = perf_counter()

        def invoke() -> None:
            try:
                outcome["result"] = self._solve(problem, metadata)
            except BaseException as error:
                outcome["error"] = error
            finally:
                completed.set()

        Thread(
            target=invoke,
            name="mathforge-per-case-wall-clock",
            daemon=True,
        ).start()
        if not completed.wait(self.harness_return_seconds):
            return self._timeout_result(perf_counter() - started)
        if "error" in outcome:
            raise outcome["error"]
        result = outcome.get("result")
        if not isinstance(result, dict):
            raise TypeError("solve must return a mapping")
        return result

    def _timeout_result(self, elapsed_seconds: float) -> dict[str, Any]:
        elapsed = max(0.0, float(elapsed_seconds))
        final_response = (
            "未能在单题 15 分钟墙钟限制内完成求解；"
            "为避免输出未经验证的结论，本题返回确定性超时结果。"
        )
        trace = [
            {
                "event": "per_case_wall_clock_timeout",
                "elapsed_seconds": round(elapsed, 6),
                "wall_clock_seconds": self.wall_clock_seconds,
                "serialization_reserve_seconds": (
                    self.serialization_reserve_seconds
                ),
                "error_code": "per_case_wall_clock_exceeded",
            },
            {
                "event": "run_completed",
                "outcome": "timeout",
                "final_phase": "timeout_completed",
                "error_code": "per_case_wall_clock_exceeded",
            },
        ]
        metrics = RunMetrics(
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
    args = parser.parse_args()

    model_identity = require_exact_intern_model()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    config = load_benchmark_config(args.config)
    harness = MathForgeHarness(
        InternChatClient(),
        config,
        model_identity=model_identity,
    )
    wall_clock_runner = PerCaseWallClockRunner(harness.solve)

    def persist(record: BenchmarkRecord) -> None:
        path = write_case_output(record, args.output_dir)
        print(f"Wrote {path}", flush=True)

    _, summary = run_benchmark(
        load_jsonl(args.input),
        wall_clock_runner.solve,
        concurrency=args.concurrency,
        seed=args.seed,
        on_record_completed=persist,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def write_case_output(record: BenchmarkRecord, output_dir: Path) -> Path:
    identifier = record.case.idx
    _validate_identifier(identifier)
    payload = build_public_result(_json_identifier(identifier), record.result)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{identifier}.json"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{identifier}.",
        suffix=".tmp",
        dir=output_dir,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def _validate_identifier(identifier: str) -> None:
    if (
        not identifier
        or identifier in {".", ".."}
        or Path(identifier).name != identifier
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
