from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from scripts.profile_live_runs import ROOT, profile_run
from scripts.propose_competition_config import build_proposal


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def test_live_profile_binds_config_and_redacts_external_paths(tmp_path):
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(
        json.dumps(
            {"idx": "0", "problem": "Compute 1+1.", "answer": "2"},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    run_dir = tmp_path / "live-run"
    run_dir.mkdir()
    config = ROOT / "config" / "competition.json"
    config_sha256 = sha256(config.read_bytes()).hexdigest()
    _write_json(
        run_dir / "run_manifest.json",
        {
            "schema_version": "1.0",
            "config_sha256": config_sha256,
        },
    )
    _write_json(
        run_dir / "0.json",
        {
            "id": 0,
            "status": "success",
            "final_response": "2",
            "trace": [
                {
                    "event": "closed_loop_health",
                    "health": "healthy",
                    "candidate_flow": {"selected_candidate_id": "primary-1"},
                    "closure": {},
                    "model_dispatch": {},
                },
                {
                    "event": "budget_summary",
                    "used_calls": 1,
                    "elapsed_seconds": 1.0,
                    "provider_scheduler_peak": 1,
                    "model_calls": [{"status": "completed"}],
                },
                {
                    "event": "final_answer_selected",
                    "public_solution": {"final_answer": "2"},
                },
                {"event": "run_completed", "outcome": "primary"},
            ],
        },
    )
    _write_json(run_dir / "phase7_profile.json", {"status": "analysis"})

    profile, evidence = profile_run(
        run_dir,
        dataset_path=dataset,
        expected_cases=1,
        comparison_dirs=[],
    )
    serialized = json.dumps(
        {"profile": profile, "evidence": evidence},
        ensure_ascii=False,
    )

    assert profile["config_binding"]["matches_current"] is True
    assert profile["run_dir"] == "<external>/live-run"
    assert profile["persisted_case_count"] == 1
    assert len(evidence["case_outputs"]) == 1
    assert str(tmp_path) not in serialized


def test_config_proposal_rejects_profile_from_another_config():
    profile = {
        "config_binding": {
            "run_config_sha256": "a" * 64,
            "profiled_config_sha256": "b" * 64,
            "matches_current": False,
        },
        "output_coverage": 1.0,
        "success_rate": 1.0,
        "model_dispatch": {"success_rate": 1.0},
        "candidate_acceptance_rate": 1.0,
        "health_trace_completeness": 1.0,
        "calls_per_case": {"max": 1},
        "latency_seconds": {"max": 1.0},
    }

    proposal = build_proposal(
        profile,
        {"status": "candidate-unvalidated"},
        frozen_lemma_records=0,
    )

    assert proposal["freeze_eligible"] is False
    assert "profile_config_mismatch" in proposal["failed_gates"]
    assert proposal["competition_status"]["proposed"] == "candidate-unvalidated"


def test_config_proposal_requires_complete_answer_and_human_review():
    profile = {
        "config_binding": {"matches_current": True},
        "output_coverage": 1.0,
        "success_rate": 1.0,
        "model_dispatch": {"success_rate": 1.0},
        "candidate_acceptance_rate": 1.0,
        "answer_scoring": {"coverage": 1.0},
        "health_trace_completeness": 1.0,
        "calls_per_case": {"max": 1},
        "latency_seconds": {"max": 1.0},
    }

    pending = build_proposal(
        profile,
        {"status": "candidate-unvalidated"},
        frozen_lemma_records=0,
    )
    approved = build_proposal(
        profile,
        {"status": "candidate-unvalidated"},
        frozen_lemma_records=0,
        human_review_approved=True,
    )

    assert "human_review_incomplete" in pending["failed_gates"]
    assert pending["freeze_eligible"] is False
    assert approved["freeze_eligible"] is True
    assert approved["competition_status"]["proposed"] == "live-validated"


def test_live_profile_uses_symbolic_equivalence_for_answer_matching(tmp_path):
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "idx": "0",
                "problem": "Evaluate the expression.",
                "answer": r"\pi^2/6-(\ln2)^2",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    run_dir = tmp_path / "equivalent-run"
    run_dir.mkdir()
    config = ROOT / "config" / "competition.json"
    _write_json(
        run_dir / "run_manifest.json",
        {
            "config_sha256": sha256(config.read_bytes()).hexdigest(),
        },
    )
    _write_json(
        run_dir / "0.json",
        {
            "id": 0,
            "status": "success",
            "final_response": r"\frac{\pi^2}{6}-(\ln 2)^2",
            "trace": [
                {"event": "problem_parsed", "answer_type": "expression"},
                {
                    "event": "closed_loop_health",
                    "health": "healthy",
                    "candidate_flow": {"selected_candidate_id": "primary-1"},
                    "closure": {},
                    "model_dispatch": {},
                },
                {
                    "event": "budget_summary",
                    "used_calls": 1,
                    "elapsed_seconds": 1.0,
                    "provider_scheduler_peak": 1,
                    "model_calls": [{"status": "completed"}],
                },
                {
                    "event": "final_answer_selected",
                    "public_solution": {
                        "final_answer": r"\frac{\pi^2}{6}-(\ln 2)^2"
                    },
                },
                {"event": "run_completed", "outcome": "primary"},
            ],
        },
    )

    profile, _ = profile_run(
        run_dir,
        dataset_path=dataset,
        expected_cases=1,
        comparison_dirs=[],
    )

    assert profile["answer_match_rate_on_persisted_cases"] == 1.0
    assert profile["answer_scoring"] == {
        "persisted_cases": 1,
        "scored_outputs": 1,
        "correct_outputs": 1,
        "coverage": 1.0,
        "accuracy_on_scored_outputs": 1.0,
    }
    assert profile["cases"][0]["answer_score"]["reason"] == "symbolic_equivalent"
