from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from mathforge.evaluation.r0 import (
    R0_MIN_REPETITIONS,
    build_current_head_baseline,
    build_historical_reference_registry,
    capture_current_candidate_identity,
    source_tree_fingerprint,
    validate_current_candidate_identity,
    validate_current_head_baseline,
    validate_historical_reference_registry,
)
from mathforge.model_identity import exact_model_identity
from mathforge.harness.context_budget import tokenizer_provenance


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "competition.json"


def _identity() -> dict:
    hashes = {"a": "a" * 64, "b": "b" * 64, "c": "c" * 64}
    return {
        "schema_version": "1.0",
        "phase": "R0-T01",
        "captured_at": "2026-08-31T00:00:00+00:00",
        "git_commit": "1" * 40,
        "code_dirty": False,
        "tree_sha256": hashes["a"],
        "tree_fingerprint_algorithm": "sha256-source-v1",
        "competition_config_sha256": hashes["b"],
        "competition_config_fingerprint": hashes["c"],
        "prompt_tree_sha256": hashes["a"],
        "skill_tree_sha256": hashes["b"],
        "model_identity": exact_model_identity(
            "intern-s2-preview-397b",
            request_source="argument:--model",
        ).to_dict(),
        "token_counting_mode": "multilingual_estimate",
        "tokenizer_provenance": tokenizer_provenance(),
        "python": "CPython 3.11.0",
        "platform": "test-platform",
    }


def _artifact(
    identity: dict,
    dataset_sha256: str,
    *,
    accuracy: float = 0.2,
    repetition_index: int = 0,
) -> dict:
    return {
        "repetition_index": repetition_index,
        "run_id": f"run-{repetition_index}",
        "dataset_sha256": dataset_sha256,
        "config_sha256": identity["competition_config_fingerprint"],
        "git_commit": identity["git_commit"],
        "code_dirty": identity["code_dirty"],
        "timing_profile": "competition",
        "run_identity": {
            "commit_sha": identity["git_commit"],
            "competition_config_sha": identity["competition_config_fingerprint"],
            "prompt_fingerprint": identity["prompt_tree_sha256"],
            "skill_fingerprint": identity["skill_tree_sha256"],
            "tool_fingerprint": "d" * 64,
            "dataset_sha": dataset_sha256,
            "model_identity": deepcopy(identity["model_identity"]),
            "python": identity["python"],
            "platform": identity["platform"],
        },
        "summary": {
            "case_count": 112,
            "accuracy": accuracy,
            "average_prompt_tokens": 2000.0,
            "average_observed_output_tokens": 3000.0,
            "truncation_rate": 0.1,
            "timeout_rate": 0.0,
            "model_call_timeout_count": 0,
            "background_tail_started": 0,
            "average_model_calls": 4.0,
            "latency_p50_seconds": 10.0,
            "latency_p95_seconds": 20.0,
            "zero_candidate_rate": 0.0,
            "invalid_rate": 0.0,
        },
    }


def test_current_identity_captures_required_reproducibility_inputs() -> None:
    identity = capture_current_candidate_identity(
        ROOT,
        config_path=CONFIG,
    )

    assert validate_current_candidate_identity(identity) == []
    assert identity["phase"] == "R0-T01"
    assert identity["model_identity"]["requested_model"] == "intern-s2-preview-397b"
    assert identity["token_counting_mode"] in {
        "official_tokenizer",
        "multilingual_estimate",
    }
    for field in (
        "tree_sha256",
        "competition_config_sha256",
        "competition_config_fingerprint",
        "prompt_tree_sha256",
        "skill_tree_sha256",
    ):
        assert len(identity[field]) == 64


def test_source_tree_fingerprint_is_content_sensitive_and_line_ending_stable(tmp_path) -> None:
    (tmp_path / "user_agent.py").write_bytes(b"answer = 1\n")
    first = source_tree_fingerprint(tmp_path)
    (tmp_path / "user_agent.py").write_bytes(b"answer = 1\r\n")
    assert source_tree_fingerprint(tmp_path) == first
    (tmp_path / "user_agent.py").write_bytes(b"answer = 2\n")
    assert source_tree_fingerprint(tmp_path) != first


def test_historical_references_are_explicitly_ineligible() -> None:
    references = [
        {
            "id": "historical-2026-08-25",
            "status": "historical_official_reference",
            "date": "2026-08-25",
            "metrics": {"case_count": 112, "accuracy": 20 / 112},
            "eligible_for_baseline": False,
            "reasons": ["historical aggregate has no current HEAD identity"],
        }
    ]
    registry = build_historical_reference_registry(
        references,
        dataset_sha256="e" * 64,
        source_document="plan.md",
        source_sha256="f" * 64,
    )

    assert validate_historical_reference_registry(registry) == []
    assert registry["status"] == "historical-only"
    assert registry["active_baseline_id"] is None
    rejected = deepcopy(registry)
    rejected["active_baseline_id"] = references[0]["id"]
    assert "historical reference registry cannot activate a baseline" in (
        validate_historical_reference_registry(rejected)
    )


