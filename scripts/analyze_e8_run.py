"""Analyze a persisted full-run directory using the E8 metric contract.

The case runner deliberately keeps public output separate from its manifest.
This adapter joins the two read-only, validates every public case again, and
reconstructs ``BenchmarkRecord`` objects from the manifest's recorded metrics.
It never infers a score or a missing model event from the public answer.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mathforge.benchmark import (  # noqa: E402
    BenchmarkCase,
    BenchmarkRecord,
    benchmark_record_from_dict,
    load_jsonl,
    preflight_benchmark_cases,
)
from mathforge.evaluation.e8 import (  # noqa: E402
    E8_SCHEMA_VERSION,
    summarize_e8,
)
from scripts.run_case_outputs import validate_case_output  # noqa: E402


RUN_MANIFEST_FILENAME = "run_manifest.json"


def analyze_run(
    run_dir: Path,
    input_path: Path,
) -> dict[str, Any]:
    manifest = _read_object(run_dir / RUN_MANIFEST_FILENAME, "run manifest")
    cases = load_jsonl(input_path)
    cases_by_id = {case.idx: case for case in cases}
    entries = manifest.get("cases", {})
    if not isinstance(entries, dict):
        raise ValueError("run manifest cases must be an object")

    validation_errors: list[str] = []
    records: list[BenchmarkRecord] = []
    missing_case_ids: list[str] = []
    for case in cases:
        entry = entries.get(case.idx)
        if not isinstance(entry, dict):
            missing_case_ids.append(case.idx)
            continue
        output_name = str(entry.get("output_file", f"{case.idx}.json"))
        output_path = run_dir / output_name
        try:
            public = validate_case_output(output_path, case.idx)
        except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
            validation_errors.append(
                f"{case.idx}:{type(error).__name__}:{_safe_message(error)}"
            )
            continue
        score = entry.get("score")
        metrics = entry.get("run_metrics")
        if not isinstance(score, dict) or not _score_is_complete(score):
            validation_errors.append(f"{case.idx}:manifest_score_missing")
            continue
        if not isinstance(metrics, dict) or not metrics:
            validation_errors.append(f"{case.idx}:manifest_run_metrics_missing")
            continue
        result = {
            "final_response": public["final_response"],
            "trace": public["trace"],
            "run_metrics": metrics,
        }
        payload = {
            "case": _case_payload(case),
            "result": result,
            "latency_seconds": float(entry.get("latency_seconds") or 0.0),
            "json_valid": True,
            "score": score,
            "request_fingerprint": str(entry.get("request_fingerprint", "")),
            "run_metrics": metrics,
            "pollution": {},
            "repetition_index": int(entry.get("repetition_index", 0)),
            "random_seed": int(manifest.get("seed", 0)),
        }
        try:
            records.append(benchmark_record_from_dict(payload))
        except (TypeError, ValueError, KeyError) as error:
            validation_errors.append(
                f"{case.idx}:record_reconstruction:{type(error).__name__}"
            )

    preflight = preflight_benchmark_cases(
        cases,
        allow_invalid_expected=True,
        minimum_auto_score_coverage=0.0,
    )
    summary = summarize_e8(records)
    findings: list[str] = []
    if preflight.invalid_expected_count:
        findings.append("invalid_expected_answers_are_explicitly_unscored")
    if preflight.auto_score_coverage < 0.95:
        findings.append("automatic_score_coverage_below_release_threshold")
    if missing_case_ids:
        findings.append("run_manifest_has_missing_cases")
    if validation_errors:
        findings.append("public_or_manifest_records_need_review")
    preflight_report = manifest.get("preflight", {})
    if not isinstance(preflight_report, dict) or preflight_report.get("status") != "passed":
        findings.append("model_preflight_blocked_before_case_execution")
    findings.extend(
        (
            "paired_ablation_evidence_not_included_in_this_full_run",
            "human_mathematical_review_not_included_in_this_full_run",
        )
    )
    return {
        "schema_version": E8_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run": {
            "name": run_dir.name,
            "status": manifest.get("status"),
            "case_count_expected": len(cases),
            "case_count_manifest": len(entries),
            "case_count_analyzed": len(records),
            "input_sha256": manifest.get("input_sha256", ""),
            "config_sha256": manifest.get("config_sha256", ""),
            "model_identity": manifest.get("model_identity", {}),
            "model_preflight": preflight_report,
            "attempts": [
                {
                    "attempt_id": item.get("attempt_id"),
                    "status": item.get("status"),
                    "failed_level": item.get("preflight", {}).get("failed_level")
                    if isinstance(item.get("preflight"), dict)
                    else None,
                }
                for item in manifest.get("attempts", [])
                if isinstance(item, dict)
            ],
        },
        "benchmark_preflight": preflight.to_dict(),
        "public_output_validation": {
            "valid_case_count": len(records),
            "validation_error_count": len(validation_errors),
            "validation_errors": validation_errors,
            "missing_case_ids": missing_case_ids,
        },
        "summary": summary,
        "findings": list(dict.fromkeys(findings)),
        "release_policy": {
            "competition_status_remains_candidate_unvalidated": True,
            "freeze_gate_evaluated": False,
            "reason": "A full run alone cannot establish repeated paired ablations or human review.",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze a persisted E8 full run.")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = analyze_run(args.run_dir, args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is unreadable") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _case_payload(case: BenchmarkCase) -> dict[str, Any]:
    return {
        "idx": case.idx,
        "problem": case.problem,
        "expected_answer": case.expected_answer,
        "subject": case.subject,
        "problem_type": case.problem_type,
        "answer_type": case.answer_type,
        "scorer": case.scorer,
    }


def _score_is_complete(score: dict[str, Any]) -> bool:
    return {
        "scored",
        "correct",
        "reason",
        "actual",
        "expected",
        "scorer",
        "error",
    }.issubset(score)


def _safe_message(error: BaseException) -> str:
    message = str(error).replace("\\", "/")
    return message.rsplit("/", 1)[-1]


__all__ = ["analyze_run", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
