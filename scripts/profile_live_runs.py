from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import statistics
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mathforge.verification.answer_normalization import canonical_answer  # noqa: E402


def profile_run(
    run_dir: Path,
    *,
    dataset_path: Path,
    expected_cases: int,
    comparison_dirs: list[Path],
) -> tuple[dict[str, Any], dict[str, Any]]:
    dataset = _load_dataset(dataset_path)
    case_paths = sorted(
        (
            path
            for path in run_dir.glob("*.json")
            if path.name != "run_manifest.json"
        ),
        key=lambda path: path.stem,
    )
    cases = [_profile_case(path, dataset) for path in case_paths]
    statuses = Counter(item["status"] for item in cases)
    health_counts = Counter(item["health"] for item in cases)
    all_calls = [
        call
        for item in cases
        for call in item["model_call_records"]
    ]
    completed_calls = sum(
        call.get("status") == "completed" for call in all_calls
    )
    dispatched_calls = len(all_calls)
    selected_cases = sum(bool(item["selected_candidate_id"]) for item in cases)
    calls_per_case = [item["used_calls"] for item in cases]
    latencies = [item["elapsed_seconds"] for item in cases]
    public_matches = [
        item["answer_matches_expected"]
        for item in cases
        if item["answer_matches_expected"] is not None
    ]
    manifest_path = run_dir / "run_manifest.json"
    manifest = _read_json(manifest_path) if manifest_path.is_file() else {}

    profile = {
        "schema_version": "1.0",
        "run_dir": str(run_dir.resolve()),
        "dataset_sha256": _file_sha256(dataset_path),
        "expected_case_count": expected_cases,
        "persisted_case_count": len(cases),
        "output_coverage": _ratio(len(cases), expected_cases),
        "status_counts": dict(sorted(statuses.items())),
        "success_rate": _ratio(statuses["success"], len(cases)),
        "health_counts": dict(sorted(health_counts.items())),
        "health_trace_completeness": _ratio(
            sum(bool(item["health"]) for item in cases),
            len(cases),
        ),
        "candidate_acceptance_rate": _ratio(selected_cases, len(cases)),
        "model_dispatch": {
            "calls": dispatched_calls,
            "completed": completed_calls,
            "failed": dispatched_calls - completed_calls,
            "success_rate": _ratio(completed_calls, dispatched_calls),
            "transport_attempts": sum(
                int(call.get("transport_attempts", 0))
                for call in all_calls
            ),
            "failure_codes": dict(
                sorted(
                    Counter(
                        str(call.get("failure_code", ""))
                        for call in all_calls
                        if call.get("failure_code")
                    ).items()
                )
            ),
        },
        "calls_per_case": {
            "p50": _percentile(calls_per_case, 50),
            "p95": _percentile(calls_per_case, 95),
            "max": max(calls_per_case, default=0),
        },
        "latency_seconds": {
            "p50": _percentile(latencies, 50),
            "p95": _percentile(latencies, 95),
            "max": max(latencies, default=0.0),
        },
        "answer_match_rate_on_persisted_cases": _ratio(
            sum(public_matches),
            len(public_matches),
        ),
        "manifest": {
            "schema_version": manifest.get("schema_version", ""),
            "status": manifest.get("status", ""),
            "attempt_count": manifest.get("attempt_count", 0),
            "model_identity": manifest.get("model_identity", {}),
            "preflight": manifest.get("preflight", {}),
        },
        "cases": cases,
        "comparisons": [
            _comparison_summary(path) for path in comparison_dirs
        ],
    }
    evidence = {
        "schema_version": "1.0",
        "dataset": _file_record(dataset_path),
        "config": _file_record(ROOT / "config" / "competition.json"),
        "run_manifest": (
            _file_record(manifest_path) if manifest_path.is_file() else {}
        ),
        "case_outputs": [_file_record(path) for path in case_paths],
        "comparison_manifests": [
            _file_record(path / "run_manifest.json")
            for path in comparison_dirs
            if (path / "run_manifest.json").is_file()
        ],
    }
    return profile, evidence


