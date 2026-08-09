from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping


_OFFICIAL_FIELDS = (
    "correct",
    "incorrect",
    "invalid",
    "request_count",
    "truncated_count",
)


def sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def extract_local_final_corpus(run_directory: Path) -> dict[str, Any]:
    """Build one record per final case, independent of resume attempts."""
    manifest_path = run_directory / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    final_cases = manifest.get("cases")
    if not isinstance(final_cases, dict):
        raise ValueError("run manifest cases must be a final case mapping")

    records: list[dict[str, Any]] = []
    for raw_id, case_record in sorted(
        final_cases.items(), key=lambda item: int(item[0])
    ):
        if not isinstance(case_record, dict):
            raise ValueError(f"case {raw_id} manifest record must be an object")
        output_name = str(case_record.get("output_file", f"{raw_id}.json"))
        output_path = run_directory / output_name
        output = json.loads(output_path.read_text(encoding="utf-8"))
        trace = output.get("trace", [])
        if not isinstance(trace, list):
            trace = []
        route = _last_event(trace, "route_planned")
        candidate_pool = _last_event(trace, "candidate_pool_initialized")
        metrics = case_record.get("run_metrics", {})
        score = case_record.get("score", {})
        records.append(
            {
                "id": int(raw_id),
                "status": str(case_record.get("status", output.get("status", ""))),
                "terminal_outcome": str(case_record.get("terminal_outcome", "")),
                "error_code": str(metrics.get("error_code", "")),
                "correct": bool(score.get("correct", False)),
                "scored": bool(score.get("scored", False)),
                "router_source": str(route.get("router_source", "")),
                "router_fallback_reason": str(
                    route.get("router_fallback_reason", "")
                ),
                "submitted_candidate_count": int(
                    candidate_pool.get("submitted_count", 0) or 0
                ),
                "attempt_id": str(case_record.get("attempt_id", "")),
                "resume_source": str(case_record.get("resume_source", "")),
                "output_file": output_name,
                "output_sha256": sha256_file(output_path),
            }
        )

    attempt_metrics = []
    for attempt in manifest.get("attempts", []):
        if not isinstance(attempt, dict):
            continue
        summary = attempt.get("summary", {})
        attempt_metrics.append(
            {
                "attempt_id": str(attempt.get("attempt_id", "")),
                "status": str(attempt.get("status", "")),
                "case_count": int(summary.get("case_count", 0) or 0),
                "accuracy": float(summary.get("accuracy", 0.0) or 0.0),
                "terminal_status_counts": dict(
                    summary.get("terminal_status_counts", {})
                ),
            }
        )
    return {
        "schema_version": "1.0",
        "corpus_kind": "final_case_corpus",
        "source_manifest": {
            "name": manifest_path.name,
            "sha256": sha256_file(manifest_path),
            "input_sha256": str(manifest.get("input_sha256", "")),
            "config_sha256": str(manifest.get("config_sha256", "")),
            "run_contract": manifest.get("run_contract", {}),
        },
        "attempt_metrics": attempt_metrics,
        "corpus_records": records,
        "corpus_metrics": aggregate_local_final_corpus(records),
    }


def aggregate_local_final_corpus(
    records: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    items = list(records)
    status_counts = Counter(str(item.get("status", "")) for item in items)
    error_counts = Counter(
        str(item.get("error_code", ""))
        for item in items
        if str(item.get("error_code", ""))
    )
    return {
        "case_count": len(items),
        "correct_count": sum(bool(item.get("correct")) for item in items),
        "status_counts": dict(sorted(status_counts.items())),
        "error_code_counts": dict(sorted(error_counts.items())),
        "router_llm_accepted_count": sum(
            str(item.get("router_source", "")) == "llm_router" for item in items
        ),
        "dual_candidate_count": sum(
            int(item.get("submitted_candidate_count", 0) or 0) >= 2
            for item in items
        ),
    }


def parse_official_evaluation_log(text: str) -> dict[str, Any]:
    """Extract the final official summary from timestamp-prefixed logs."""
    values: dict[str, int] = {}
    for field in _OFFICIAL_FIELDS:
        matches = re.findall(rf'"{field}"\s*:\s*(\d+)', text)
        if not matches:
            raise ValueError(f"official evaluation log is missing {field}")
        values[field] = int(matches[-1])
    total = values["correct"] + values["incorrect"] + values["invalid"]
    requests = values["request_count"]
    return {
        "case_count": total,
        **values,
        "valid_count": values["correct"] + values["incorrect"],
        "invalid_rate": values["invalid"] / total if total else 0.0,
        "truncated_rate": values["truncated_count"] / requests if requests else 0.0,
    }


def regression_case_snapshot(
    run_directory: Path,
    corpus: Mapping[str, Any],
    case_id: int,
) -> dict[str, Any]:
    records = corpus.get("corpus_records", [])
    record = next(
        (item for item in records if int(item.get("id", -1)) == case_id),
        None,
    )
    if not isinstance(record, dict):
        raise ValueError(f"missing final corpus case {case_id}")
    output = json.loads(
        (run_directory / str(record["output_file"])).read_text(encoding="utf-8")
    )
    trace = output.get("trace", [])
    summaries = _last_event(trace if isinstance(trace, list) else [], "candidate_summaries")
    candidates = []
    for candidate in summaries.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        candidates.append(
            {
                "candidate_id": str(candidate.get("candidate_id", "")),
                "role": str(candidate.get("role", "")),
                "status": str(candidate.get("status", "")),
                "rejection_category": str(candidate.get("rejection_category", "")),
            }
        )
    return {
        "id": case_id,
        "status": str(output.get("status", record.get("status", ""))),
        "final_response": str(output.get("final_response", "")),
        "correct": bool(record.get("correct", False)),
        "error_code": str(record.get("error_code", "")),
        "router_source": str(record.get("router_source", "")),
        "router_fallback_reason": str(record.get("router_fallback_reason", "")),
        "candidates": candidates,
        "output_sha256": str(record.get("output_sha256", "")),
        "privacy": "redacted_public_diagnostics_only",
    }


def _last_event(trace: list[Any], event: str) -> dict[str, Any]:
    for item in reversed(trace):
        if isinstance(item, dict) and item.get("event") == event:
            return item
    return {}
