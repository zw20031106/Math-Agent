from __future__ import annotations

from collections import Counter
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
import tarfile
from typing import Any, Mapping

from mathforge.evaluation.artifacts import validate_artifact
from mathforge.evaluation.scoring import score_response


CASE_FAILURE_TAXONOMY = (
    "parser_error",
    "router_error",
    "solver_wrong",
    "protocol_invalid",
    "truncated",
    "provider_timeout",
    "candidate_rejected",
    "wrong_arbitration",
    "trace_invalid",
    "fallback",
)
_FAILURE_PRECEDENCE = (
    "parser_error",
    "router_error",
    "protocol_invalid",
    "provider_timeout",
    "truncated",
    "candidate_rejected",
    "wrong_arbitration",
    "solver_wrong",
    "trace_invalid",
    "fallback",
)
_SOURCE_ROOT_FILES = ("main.py", "llm_client.py", "user_agent.py")


def competition_source_fingerprint(
    root: Path,
    *,
    revision: str | None = None,
) -> tuple[int, str]:
    """Hash competition Python sources from a worktree or an immutable commit."""
    root = root.resolve()
    if revision is None:
        paths = [root / name for name in _SOURCE_ROOT_FILES]
        paths.extend((root / "mathforge").rglob("*.py"))
        records = [
            (path.relative_to(root).as_posix(), path.read_bytes())
            for path in paths
            if path.is_file()
        ]
    else:
        archive = subprocess.run(
            [
                "git",
                "archive",
                "--format=tar",
                revision,
                "--",
                *_SOURCE_ROOT_FILES,
                "mathforge",
            ],
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout
        with tarfile.open(fileobj=BytesIO(archive), mode="r:") as bundle:
            records = [
                (member.name, bundle.extractfile(member).read())
                for member in bundle.getmembers()
                if member.isfile() and member.name.endswith(".py")
            ]

    digest = sha256()
    for name, raw in sorted(records):
        normalized = raw.replace(b"\r\n", b"\n")
        encoded_name = name.encode("utf-8")
        digest.update(len(encoded_name).to_bytes(8, "big"))
        digest.update(encoded_name)
        digest.update(len(normalized).to_bytes(8, "big"))
        digest.update(normalized)
    return len(records), digest.hexdigest()


def audit_official_artifact(
    artifact: Mapping[str, Any],
    frozen_snapshot: Mapping[str, Any],
    *,
    proof_reviews: Mapping[str, Any] | None = None,
    evidence_origin: str,
    root: Path,
) -> dict[str, Any]:
    """Build a per-case audit and decide whether evidence may be activated."""
    artifact_payload = dict(artifact)
    baseline = dict(frozen_snapshot.get("baseline_candidate", {}))
    errors = list(validate_artifact(artifact_payload))
    errors.extend(
        _fingerprint_errors(
            artifact_payload,
            baseline,
            evidence_origin=evidence_origin,
            root=root,
        )
    )

    records = artifact_payload.get("records", [])
    if not isinstance(records, list):
        records = []
    identifiers = [
        str(record.get("case", {}).get("idx", ""))
        for record in records
        if isinstance(record, dict)
    ]
    if not records:
        errors.append("artifact has no per-case records")
    if len(identifiers) != len(set(identifiers)):
        errors.append("artifact contains duplicate case identifiers")
    raw_summary = artifact_payload.get("summary", {})
    summary = raw_summary if isinstance(raw_summary, Mapping) else {}
    summary_count = summary.get("case_count")
    if isinstance(summary_count, int) and summary_count != len(records):
        errors.append("artifact summary case count does not match records")

    reviews = proof_reviews or {}
    case_audits = [
        _audit_case(record, reviews)
        for record in records
        if isinstance(record, dict)
    ]
    for case in case_audits:
        case_id = case["case_id"]
        if not case["lineage_complete"]:
            errors.append(f"case {case_id} lineage is incomplete")
        if case["verdict"]["status"] == "pending_human_review":
            errors.append(f"case {case_id} proof review is incomplete")
        if case["verdict"]["status"] == "unscored":
            errors.append(f"case {case_id} non-proof auto-score is unavailable")

    errors = list(dict.fromkeys(errors))
    label_counts = Counter(
        label
        for case in case_audits
        for label in case["failure_classification"]["labels"]
    )
    eligible = not errors
    return {
        "schema_version": "1.0",
        "artifact_sha256": str(artifact_payload.get("artifact_sha256", "")),
        "evidence_origin": evidence_origin,
        "fingerprint_binding": {
            "expected": baseline,
            "observed": {
                "git_commit": str(artifact_payload.get("git_commit", "")),
                "code_dirty": artifact_payload.get("code_dirty"),
                "config_sha256": str(artifact_payload.get("config_sha256", "")),
                "prompt_sha256": str(artifact_payload.get("prompt_sha256", "")),
                "skill_sha256": str(artifact_payload.get("skill_sha256", "")),
                "dataset_sha256": str(artifact_payload.get("dataset_sha256", "")),
            },
        },
        "case_failure_taxonomy": list(CASE_FAILURE_TAXONOMY),
        "cases": case_audits,
        "summary": {
            "case_count": len(case_audits),
            "proof_case_count": sum(case["is_proof"] for case in case_audits),
            "correct_count": sum(
                case["verdict"].get("correct") is True for case in case_audits
            ),
            "incorrect_count": sum(
                case["verdict"].get("correct") is False for case in case_audits
            ),
            "failure_label_counts": dict(sorted(label_counts.items())),
            "lineage_complete_count": sum(
                case["lineage_complete"] for case in case_audits
            ),
        },
        "active_baseline_eligible": eligible,
        "eligibility_errors": errors,
    }


def _fingerprint_errors(
    artifact: Mapping[str, Any],
    baseline: Mapping[str, Any],
    *,
    evidence_origin: str,
    root: Path,
) -> list[str]:
    errors: list[str] = []
    if evidence_origin != "official-platform-export":
        errors.append("evidence origin is not an official platform export")
    if artifact.get("code_dirty") is not False:
        errors.append("artifact code state is dirty or unobservable")
    fields = {
        "git_commit": "git_commit",
        "config_sha256": "config_sha256",
        "prompt_sha256": "prompt_sha256",
        "skill_sha256": "skill_sha256",
    }
    for artifact_field, baseline_field in fields.items():
        if str(artifact.get(artifact_field, "")) != str(
            baseline.get(baseline_field, "")
        ):
            errors.append(f"artifact {artifact_field} does not match frozen baseline")

    revision = str(artifact.get("git_commit", ""))
    try:
        source_count, source_hash = competition_source_fingerprint(
            root,
            revision=revision,
        )
    except (OSError, subprocess.CalledProcessError):
        errors.append("artifact source commit is unavailable for verification")
    else:
        if source_count != int(baseline.get("source_file_count", -1)):
            errors.append("artifact source file count does not match frozen baseline")
        if source_hash != str(baseline.get("source_sha256", "")):
            errors.append("artifact source fingerprint does not match frozen baseline")
    return errors


def _audit_case(
    record: Mapping[str, Any],
    proof_reviews: Mapping[str, Any],
) -> dict[str, Any]:
    raw_case = record.get("case", {})
    raw_result = record.get("result", {})
    case = dict(raw_case) if isinstance(raw_case, Mapping) else {}
    result = dict(raw_result) if isinstance(raw_result, Mapping) else {}
    trace = result.get("trace", [])
    events = [event for event in trace if isinstance(event, dict)] if isinstance(trace, list) else []
    case_id = str(case.get("idx", ""))
    response_mode = _last_value(events, "problem_parsed", "response_mode")
    problem_type = str(case.get("problem_type", "")) or str(
        _last_value(events, "problem_parsed", "problem_type")
    )
    is_proof = response_mode == "proof_full" or problem_type == "proof"
    candidates = _candidate_lineage(events)
    selected_id = str(_last_value(events, "final_answer_selected", "candidate_id"))
    fallback = bool(_last_event(events, "fallback_used"))
    final_candidate = {
        "kind": "candidate" if selected_id else "fallback" if fallback else "missing",
        "candidate_id": selected_id,
    }
    calls, calls_complete = _model_call_timeline(events, record)
    candidate_complete = fallback or (
        bool(selected_id)
        and any(item["candidate_id"] == selected_id for item in candidates)
    )
    trace_complete = bool(events) and events[-1].get("event") == "run_completed"
    lineage_complete = bool(case_id) and candidate_complete and calls_complete and trace_complete

    if is_proof:
        verdict = _proof_verdict(case_id, proof_reviews.get(case_id))
    else:
        verdict = _automatic_verdict(case, result)
    classification = _classify_case(
        record,
        events,
        candidates,
        selected_id,
        verdict,
        trace_complete=trace_complete,
    )
    return {
        "case_id": case_id,
        "input": {
            "problem": str(case.get("problem", "")),
            "problem_type": problem_type,
            "answer_type": case.get("answer_type"),
            "response_mode": response_mode,
            "expected_answer": case.get("expected_answer"),
        },
        "output": {
            "final_response": str(result.get("final_response", "")),
            "json_valid": bool(record.get("json_valid", False)),
        },
        "is_proof": is_proof,
        "final_candidate": final_candidate,
        "candidate_lineage": candidates,
        "model_call_timeline": calls,
        "lineage_complete": lineage_complete,
        "verdict": verdict,
        "failure_classification": classification,
    }


def _automatic_verdict(case: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    expected = case.get("expected_answer")
    if expected is None:
        return {"status": "unscored", "correct": None, "authority": "none"}
    try:
        scored = score_response(
            str(expected),
            str(result.get("final_response", "")),
            answer_type=case.get("answer_type"),
            scorer=case.get("scorer"),
        )
    except (TypeError, ValueError):
        return {"status": "unscored", "correct": None, "authority": "none"}
    return {
        "status": "completed" if scored.scored else "unscored",
        "correct": scored.correct if scored.scored else None,
        "authority": "deterministic_auto_score",
        "reason": scored.reason,
    }


def _proof_verdict(case_id: str, payload: Any) -> dict[str, Any]:
    pending = {
        "status": "pending_human_review",
        "correct": None,
        "authority": "two_independent_reviewers_then_adjudicator",
        "case_id": case_id,
        "reviews": [],
    }
    if not isinstance(payload, dict):
        return pending
    reviews = payload.get("reviews", [])
    if not isinstance(reviews, list) or len(reviews) < 2:
        return pending
    normalized = [_normalize_review(review) for review in reviews[:2]]
    if any(review is None for review in normalized):
        return pending
    first, second = normalized
    if first["reviewer_id"] == second["reviewer_id"]:
        return pending
    final = first["verdict"] if first["verdict"] == second["verdict"] else ""
    adjudication = None
    if not final:
        adjudication = _normalize_review(payload.get("adjudication"))
        if (
            adjudication is None
            or adjudication["reviewer_id"]
            in {first["reviewer_id"], second["reviewer_id"]}
        ):
            return pending
        final = adjudication["verdict"]
    public_reviews = [first, second]
    if adjudication is not None:
        public_reviews.append(adjudication)
    return {
        "status": "completed",
        "correct": final == "correct",
        "authority": "human_review",
        "case_id": case_id,
        "reviews": public_reviews,
    }


def _normalize_review(payload: Any) -> dict[str, str] | None:
    if not isinstance(payload, dict):
        return None
    reviewer_id = str(payload.get("reviewer_id", "")).strip()
    verdict = str(payload.get("verdict", "")).strip()
    signature = str(payload.get("signature", "")).strip()
    if not reviewer_id or verdict not in {"correct", "incorrect"} or not signature:
        return None
    return {
        "reviewer_id": reviewer_id,
        "verdict": verdict,
        "signature_sha256": sha256(signature.encode("utf-8")).hexdigest(),
    }


def _candidate_lineage(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    parent_links: list[tuple[str, str]] = []
    for event in events:
        if event.get("event") == "candidate_generated":
            candidate_id = str(event.get("candidate_id", ""))
            content = event.get("content", {})
            if candidate_id and isinstance(content, dict):
                states[candidate_id] = {
                    "candidate_id": candidate_id,
                    "role": str(event.get("role", "")),
                    "source": str(event.get("source", "")),
                    "content_digest": str(event.get("content_digest", "")),
                    "final_answer": str(content.get("final_answer", "")),
                    "status": "generated",
                    "reason_codes": [],
                    "parents": [],
                }
        if event.get("event") == "candidate_final_states":
            for item in event.get("candidates", []):
                if not isinstance(item, dict):
                    continue
                candidate_id = str(item.get("candidate_id", ""))
                if not candidate_id:
                    continue
                state = states.setdefault(
                    candidate_id,
                    {
                        "candidate_id": candidate_id,
                        "role": "",
                        "source": "",
                        "content_digest": "",
                        "final_answer": "",
                        "parents": [],
                    },
                )
                state["status"] = str(item.get("status", ""))
                state["version"] = int(item.get("version", 0) or 0)
                state["reason_codes"] = list(item.get("reason_codes", []))
        source_id = str(event.get("source_candidate_id", ""))
        proposed_id = str(event.get("proposed_candidate_id", ""))
        if source_id and proposed_id:
            parent_links.append((source_id, proposed_id))
    for source_id, proposed_id in parent_links:
        if proposed_id in states:
            states[proposed_id]["parents"] = list(
                dict.fromkeys([*states[proposed_id]["parents"], source_id])
            )
    return [states[key] for key in sorted(states)]


def _model_call_timeline(
    events: list[dict[str, Any]],
    record: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    budget = _last_event(events, "budget_summary")
    raw_calls = budget.get("model_call_records", budget.get("model_calls", []))
    if not isinstance(raw_calls, list):
        raw_calls = []
    calls = []
    for index, raw in enumerate(raw_calls, start=1):
        if not isinstance(raw, dict):
            continue
        calls.append(
            {
                "sequence": index,
                "logical_call_index": int(raw.get("logical_call_index", index) or index),
                "role": str(raw.get("role", raw.get("agent_role", ""))),
                "agent_id": str(raw.get("agent_id", "")),
                "turn_id": str(raw.get("turn_id", "")),
                "candidate_id": str(raw.get("candidate_id", "")),
                "stage": str(raw.get("stage", "")),
                "action": str(raw.get("action", raw.get("action_category", ""))),
                "status": str(raw.get("status", "")),
                "started_elapsed_seconds": float(raw.get("started_elapsed_seconds", 0.0) or 0.0),
                "queue_elapsed_seconds": float(raw.get("queue_elapsed_seconds", 0.0) or 0.0),
                "execution_elapsed_seconds": float(raw.get("execution_elapsed_seconds", 0.0) or 0.0),
                "total_elapsed_seconds": float(raw.get("total_elapsed_seconds", raw.get("elapsed_seconds", 0.0)) or 0.0),
                "finish_reason": str(raw.get("finish_reason", "")),
                "response_truncated": bool(raw.get("response_truncated", False)),
                "failure_code": str(raw.get("failure_code", "")),
            }
        )
    raw_metrics = record.get("run_metrics", {})
    metrics = raw_metrics if isinstance(raw_metrics, Mapping) else {}
    expected = int(metrics.get("model_calls", 0) or 0)
    observed = sum(
        bool(raw.get("logical_call_consumed", raw.get("dispatched", True)))
        for raw in raw_calls
        if isinstance(raw, dict)
    )
    return calls, observed == expected


def _classify_case(
    record: Mapping[str, Any],
    events: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    selected_id: str,
    verdict: Mapping[str, Any],
    *,
    trace_complete: bool,
) -> dict[str, Any]:
    labels: set[str] = set()
    raw_metrics = record.get("run_metrics", {})
    run_metrics = raw_metrics if isinstance(raw_metrics, Mapping) else {}
    error_code = str(run_metrics.get("error_code", "")).casefold()
    event_names = {str(event.get("event", "")) for event in events}
    if "parser" in error_code or "problem_parse_failed" in event_names:
        labels.add("parser_error")
    if "router" in error_code or "router_plan_failed" in event_names:
        labels.add("router_error")
    if not bool(record.get("json_valid", False)) or any(
        marker in error_code for marker in ("protocol", "schema", "public_output")
    ):
        labels.add("protocol_invalid")
    budget = _last_event(events, "budget_summary")
    raw_calls = budget.get("model_call_records", budget.get("model_calls", []))
    raw_calls = raw_calls if isinstance(raw_calls, list) else []
    if (
        int(run_metrics.get("model_call_timeout_count", 0) or 0) > 0
        or any(isinstance(call, dict) and call.get("status") == "timeout" for call in raw_calls)
        or "timeout" in error_code
    ):
        labels.add("provider_timeout")
    if any(
        isinstance(call, dict)
        and (
            call.get("response_truncated") is True
            or str(call.get("finish_reason", "")).casefold() == "length"
        )
        for call in raw_calls
    ):
        labels.add("truncated")
    candidate_states = [item.get("status", "") for item in candidates]
    if (
        "all_candidates" in error_code
        or (
            candidate_states
            and all(status in {"rejected", "generation_failed"} for status in candidate_states)
        )
    ):
        labels.add("candidate_rejected")
    if verdict.get("correct") is False:
        selected = next(
            (item for item in candidates if item["candidate_id"] == selected_id),
            None,
        )
        raw_case = record.get("case", {})
        case = raw_case if isinstance(raw_case, Mapping) else {}
        expected = case.get("expected_answer")
        alternatives_correct = False
        if expected is not None:
            for candidate in candidates:
                if candidate["candidate_id"] == selected_id or not candidate["final_answer"]:
                    continue
                try:
                    score = score_response(
                        str(expected),
                        candidate["final_answer"],
                        answer_type=case.get("answer_type"),
                        scorer=case.get("scorer"),
                    )
                except (TypeError, ValueError):
                    continue
                alternatives_correct = alternatives_correct or (score.scored and score.correct)
        if selected is not None and alternatives_correct:
            labels.add("wrong_arbitration")
        else:
            labels.add("solver_wrong")
    if not trace_complete:
        labels.add("trace_invalid")
    terminal = _last_event(events, "run_completed")
    if terminal.get("outcome") == "fallback" or "fallback_used" in event_names:
        labels.add("fallback")
    ordered = [label for label in _FAILURE_PRECEDENCE if label in labels]
    return {"primary": ordered[0] if ordered else None, "labels": ordered}


def _last_event(events: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for event in reversed(events):
        if event.get("event") == name:
            return event
    return {}


def _last_value(events: list[dict[str, Any]], name: str, field: str) -> Any:
    return _last_event(events, name).get(field, "")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return payload