def test_checked_in_historical_reference_fixture_is_valid() -> None:
    fixture = json.loads(
        (ROOT / "data" / "evidence" / "historical_official_references.json").read_text(
            encoding="utf-8"
        )
    )
    assert validate_historical_reference_registry(fixture) == []
    assert [item["metrics"]["correct"] for item in fixture["references"]] == [20, 14]


def test_current_head_baseline_is_fail_closed_until_three_comparable_runs() -> None:
    identity = _identity()
    dataset_sha256 = "e" * 64
    artifacts = [_artifact(identity, dataset_sha256, accuracy=0.2)]

    blocked = build_current_head_baseline(
        artifacts,
        identity=identity,
        dataset_sha256=dataset_sha256,
    )
    assert blocked["status"] == "blocked"
    assert len(blocked["repetitions"]) == 1
    assert blocked["active_baseline_eligible"] is False
    assert any("at least 3" in item for item in blocked["blockers"])

    complete = build_current_head_baseline(
        [
            _artifact(identity, dataset_sha256, repetition_index=index)
            for index in range(R0_MIN_REPETITIONS)
        ],
        identity=identity,
        dataset_sha256=dataset_sha256,
    )
    assert complete["status"] == "complete"
    assert len(complete["repetitions"]) == R0_MIN_REPETITIONS
    assert validate_current_head_baseline(complete) == []
    assert complete["active_baseline_eligible"] is False


def test_current_head_baseline_rejects_mismatched_identity_artifacts() -> None:
    identity = _identity()
    dataset_sha256 = "e" * 64
    mismatched = _artifact(identity, dataset_sha256)
    mismatched["git_commit"] = "2" * 40

    baseline = build_current_head_baseline(
        [
            dict(mismatched, repetition_index=index)
            for index in range(R0_MIN_REPETITIONS)
        ],
        identity=identity,
        dataset_sha256=dataset_sha256,
    )

    assert baseline["status"] == "blocked"
    assert len(baseline["repetitions"]) == 0
    assert any("artifact commit does not match identity" in item for item in baseline["blockers"])


def test_current_head_baseline_does_not_count_the_same_run_three_times() -> None:
    identity = _identity()
    dataset_sha256 = "e" * 64
    artifact = _artifact(identity, dataset_sha256)

    baseline = build_current_head_baseline(
        [artifact, deepcopy(artifact), deepcopy(artifact)],
        identity=identity,
        dataset_sha256=dataset_sha256,
    )

    assert baseline["status"] == "blocked"
    assert len(baseline["repetitions"]) == 1
    assert any("duplicate repetition artifact fingerprint" in item for item in baseline["blockers"])


def test_current_head_baseline_does_not_count_one_run_under_new_labels() -> None:
    identity = _identity()
    dataset_sha256 = "e" * 64
    artifact = _artifact(identity, dataset_sha256)

    baseline = build_current_head_baseline(
        [dict(artifact, repetition_index=index) for index in range(R0_MIN_REPETITIONS)],
        identity=identity,
        dataset_sha256=dataset_sha256,
    )

    assert baseline["status"] == "blocked"
    assert len(baseline["repetitions"]) == 1
    assert any("duplicate repetition artifact fingerprint" in item for item in baseline["blockers"])


def test_current_head_baseline_requires_clean_resolvable_identity() -> None:
    identity = _identity()
    identity["code_dirty"] = True
    identity["git_commit"] = "unavailable"
    dataset_sha256 = "e" * 64

    baseline = build_current_head_baseline(
        [
            _artifact(identity, dataset_sha256, repetition_index=index)
            for index in range(R0_MIN_REPETITIONS)
        ],
        identity=identity,
        dataset_sha256=dataset_sha256,
    )

    assert baseline["status"] == "blocked"
    assert any("clean worktree" in item for item in baseline["blockers"])
    assert any("resolvable git commit" in item for item in baseline["blockers"])


def test_current_head_baseline_marks_unavailable_operational_metrics_as_blockers() -> None:
    identity = _identity()
    dataset_sha256 = "e" * 64
    artifact = _artifact(identity, dataset_sha256)
    del artifact["summary"]["truncation_rate"]

    baseline = build_current_head_baseline(
        [dict(artifact, repetition_index=index) for index in range(R0_MIN_REPETITIONS)],
        identity=identity,
        dataset_sha256=dataset_sha256,
    )

    assert baseline["status"] == "blocked"
    assert "truncation" in baseline["metric_gaps"]
    assert any("missing required baseline metrics" in item for item in baseline["blockers"])


def test_identity_rejects_wrong_model() -> None:
    identity = _identity()
    identity["model_identity"]["requested_model"] = "wrong-model"
    errors = validate_current_candidate_identity(identity)
    assert "current candidate identity uses the wrong model" in errors
