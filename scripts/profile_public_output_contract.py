from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


PUBLIC_FIELDS = {"id", "status", "final_response", "trace"}


def profile_public_output_contract(
    run_dir: Path,
    *,
    dataset_path: Path,
    expected_cases: int,
) -> dict[str, Any]:
    dataset_sha256 = _file_sha256(dataset_path)
    case_paths = sorted(
        (
            path
            for path in run_dir.glob("*.json")
            if path.name != "run_manifest.json" and path.stem.isdigit()
        ),
        key=lambda path: int(path.stem),
    )
    statuses: Counter[str] = Counter()
    first_events: Counter[str] = Counter()
    event_counts: Counter[str] = Counter()
    event_chars: dict[str, list[int]] = defaultdict(list)
    trace_chars: list[int] = []
    trace_event_counts: list[int] = []
    response_chars: list[int] = []
    contract_valid = 0
    multiline_responses = 0
    canonical_answers = 0
    latex_answers = 0
    candidate_content_cases = 0
    solution_process_first = 0
    output_digests: list[str] = []

    for path in case_paths:
        payload = _read_json(path)
        output_digests.append(_file_sha256(path))
        statuses[str(payload.get("status", "missing"))] += 1
        if set(payload) == PUBLIC_FIELDS:
            contract_valid += 1
        final_response = str(payload.get("final_response", ""))
        response_chars.append(len(final_response))
        multiline_responses += "\n" in final_response.strip()
        canonical_answers += "Final answer:" in final_response
        latex_answers += bool(
            "$" in final_response
            or r"\(" in final_response
            or r"\[" in final_response
        )

        trace = payload.get("trace", [])
        if not isinstance(trace, list):
            trace = []
        trace_chars.append(_serialized_chars(trace))
        trace_event_counts.append(len(trace))
        first_name = (
            str(trace[0].get("event", "invalid"))
            if trace and isinstance(trace[0], dict)
            else "missing"
        )
        first_events[first_name] += 1
        solution_process_first += first_name == "solution_process"
        has_candidate_content = False
        for event in trace:
            if not isinstance(event, dict):
                event_counts["invalid"] += 1
                continue
            name = str(event.get("event", "missing"))
            event_counts[name] += 1
            event_chars[name].append(_serialized_chars(event))
            if name == "candidate_summaries":
                candidates = event.get("candidates", [])
                has_candidate_content = any(
                    isinstance(candidate, dict)
                    and bool(
                        candidate.get("public_solution_steps")
                        or candidate.get("public_final_answer")
                    )
                    for candidate in candidates
                    if isinstance(candidates, list)
                )
        candidate_content_cases += has_candidate_content

    manifest_path = run_dir / "run_manifest.json"
    return {
        "schema_version": "1.0",
        "purpose": "pre-T1 public output contract baseline",
        "source": {
            "run": f"<external>/{run_dir.name}",
            "dataset": f"<external>/{dataset_path.name}",
            "dataset_sha256": dataset_sha256,
            "run_manifest_sha256": (
                _file_sha256(manifest_path) if manifest_path.is_file() else ""
            ),
            "case_outputs_sha256": sha256(
                "\n".join(output_digests).encode("ascii")
            ).hexdigest(),
        },
        "coverage": {
            "expected_cases": expected_cases,
            "persisted_cases": len(case_paths),
            "public_contract_valid_cases": contract_valid,
            "status_counts": dict(sorted(statuses.items())),
        },
        "final_response": {
            "characters": _distribution(response_chars),
            "multiline_cases": multiline_responses,
            "canonical_answer_block_cases": canonical_answers,
            "latex_cases": latex_answers,
        },
        "trace": {
            "characters": _distribution(trace_chars),
            "events_per_case": _distribution(trace_event_counts),
            "first_event_counts": dict(sorted(first_events.items())),
            "solution_process_first_cases": solution_process_first,
            "candidate_content_cases": candidate_content_cases,
            "event_counts": dict(sorted(event_counts.items())),
            "largest_event_types": [
                {
                    "event": name,
                    "count": len(values),
                    "p50_chars": _percentile(values, 50),
                    "p95_chars": _percentile(values, 95),
                    "max_chars": max(values, default=0),
                }
                for name, values in sorted(
                    event_chars.items(),
                    key=lambda item: max(item[1], default=0),
                    reverse=True,
                )[:10]
            ],
        },
    }


def _distribution(values: list[int]) -> dict[str, float | int]:
    return {
        "p50": _percentile(values, 50),
        "p95": _percentile(values, 95),
        "max": max(values, default=0),
    }


def _percentile(values: list[int], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * percentile / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 6)


def _serialized_chars(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return payload


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
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    profile = profile_public_output_contract(
        args.run_dir,
        dataset_path=args.dataset,
        expected_cases=args.expected_cases,
    )
    _write_json(args.output, profile)
    print(
        json.dumps(
            {
                "output": args.output.name,
                "persisted_cases": profile["coverage"]["persisted_cases"],
                "status_counts": profile["coverage"]["status_counts"],
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
