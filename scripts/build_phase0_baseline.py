from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "phase0_baseline_manifest.json"
DATASETS = (
    (
        "reliability",
        ROOT / "tests" / "fixtures" / "phase0_reliability.jsonl",
    ),
    (
        "general_high_difficulty",
        ROOT / "tests" / "fixtures" / "phase0_general_high_difficulty.jsonl",
    ),
    (
        "contract_adversarial",
        ROOT / "tests" / "fixtures" / "phase0_contract_adversarial.jsonl",
    ),
)


def build_manifest() -> dict[str, Any]:
    records = [
        _dataset_record(name, path)
        for name, path in DATASETS
    ]
    return {
        "schema_version": "1.0",
        "phase": "phase0",
        "captured_at": "2026-07-30",
        "purpose": "reproducible stability and accuracy baseline",
        "datasets": records,
        "config": _file_record(ROOT / "config" / "competition.json"),
        "metrics": {
            "answer_equivalence_accuracy": (
                "correct symbolic-equivalence canaries / all canaries"
            ),
            "answer_production_rate": (
                "cases with non-empty mathematical final_response / all cases"
            ),
            "primary_success_rate": "primary outcomes / all cases",
            "degraded_salvage_rate": (
                "degraded_candidate_salvage outcomes / all cases"
            ),
            "model_call_success_rate": (
                "completed dispatched model calls / dispatched model calls"
            ),
            "p50_p95_latency_seconds": "case latency percentiles",
            "p50_p95_model_calls": "per-case model-call percentiles",
        },
        "historical_reliability_snapshot": _historical_reliability_snapshot(),
        "failure_taxonomy": {
            "transport": {
                "fixture": "reliability",
                "codes": [
                    "network_connect_failure",
                    "network_read_timeout",
                    "empty_response",
                ],
            },
            "schema": {
                "fixture": "reliability",
                "codes": ["candidate_schema_invalid"],
            },
            "logic": {
                "fixture": "contract_adversarial",
                "categories": ["tool_claim", "candidate_conflict"],
            },
            "verification": {
                "fixture": "contract_adversarial",
                "categories": ["candidate_conflict"],
            },
            "formatting": {
                "fixture": "contract_adversarial",
                "categories": ["structured_output_pressure"],
            },
        },
        "privacy": {
            "contains_credentials": False,
            "contains_absolute_paths": False,
            "contains_private_reasoning_transcripts": False,
        },
    }


def _dataset_record(name: str, path: Path) -> dict[str, Any]:
    items = _load_items(path)
    categories = Counter(
        str(
            item.get(
                "domain",
                item.get(
                    "category",
                    item.get("failure_family", item.get("status", "unspecified")),
                ),
            )
        )
        for item in items
    )
    record = _file_record(path)
    record.update(
        {
            "name": name,
            "case_count": len(items),
            "categories": dict(sorted(categories.items())),
        }
    )
    return record


def _load_items(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain an object")
    cases = payload.get("cases", [])
    if not isinstance(cases, list):
        raise ValueError(f"{path.name} cases must be a list")
    return cases


def _historical_reliability_snapshot() -> dict[str, Any]:
    path = ROOT / "tests" / "fixtures" / "phase0_0729_live_regressions.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload["cases"]
    statuses = Counter(str(case.get("status", "unknown")) for case in cases)
    completed = [
        case for case in cases
        if case.get("status") in {"success", "failed"}
    ]
    return {
        "source_dataset": _relative_path(path),
        "status_counts": dict(sorted(statuses.items())),
        "completed_case_count": len(completed),
        "success_rate_on_completed": (
            round(statuses["success"] / len(completed), 6)
            if completed
            else 0.0
        ),
        "known_failure_classes": sorted(
            {
                str(case["root_failure"])
                for case in cases
                if case.get("root_failure")
            }
        ),
    }


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "path": _relative_path(path),
        "bytes": path.stat().st_size,
        "sha256": sha256(path.read_bytes()).hexdigest(),
    }


def _relative_path(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def write_manifest(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(build_manifest(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    write_manifest(args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