def _profile_case(
    path: Path,
    dataset: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    payload = _read_json(path)
    trace = payload.get("trace", [])
    health = _last_event(trace, "closed_loop_health")
    budget = _last_event(trace, "budget_summary")
    final = _last_event(trace, "final_answer_selected")
    terminal = _last_event(trace, "run_completed")
    identifier = str(payload.get("id", path.stem))
    expected = str(dataset.get(identifier, {}).get("answer", ""))
    answer = str(
        final.get("public_solution", {}).get("final_answer", "")
        if isinstance(final.get("public_solution"), dict)
        else ""
    )
    return {
        "id": payload.get("id"),
        "status": str(payload.get("status", "")),
        "health": str(health.get("health", "")),
        "outcome": str(terminal.get("outcome", "")),
        "selected_candidate_id": str(
            health.get("candidate_flow", {}).get(
                "selected_candidate_id",
                "",
            )
            if isinstance(health.get("candidate_flow"), dict)
            else ""
        ),
        "primary": str(
            health.get("candidate_flow", {}).get("primary", "")
            if isinstance(health.get("candidate_flow"), dict)
            else ""
        ),
        "proof_status": str(
            health.get("closure", {}).get("proof_status", "")
            if isinstance(health.get("closure"), dict)
            else ""
        ),
        "degradation_reasons": list(
            health.get("closure", {}).get("degradation_reasons", [])
            if isinstance(health.get("closure"), dict)
            else []
        ),
        "root_failure_codes": list(
            health.get("model_dispatch", {}).get(
                "root_failure_codes",
                [],
            )
            if isinstance(health.get("model_dispatch"), dict)
            else []
        ),
        "used_calls": int(budget.get("used_calls", 0)),
        "elapsed_seconds": float(budget.get("elapsed_seconds", 0.0)),
        "model_call_records": list(budget.get("model_calls", [])),
        "expected_answer": expected,
        "public_answer": answer,
        "answer_matches_expected": (
            _answers_match(expected, answer) if expected and answer else None
        ),
        "output_sha256": _file_sha256(path),
    }


def _comparison_summary(directory: Path) -> dict[str, Any]:
    paths = [
        path
        for path in directory.glob("*.json")
        if path.name != "run_manifest.json"
    ]
    statuses = Counter()
    for path in paths:
        try:
            payload = _read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            statuses["unreadable"] += 1
            continue
        statuses[str(payload.get("status", "missing"))] += 1
    manifest_path = directory / "run_manifest.json"
    manifest = _read_json(manifest_path) if manifest_path.is_file() else {}
    return {
        "run_dir": str(directory.resolve()),
        "persisted_case_count": len(paths),
        "status_counts": dict(sorted(statuses.items())),
        "manifest_status": manifest.get("status", "missing"),
        "attempt_count": manifest.get("attempt_count", 0),
    }


def _answers_match(expected: str, actual: str) -> bool:
    return canonical_answer(expected, "expression") == canonical_answer(
        actual,
        "expression",
    )


def _load_dataset(path: Path) -> dict[str, dict[str, Any]]:
    result = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines()
    ):
        if not line.strip():
            continue
        item = json.loads(line)
        identifier = str(item.get("idx", line_number))
        result[identifier] = {
            **item,
            "answer": item.get("expected_answer", item.get("answer", "")),
        }
    return result


def _last_event(trace: Any, name: str) -> dict[str, Any]:
    if not isinstance(trace, list):
        return {}
    return next(
        (
            event
            for event in reversed(trace)
            if isinstance(event, dict) and event.get("event") == name
        ),
        {},
    )


def _percentile(values: list[float | int], percentile: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * percentile / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return round(
        ordered[lower] * (1 - weight) + ordered[upper] * weight,
        6,
    )


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": _file_sha256(path),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--expected-cases", type=int, required=True)
    parser.add_argument(
        "--compare-run",
        action="append",
        type=Path,
        default=[],
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    args = parser.parse_args()
    profile, evidence = profile_run(
        args.run_dir,
        dataset_path=args.dataset,
        expected_cases=args.expected_cases,
        comparison_dirs=args.compare_run,
    )
    _write_json(args.output, profile)
    _write_json(args.evidence_output, evidence)
    print(json.dumps(profile, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
