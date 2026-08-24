from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from mathforge.config import load_competition_config
from mathforge.evaluation.artifacts import finalize_artifact
from mathforge.evaluation.official_case_audit import (
    CASE_FAILURE_TAXONOMY,
    audit_official_artifact,
    competition_source_fingerprint,
)
from mathforge.model_identity import EXACT_INTERN_MODEL, exact_model_identity
from mathforge.provenance import build_run_provenance


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "data" / "evidence" / "phase0_0824_snapshot.json"


def _snapshot() -> dict:
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def _record(*, proof: bool = False) -> dict:
    response_mode = "proof_full" if proof else "worked_solution"
    problem_type = "proof" if proof else "calculation"
    expected_answer = "2"
    trace = [
        {
            "event": "problem_parsed",
            "problem_type": problem_type,
            "response_mode": response_mode,
        },
        {"event": "route_planned", "router_source": "llm_router"},
        {
            "event": "candidate_generated",
            "candidate_id": "primary-1",
            "role": "PrimarySolver",
            "source": "llm_primary",
            "content_digest": "a" * 64,
            "content": {"final_answer": "3"},
        },
        {
            "event": "candidate_generated",
            "candidate_id": "alternative-1",
            "role": "AlternativeSolver",
            "source": "llm_alternative",
            "content_digest": "b" * 64,
            "content": {"final_answer": "2"},
        },
        {
            "event": "candidate_final_states",
            "candidates": [
                {
                    "candidate_id": "primary-1",
                    "version": 1,
                    "status": "selected",
                    "reason_codes": ["arbitration_selected"],
                },
                {
                    "candidate_id": "alternative-1",
                    "version": 1,
                    "status": "viable_not_selected",
                    "reason_codes": ["arbitration_not_selected"],
                },
            ],
        },
        {"event": "final_answer_selected", "candidate_id": "primary-1"},
        {
            "event": "budget_summary",
            "model_call_records": [
                {
                    "logical_call_index": 1,
                    "logical_call_consumed": True,
                    "dispatched": True,
                    "role": "RouterPlanner",
                    "stage": "router",
                    "status": "completed",
                },
                {
                    "logical_call_index": 2,
                    "logical_call_consumed": True,
                    "dispatched": True,
                    "role": "PrimarySolver",
                    "candidate_id": "primary-1",
                    "stage": "solver_candidate_standard",
                    "status": "completed",
                },
            ],
        },
        {"event": "run_completed", "outcome": "primary", "error_code": ""},
    ]
    return {
        "case": {
            "idx": "case-1",
            "problem": "Prove the result." if proof else "Compute 1+1.",
            "expected_answer": expected_answer,
            "problem_type": problem_type,
            "answer_type": "integer",
            "scorer": "symbolic",
        },
        "result": {
            "final_response": "A complete proof." if proof else "3",
            "trace": trace,
            "run_metrics": {"model_calls": 2, "error_code": ""},
            "provenance": {},
        },
        "latency_seconds": 3.0,
        "json_valid": True,
        "score": {"scored": True, "correct": False, "reason": "mismatch"},
        "request_fingerprint": "c" * 64,
        "run_metrics": {
            "model_calls": 2,
            "model_call_timeout_count": 0,
            "error_code": "",
        },
        "pollution": {},
        "repetition_index": 0,
        "random_seed": 0,
    }


def _artifact(*, proof: bool = False) -> dict:
    snapshot = _snapshot()
    baseline = snapshot["baseline_candidate"]
    identity = exact_model_identity(
        EXACT_INTERN_MODEL,
        request_source="argument:--model",
    )
    provenance = build_run_provenance(
        load_competition_config(),
        model_identity=identity,
    ).to_dict()
    provenance["code_commit"] = baseline["git_commit"]
    provenance["code_dirty"] = False
    return finalize_artifact(
        {
            "benchmark_schema_version": "3.4",
            "dataset_sha256": "d" * 64,
            "config_sha256": baseline["config_sha256"],
            "prompt_sha256": baseline["prompt_sha256"],
            "skill_sha256": baseline["skill_sha256"],
            "git_commit": baseline["git_commit"],
            "code_dirty": False,
            **identity.to_dict(),
            "run_provenance": provenance,
            "summary": {"case_count": 1},
            "records": [_record(proof=proof)],
        }
    )


def _audit(artifact: dict, *, reviews: dict | None = None, origin: str = "official-platform-export") -> dict:
    return audit_official_artifact(
        artifact,
        _snapshot(),
        proof_reviews=reviews,
        evidence_origin=origin,
        root=ROOT,
    )


def test_frozen_phase0_source_and_taxonomy_are_reproducible_from_commit():
    snapshot = _snapshot()
    baseline = snapshot["baseline_candidate"]
    count, fingerprint = competition_source_fingerprint(
        ROOT,
        revision=baseline["git_commit"],
    )

    assert count == baseline["source_file_count"] == 171
    assert fingerprint == baseline["source_sha256"]
    assert tuple(snapshot["case_failure_taxonomy"]) == CASE_FAILURE_TAXONOMY
    assert snapshot["active_baseline_id"] is None
    assert all(
        not item["eligible_for_active_baseline"]
        for item in snapshot["official_evidence_inventory"]
    )


