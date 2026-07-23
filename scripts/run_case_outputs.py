from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm_client import DEFAULT_MODEL, InternChatClient  # noqa: E402
from mathforge.benchmark import BenchmarkRecord, load_jsonl, run_benchmark  # noqa: E402
from mathforge.output.public_result import build_public_result  # noqa: E402
from mathforge.runtime import MathForgeHarness  # noqa: E402
from scripts.run_benchmark import load_benchmark_config  # noqa: E402


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
    parser.add_argument("--model-identifier", default=DEFAULT_MODEL)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    config = load_benchmark_config(args.config)
    harness = MathForgeHarness(
        InternChatClient(),
        config,
        model_identifier=args.model_identifier,
    )

    def persist(record: BenchmarkRecord) -> None:
        path = write_case_output(record, args.output_dir)
        print(f"Wrote {path}", flush=True)

    _, summary = run_benchmark(
        load_jsonl(args.input),
        harness.solve,
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
