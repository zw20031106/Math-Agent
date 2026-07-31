"""Compare real concurrency 1/2/4 profiles against the frozen Phase 2 gate.

The script intentionally consumes persisted profiles instead of constructing a
new online client.  A live run can be produced with the official runner, then
this deterministic comparison can be executed inside the disconnected
evaluation image.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


MAX_CONCURRENCY = 16
MIN_CANDIDATE_FORMATION_RATE = 0.95
MAX_ANSWER_PRODUCTION_DROP = 0.05
MAX_ACCURACY_DROP = 0.05


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"profile must be an object: {path}")
    return payload


def _rate(profile: dict[str, Any], *keys: str) -> float:
    value: Any = profile
    for key in keys:
        if not isinstance(value, dict):
            return 0.0
        value = value.get(key)
    return float(value or 0.0)


def compare(profiles: dict[int, dict[str, Any]]) -> dict[str, Any]:
    missing = sorted({1, 2, 4} - set(profiles))
    if missing:
        raise ValueError(f"profiles missing concurrency levels: {missing}")
    peak_values = {
        level: int(
            _rate(profile, "manifest", "preflight", "scheduler_peak")
            or _rate(profile, "scheduler", "peak")
            or _rate(profile, "max_peak_concurrency")
        )
        for level, profile in profiles.items()
    }
    formation = {
        level: _rate(profile, "candidate_acceptance_rate")
        for level, profile in profiles.items()
    }
    answer_rates = {
        level: _rate(profile, "success_rate")
        for level, profile in profiles.items()
    }
    accuracy_rates = {
        level: _rate(profile, "answer_match_rate_on_persisted_cases")
        for level, profile in profiles.items()
    }
    result = {
        "schema_version": "phase2-capacity-gate-1.0",
        "levels": [1, 2, 4],
        "frozen_gate": {
            "max_physical_concurrency": MAX_CONCURRENCY,
            "min_candidate_formation_rate": MIN_CANDIDATE_FORMATION_RATE,
            "max_answer_production_drop_vs_concurrency_1": (
                MAX_ANSWER_PRODUCTION_DROP
            ),
            "max_accuracy_drop_vs_concurrency_1": MAX_ACCURACY_DROP,
        },
        "observed": {
            "peak_physical_concurrency": peak_values,
            "candidate_formation_rate": formation,
            "answer_production_rate": answer_rates,
            "accuracy_rate": accuracy_rates,
        },
    }
    drops = {
        "answer_production_drop_at_4": max(
            0.0,
            answer_rates[1] - answer_rates[4],
        ),
        "accuracy_drop_at_4": max(
            0.0,
            accuracy_rates[1] - accuracy_rates[4],
        ),
    }
    result["comparison"] = drops
    result["passed"] = bool(
        all(value <= MAX_CONCURRENCY for value in peak_values.values())
        and all(
            formation[level] >= MIN_CANDIDATE_FORMATION_RATE
            for level in (1, 2, 4)
        )
        and drops["answer_production_drop_at_4"]
        <= MAX_ANSWER_PRODUCTION_DROP
        and drops["accuracy_drop_at_4"] <= MAX_ACCURACY_DROP
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency-1", required=True, type=Path)
    parser.add_argument("--concurrency-2", required=True, type=Path)
    parser.add_argument("--concurrency-4", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = compare(
        {
            1: _read(args.concurrency_1),
            2: _read(args.concurrency_2),
            4: _read(args.concurrency_4),
        }
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
