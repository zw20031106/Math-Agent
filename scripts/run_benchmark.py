from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm_client import InternChatClient  # noqa: E402
from mathforge.benchmark import load_jsonl, run_benchmark  # noqa: E402
from mathforge.config import HarnessConfig  # noqa: E402
from mathforge.runtime import MathForgeHarness  # noqa: E402


BENCHMARK_SCHEMA_VERSION = "2.0"


def build_benchmark_metadata(input_path: Path, config_path: Path) -> dict:
    config_payload = json.loads(config_path.read_text(encoding="utf-8"))
    return {
        "benchmark_schema_version": BENCHMARK_SCHEMA_VERSION,
        "dataset_sha256": _file_sha256(input_path),
        "config_sha256": _file_sha256(config_path),
        "config_status": str(config_payload.get("status", "unspecified")),
        "git_commit": _git_commit(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a MathForge ablation benchmark.")
    parser.add_argument("--input", type=Path, required=True, help="JSONL benchmark cases")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "competition.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()

    config = HarnessConfig.from_json(args.config)
    harness = MathForgeHarness(InternChatClient(), config)
    cases = load_jsonl(args.input)
    records, summary = run_benchmark(cases, harness.solve, concurrency=args.concurrency)
    output = {
        **build_benchmark_metadata(args.input, args.config),
        "config": args.config.as_posix(),
        "summary": summary,
        "records": [
            {
                "idx": record.case.idx,
                "latency_seconds": record.latency_seconds,
                "json_valid": record.json_valid,
                "final_response": record.result.get("final_response", ""),
                "request_fingerprint": record.request_fingerprint,
                "score": record.score.to_dict(),
            }
            for record in records
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
