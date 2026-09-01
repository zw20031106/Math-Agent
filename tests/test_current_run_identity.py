from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from mathforge.config import HarnessConfig, load_competition_config
from mathforge.evaluation.artifacts import (
    COMPETITION_TIMING_PROFILE,
    DEBUG_NONCOMPARABLE_TIMING_PROFILE,
    build_run_identity,
    ensure_competition_timing,
    run_identity_errors,
    timing_profile_for,
    validate_baseline_artifact,
)
from mathforge.evaluation.evidence_registry import baseline_registration_errors
from mathforge.model_identity import EXACT_INTERN_MODEL, exact_model_identity
from scripts.run_benchmark import build_benchmark_metadata
from scripts.run_case_outputs import (
    PER_CASE_WALL_CLOCK_SECONDS,
    CaseRunManifest,
    PerCaseWallClockRunner,
)
from mathforge.benchmark import BenchmarkCase


def _identity(**overrides):
    values = {
        "commit_sha": "a" * 40,
        "competition_config_sha": "b" * 64,
        "prompt_fingerprint": "c" * 64,
        "skill_fingerprint": "d" * 64,
        "tool_fingerprint": "e" * 64,
        "dataset_sha": "f" * 64,
        "model_identity": exact_model_identity(
            EXACT_INTERN_MODEL,
            request_source="argument:--model",
        ).to_dict(),
        "python": "CPython 3.13.4",
        "platform": "Windows-test",
    }
    values.update(overrides)
    return build_run_identity(**values)


def test_run_identity_has_all_fingerprints_and_rejects_missing_fields():
    identity = _identity()
    assert run_identity_errors(identity) == []
    missing = identity.to_dict()
    missing.pop("prompt_fingerprint")
    errors = run_identity_errors(missing)
    assert "run identity fields are missing: ['prompt_fingerprint']" in errors

    changed = identity.to_dict()
    changed["prompt_fingerprint"] = "0" * 64
    assert changed["prompt_fingerprint"] != identity.prompt_fingerprint


def test_benchmark_metadata_freezes_current_inputs_and_timing(tmp_path):
    dataset = tmp_path / "cases.jsonl"
    config = tmp_path / "config.json"
    dataset.write_text('{"idx":"1","problem":"1+1"}\n', encoding="utf-8")
    configured = HarnessConfig(profile="test", status="candidate-unvalidated")
    config.write_text(json.dumps(configured.to_dict()), encoding="utf-8")

    metadata = build_benchmark_metadata(dataset, config)
    identity = metadata["run_identity"]
    assert set(identity) == {
        "commit_sha",
        "competition_config_sha",
        "prompt_fingerprint",
        "skill_fingerprint",
        "tool_fingerprint",
        "dataset_sha",
        "model_identity",
        "python",
        "platform",
    }
    assert identity["dataset_sha"] == metadata["dataset_sha256"]
    assert metadata["timing_profile"] == DEBUG_NONCOMPARABLE_TIMING_PROFILE

    original_config_sha = identity["competition_config_sha"]
    config.write_text(
        json.dumps({**configured.to_dict(), "skill_char_budget": 6001}),
        encoding="utf-8",
    )
    changed_config = build_benchmark_metadata(dataset, config)["run_identity"]
    assert changed_config["competition_config_sha"] != original_config_sha

    dataset.write_text('{"idx":"1","problem":"2+2"}\n', encoding="utf-8")
    changed_dataset = build_benchmark_metadata(dataset, config)["run_identity"]
    assert changed_dataset["dataset_sha"] != identity["dataset_sha"]


def test_historical_evidence_and_dirty_runs_cannot_register_baseline():
    identity = _identity()
    registry = {
        "baseline_candidate_git_commit": identity.commit_sha,
        "baseline_candidate_config_sha256": identity.competition_config_sha,
        "dataset_sha256": identity.dataset_sha,
        "active_baseline_id": None,
        "entries": [],
    }
    entry = {
        "classification": "historical-ineligible",
        "eligible_for_baseline": False,
        "requested_model": EXACT_INTERN_MODEL,
        "git_commit": identity.commit_sha,
        "dataset_sha256": identity.dataset_sha,
    }
    errors = baseline_registration_errors(
        registry,
        identity.to_dict(),
        code_dirty=True,
        timing_profile=COMPETITION_TIMING_PROFILE,
        entry=entry,
    )
    assert "run identity requires a clean worktree" in errors
    assert "historical evidence cannot become an active baseline" in errors


def test_baseline_artifact_requires_current_identity_and_competition_timing():
    artifact = {
        "benchmark_schema_version": "3.4",
        "dataset_sha256": "f" * 64,
        "config_sha256": "b" * 64,
        "git_commit": "a" * 40,
        "code_dirty": True,
        "requested_model": EXACT_INTERN_MODEL,
        "request_source": "argument:--model",
        "response_model_observable": False,
        "thinking_mode_observable": False,
        "unobservable_reason": "official_client_returns_assistant_content_only",
        "run_provenance": {},
        "summary": {},
        "records": [],
        "artifact_sha256": "",
    }
    errors = validate_baseline_artifact(artifact)
    assert "baseline artifact is missing run_identity" in errors
    assert "baseline artifact timing profile is not competition" in errors


def test_formal_competition_profile_rejects_1200_seconds():
    config = replace(load_competition_config(), outer_platform_limit_seconds=1200.0)
    assert timing_profile_for(config) == DEBUG_NONCOMPARABLE_TIMING_PROFILE
    with pytest.raises(ValueError, match="900-second"):
        ensure_competition_timing(config)


def test_case_runner_default_and_manifest_record_competition_identity(tmp_path):
    assert PER_CASE_WALL_CLOCK_SECONDS == 900.0
    runner = PerCaseWallClockRunner(lambda *_: {"final_response": "ok", "trace": []})
    assert runner.wall_clock_seconds == 900.0
    assert runner.harness_return_seconds == 850.0

    dataset = tmp_path / "cases.jsonl"
    config = tmp_path / "config.json"
    output = tmp_path / "outputs"
    dataset.write_text('{"idx":"1","problem":"1+1"}\n', encoding="utf-8")
    config.write_text(
        json.dumps(HarnessConfig(profile="test", status="candidate-unvalidated").to_dict()),
        encoding="utf-8",
    )
    _, manifest = CaseRunManifest.prepare(
        cases=[BenchmarkCase("1", "1+1")],
        input_path=dataset,
        config_path=config,
        output_dir=output,
        seed=0,
        concurrency=2,
        resume=False,
    )
    identity = manifest.payload["run_contract"]["run_identity"]
    assert set(identity) == {
        "commit_sha",
        "competition_config_sha",
        "prompt_fingerprint",
        "skill_fingerprint",
        "tool_fingerprint",
        "dataset_sha",
        "model_identity",
        "python",
        "platform",
    }
    assert manifest.payload["run_identity"] == identity
