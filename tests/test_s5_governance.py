from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

import pytest

from mathforge.benchmark import BenchmarkCase, benchmark_record_to_dict, run_benchmark
from mathforge.evaluation.artifacts import finalize_artifact, validate_artifact
from mathforge.governance.reviews import validate_review_manifest
from mathforge.model_identity import EXACT_INTERN_MODEL, exact_model_identity
from mathforge.retrieval.builder import build_database
from mathforge.retrieval.retriever import RetrievalStatus, Retriever
from mathforge.retrieval.schemas import KnowledgeCard
from mathforge.runtime import MathForgeHarness
from scripts.run_benchmark import build_benchmark_metadata, load_benchmark_config
from tests.fake_client import FakeClient
from tests.test_runtime_state import _minimal_config


ROOT = Path(__file__).resolve().parents[1]


def _card(identifier: str, statement: str = "Check equation roots.") -> KnowledgeCard:
    card = KnowledgeCard(
        identifier,
        "algebra",
        "procedure",
        "Equation checking",
        statement,
        ["equation"],
        [],
        ["extraneous root"],
        "test_fixture",
        "tests/test_s5_governance.py",
        "reviewed",
        "test-fixture-v1",
        "test-maintainer",
        "2026-07-23",
    )
    return replace(card, content_hash=card.computed_content_hash())


def test_rag_builder_is_atomic_when_sqlite_insertion_fails(tmp_path):
    database = tmp_path / "knowledge.sqlite"
    build_database(database, [_card("old")])
    before = sha256(database.read_bytes()).hexdigest()

    with pytest.raises(sqlite3.IntegrityError):
        build_database(database, [_card("duplicate"), _card("duplicate")])

    assert sha256(database.read_bytes()).hexdigest() == before
    assert [card.id for card in Retriever(database).retrieve("equation")] == ["old"]
    assert not list(tmp_path.glob(".knowledge.sqlite.*.tmp"))


def test_bilingual_retrieval_benchmark_meets_the_frozen_recall_gate():
    cases = json.loads(
        (ROOT / "data" / "retrieval_bilingual_benchmark.json").read_text(
            encoding="utf-8"
        )
    )
    retriever = Retriever()
    matches = 0
    for case in cases:
        result = retriever.search_with_status(
            case["query"],
            subject=case["subject"],
            top_k=3,
        )
        assert result.status is RetrievalStatus.MATCHED
        matches += case["expected_card_id"] in {
            hit.card.id for hit in result.hits
        }
    assert matches / len(cases) >= 0.875


def test_retrieval_reports_safe_failure_reasons_instead_of_silent_empty_lists(
    tmp_path,
):
    missing = Retriever(tmp_path / "missing.sqlite").search_with_status("equation")
    assert missing.status is RetrievalStatus.MISSING_DB
    assert missing.hits == []

    database = tmp_path / "empty.sqlite"
    sqlite3.connect(database).close()
    unavailable = Retriever(database).search_with_status("equation")
    assert unavailable.status is RetrievalStatus.FTS_UNAVAILABLE
    assert unavailable.hits == []

    no_match_database = tmp_path / "valid.sqlite"
    build_database(no_match_database, [_card("only")])
    no_match = Retriever(no_match_database).search_with_status("topology")
    assert no_match.status is RetrievalStatus.NO_MATCH


def test_runtime_trace_records_rag_failure_reason(tmp_path):
    config = replace(
        _minimal_config(),
        enable_skills=True,
        enable_rag=True,
    )
    harness = MathForgeHarness(FakeClient(), config)
    harness._retriever = Retriever(tmp_path / "missing.sqlite")
    result = harness.solve("Compute 1 + 1.", {})

    retrieval = next(
        event for event in result["trace"] if event["event"] == "retrieval_completed"
    )
    assert retrieval["status"] == "missing_db"
    assert retrieval["card_ids"] == []


