from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mathforge.evaluation.scoring import score_response  # noqa: E402


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
            if path.name != "run_manifest.json" and path.stem in dataset
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
    scheduler_peaks = [item["provider_scheduler_peak"] for item in cases]
    public_matches = [
        item["answer_matches_expected"]
        for item in cases
        if item["answer_matches_expected"] is not None
    ]
    correct_answers = sum(public_matches)
    manifest_path = run_dir / "run_manifest.json"
    manifest = _read_json(manifest_path) if manifest_path.is_file() else {}
    config_path = ROOT / "config" / "competition.json"
    profiled_config_sha256 = _file_sha256(config_path)
    run_config_sha256 = str(manifest.get("config_sha256", ""))
    config_binding = {
        "run_config_sha256": run_config_sha256,
        "profiled_config_sha256": profiled_config_sha256,
        "matches_current": bool(run_config_sha256)
        and run_config_sha256 == profiled_config_sha256,
    }

    profile = {
        "schema_version": "1.0",
        "run_dir": _public_path(run_dir),
        "dataset_sha256": _file_sha256(dataset_path),
        "config_binding": config_binding,
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
        "max_peak_concurrency": max(scheduler_peaks, default=0),
        "answer_scoring": {
            "persisted_cases": len(cases),
            "scored_outputs": len(public_matches),
            "correct_outputs": correct_answers,
            "coverage": _ratio(len(public_matches), len(cases)),
            "accuracy_on_scored_outputs": _ratio(
                correct_answers,
                len(public_matches),
            ),
        },
        "answer_match_rate_on_persisted_cases": _ratio(
            correct_answers,
            len(cases),
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
            _comparison_summary(path, expected_ids=set(dataset))
            for path in comparison_dirs
        ],
    }
    evidence = {
        "schema_version": "1.0",
        "dataset": _file_record(dataset_path),
        "config": _file_record(config_path),
        "config_binding": config_binding,
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
    model_activity = _last_event(trace, "model_activity")
    final = _last_event(trace, "final_answer_selected")
    terminal = _last_event(trace, "run_completed")
    parsed = _last_event(trace, "problem_parsed")
    identifier = str(payload.get("id", path.stem))
    dataset_case = dataset.get(identifier, {})
    expected = str(dataset_case.get("answer", ""))
    answer = str(
        final.get("public_solution", {}).get("final_answer", "")
        if isinstance(final.get("public_solution"), dict)
        else ""
    )
    answer_type = str(
        parsed.get(
            "answer_type",
            dataset_case.get("answer_type", "expression"),
        )
    )
    score = (
        score_response(
            expected,
            f"Final answer: {answer}",
            answer_type=answer_type,
            scorer=dataset_case.get("scorer"),
        )
        if expected and answer
        else None
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
        "provider_scheduler_peak": int(
            budget.get("provider_scheduler_peak", 0)
        ),
        "model_call_records": list(
            model_activity.get("calls", budget.get("model_calls", []))
        ),
        "expected_answer": expected,
        "public_answer": answer,
        "answer_type": answer_type,
        "answer_matches_expected": (
            score.correct
            if score is not None and score.scored and not score.error
            else None
        ),
        "answer_score": score.to_dict() if score is not None else {},
        "output_sha256": _file_sha256(path),
    }


def _comparison_summary(
    directory: Path,
    *,
    expected_ids: set[str],
) -> dict[str, Any]:
    paths = [
        path
        for path in directory.glob("*.json")
        if path.name != "run_manifest.json" and path.stem in expected_ids
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
        "run_dir": _public_path(directory),
        "persisted_case_count": len(paths),
        "status_counts": dict(sorted(statuses.items())),
        "manifest_status": manifest.get("status", "missing"),
        "attempt_count": manifest.get("attempt_count", 0),
    }


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
        "path": _public_path(path),
        "bytes": path.stat().st_size,
        "sha256": _file_sha256(path),
    }


def _public_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return f"<external>/{resolved.name}"


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
    print(
        json.dumps(
            {
                "output": _public_path(args.output),
                "evidence_output": _public_path(args.evidence_output),
                "persisted_case_count": profile["persisted_case_count"],
                "output_coverage": profile["output_coverage"],
                "success_rate": profile["success_rate"],
                "freeze_config_match": profile["config_binding"][
                    "matches_current"
                ],
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