def test_nonproof_audit_exposes_calls_candidates_and_wrong_arbitration():
    audit = _audit(_artifact())
    case = audit["cases"][0]

    assert audit["active_baseline_eligible"] is True
    assert case["lineage_complete"] is True
    assert case["final_candidate"] == {
        "kind": "candidate",
        "candidate_id": "primary-1",
    }
    assert len(case["model_call_timeline"]) == 2
    assert {item["candidate_id"] for item in case["candidate_lineage"]} == {
        "primary-1",
        "alternative-1",
    }
    assert case["verdict"]["authority"] == "deterministic_auto_score"
    assert case["verdict"]["correct"] is False
    assert case["failure_classification"] == {
        "primary": "wrong_arbitration",
        "labels": ["wrong_arbitration"],
    }


def test_local_or_fingerprint_mismatched_evidence_cannot_be_activated():
    local = _audit(_artifact(), origin="local-diagnostic")
    assert local["active_baseline_eligible"] is False
    assert "evidence origin is not an official platform export" in local[
        "eligibility_errors"
    ]

    mismatched = _artifact()
    mismatched["git_commit"] = "0" * 40
    mismatched = finalize_artifact(mismatched)
    audit = _audit(mismatched)
    assert audit["active_baseline_eligible"] is False
    assert "artifact git_commit does not match frozen baseline" in audit[
        "eligibility_errors"
    ]
    assert "artifact source commit is unavailable for verification" in audit[
        "eligibility_errors"
    ]


def test_proof_requires_two_independent_reviews_and_third_on_disagreement():
    artifact = _artifact(proof=True)
    pending = _audit(artifact)
    assert pending["active_baseline_eligible"] is False
    assert pending["cases"][0]["verdict"]["status"] == "pending_human_review"

    disagreement = {
        "case-1": {
            "reviews": [
                {"reviewer_id": "reviewer-a", "verdict": "correct", "signature": "sig-a"},
                {"reviewer_id": "reviewer-b", "verdict": "incorrect", "signature": "sig-b"},
            ]
        }
    }
    still_pending = _audit(artifact, reviews=disagreement)
    assert still_pending["active_baseline_eligible"] is False

    adjudicated = deepcopy(disagreement)
    adjudicated["case-1"]["adjudication"] = {
        "reviewer_id": "reviewer-c",
        "verdict": "correct",
        "signature": "sig-c",
    }
    completed = _audit(artifact, reviews=adjudicated)
    verdict = completed["cases"][0]["verdict"]
    assert completed["active_baseline_eligible"] is True
    assert verdict["status"] == "completed"
    assert verdict["correct"] is True
    assert len(verdict["reviews"]) == 3
    assert all("signature" not in review for review in verdict["reviews"])


def test_missing_call_lineage_blocks_activation_even_when_output_is_valid():
    artifact = _artifact()
    artifact["records"][0]["result"]["trace"][-2]["model_call_records"] = []
    artifact = finalize_artifact(artifact)
    audit = _audit(artifact)

    assert audit["active_baseline_eligible"] is False
    assert audit["cases"][0]["lineage_complete"] is False
    assert "case case-1 lineage is incomplete" in audit["eligibility_errors"]


def test_repair_parent_link_is_retained_when_link_precedes_candidate_event():
    artifact = _artifact()
    trace = artifact["records"][0]["result"]["trace"]
    final_state_index = next(
        index
        for index, event in enumerate(trace)
        if event["event"] == "candidate_final_states"
    )
    trace[final_state_index:final_state_index] = [
        {
            "event": "repair_completed",
            "source_candidate_id": "primary-1",
            "proposed_candidate_id": "primary-1-v2",
        },
        {
            "event": "candidate_generated",
            "candidate_id": "primary-1-v2",
            "role": "RepairAgent",
            "source": "llm_repair",
            "content_digest": "e" * 64,
            "content": {"final_answer": "3"},
        },
    ]
    artifact = finalize_artifact(artifact)

    lineage = _audit(artifact)["cases"][0]["candidate_lineage"]
    repaired = next(item for item in lineage if item["candidate_id"] == "primary-1-v2")
    assert repaired["parents"] == ["primary-1"]


def test_malformed_summary_is_rejected_without_crashing_the_auditor():
    artifact = _artifact()
    artifact["summary"] = []
    artifact = finalize_artifact(artifact)
    audit = _audit(artifact)

    assert audit["active_baseline_eligible"] is False
    assert "artifact summary must be an object" in audit["eligibility_errors"]


def test_timeout_and_truncation_are_retained_as_causal_labels():
    artifact = _artifact()
    record = artifact["records"][0]
    record["run_metrics"]["model_call_timeout_count"] = 1
    calls = record["result"]["trace"][-2]["model_call_records"]
    calls[1]["status"] = "timeout"
    calls[1]["response_truncated"] = True
    calls[1]["finish_reason"] = "length"
    artifact = finalize_artifact(artifact)

    classification = _audit(artifact)["cases"][0]["failure_classification"]
    assert classification["primary"] == "provider_timeout"
    assert classification["labels"] == [
        "provider_timeout",
        "truncated",
        "wrong_arbitration",
    ]