def test_run_and_benchmark_provenance_are_complete_and_tamper_evident(tmp_path):
    harness = MathForgeHarness(
        FakeClient(),
        _minimal_config(),
        model_identity=exact_model_identity(
            EXACT_INTERN_MODEL,
            request_source="test",
        ),
    )
    result = harness.solve("1 + 1", {})
    provenance = result["provenance"]

    assert provenance["schema_version"] == "1.2"
    assert provenance["code_commit"]
    assert provenance["code_commit"] == "uninspected-runtime"
    assert provenance["code_dirty"] is None
    assert provenance["model_identity"]["requested_model"] == EXACT_INTERN_MODEL
    assert provenance["model_identity"]["response_model_observable"] is False
    assert provenance["tokenizer"]["repository"] == "internlm/Intern-S2-Preview-397B"
    assert len(provenance["tokenizer"]["tokenizer_json_sha256"]) == 64
    assert provenance["config"]["schema_version"]
    assert len(provenance["config"]["sha256"]) == 64
    assert len(provenance["prompts"]) == 8
    # Phase S4 adds nine externally sourced but fully rewritten V3 Skills.
    assert len(provenance["skills"]) == 95
    assert len(provenance["tools"]) == 10
    assert provenance["rag"]["schema_version"]
    assert len(provenance["rag"]["knowledge_db_sha256"]) == 64
    assert provenance["content_reviews"]["status"] == "pending-human"

    dataset = tmp_path / "cases.jsonl"
    config_path = tmp_path / "config.json"
    dataset.write_text('{"problem":"1+1"}\n', encoding="utf-8")
    config_path.write_text(
        json.dumps(_minimal_config().to_dict()),
        encoding="utf-8",
    )
    records, summary = run_benchmark(
        [BenchmarkCase("1", "1 + 1", "2", answer_type="integer")],
        harness.solve,
    )
    artifact = finalize_artifact(
        {
            **build_benchmark_metadata(
                dataset,
                config_path,
            ),
            "summary": summary,
            "records": [benchmark_record_to_dict(record) for record in records],
        }
    )
    assert validate_artifact(artifact) == []
    alias_artifact = json.loads(json.dumps(artifact))
    alias_artifact["requested_model"] = "intern-s2-preview"
    alias_artifact["run_provenance"]["model_identity"][
        "requested_model"
    ] = "intern-s2-preview"
    alias_artifact = finalize_artifact(alias_artifact)
    assert validate_artifact(alias_artifact) == [
        "artifact requested model is not the exact competition model"
    ]
    artifact["records"][0]["result"]["final_response"] = "tampered"
    assert validate_artifact(artifact) == ["artifact_sha256 mismatch"]


def test_artifact_validator_reports_malformed_nested_provenance():
    artifact = {
        "benchmark_schema_version": "3.3",
        "dataset_sha256": "0" * 64,
        "config_sha256": "0" * 64,
        "git_commit": "test",
        "code_dirty": False,
        "requested_model": EXACT_INTERN_MODEL,
        "request_source": "environment:INTERN_MODEL",
        "response_model_observable": False,
        "thinking_mode_observable": False,
        "unobservable_reason": "official_client_returns_assistant_content_only",
        "run_provenance": {
            "schema_version": "1.2",
            "code_commit": "test",
            "code_dirty": False,
            "model_identity": None,
            "tokenizer": None,
            "config": None,
            "prompts": [],
            "skills": [],
            "rag": {},
            "tools": [],
            "content_reviews": {},
            "component_decisions": {},
        },
        "summary": {},
        "records": [],
    }
    artifact = finalize_artifact(artifact)

    assert validate_artifact(artifact) == ["artifact run provenance is invalid"]


def test_content_review_manifest_covers_all_scopes_but_blocks_human_freeze():
    manifest_path = ROOT / "docs" / "content_review_manifest.json"
    assert validate_review_manifest(manifest_path, require_human=False) == []
    errors = validate_review_manifest(manifest_path, require_human=True)
    assert errors == ["human review signatures are incomplete"]


def test_component_decisions_keep_unproven_optional_paths_disabled():
    competition = json.loads(
        (ROOT / "config" / "competition.json").read_text(encoding="utf-8")
    )
    decisions = json.loads(
        (ROOT / "config" / "component_decisions.json").read_text(encoding="utf-8")
    )

    assert competition["enable_rag"] is False
    assert competition["use_mcp"] is False
    assert competition["enable_finalizer"] is False
    assert decisions["rag"]["default_enabled"] is False
    assert decisions["mcp"]["transport"] == "stdio"
    assert decisions["mcp"]["http_allowed"] is False
    assert decisions["mcp"]["persistent_process"] is False
    assert decisions["finalizer"]["default_enabled"] is False


def test_dependency_lock_is_exact_and_covers_direct_requirements():
    locked = {
        line.split("==", 1)[0].lower()
        for line in (ROOT / "requirements-lock.txt").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }
    assert {"requests", "sympy", "pytest", "pytest-cov", "ruff", "mypy"} <= locked
    assert all(
        "==" in line
        for line in (ROOT / "requirements-lock.txt").read_text(
            encoding="utf-8"
        ).splitlines()
        if line and not line.startswith("#")
    )


def test_all_a0_to_a10_ablation_overlays_are_loadable():
    for index in range(11):
        config = load_benchmark_config(
            ROOT / "config" / "ablation" / f"A{index}.json"
        )
        assert config.profile == f"ablation-A{index}"
        assert config.status == "experiment"
    assert load_benchmark_config(
        ROOT / "config" / "ablation" / "A10.json"
    ).enable_finalizer is True
