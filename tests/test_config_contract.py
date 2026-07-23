from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

import mathforge.config as config_module
from mathforge.config import HarnessConfig
from scripts.run_benchmark import build_benchmark_metadata
from tests.fake_client import FakeClient
from user_agent import ReasoningAgent


def _minimal_config(**overrides) -> HarnessConfig:
    values = {
        "profile": "test",
        "status": "test",
        "max_model_calls": 1,
        "enable_router": False,
        "enable_skills": False,
        "enable_alternatives": False,
        "enable_tools": False,
        "enable_evidence": False,
        "enable_proof_obligations": False,
        "enable_verifier": False,
        "enable_memory": False,
        "enable_lemma_loop": False,
        "enable_rag": False,
        "enable_repair": False,
        "enable_finalizer": False,
    }
    values.update(overrides)
    return HarnessConfig(**values)


def _write_config(path: Path, config: HarnessConfig) -> None:
    path.write_text(
        json.dumps(config.to_dict(), ensure_ascii=False),
        encoding="utf-8",
    )


def test_config_rejects_unknown_keys_string_booleans_and_ranges():
    valid = _minimal_config().to_dict()
    with pytest.raises(ValueError, match="unknown configuration keys"):
        HarnessConfig.from_dict({**valid, "typo_feature": True})
    with pytest.raises(ValueError, match="enable_tools"):
        HarnessConfig.from_dict({**valid, "enable_tools": "false"})
    with pytest.raises(ValueError, match="max_model_calls"):
        HarnessConfig.from_dict({**valid, "max_model_calls": 0})
    with pytest.raises(ValueError, match="max_claims"):
        HarnessConfig.from_dict({**valid, "max_claims": 0})
    with pytest.raises(ValueError, match="max_tool_seconds"):
        HarnessConfig.from_dict({**valid, "max_tool_seconds": 0})


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "enable_verifier": True,
            "enable_evidence": False,
            "enable_proof_obligations": True,
            "max_model_calls": 2,
        },
        {
            "enable_repair": True,
            "enable_evidence": True,
            "enable_tools": False,
        },
        {
            "enable_lemma_loop": True,
            "enable_memory": False,
            "enable_proof_obligations": True,
        },
        {"enable_rag": True, "enable_skills": False},
        {"use_mcp": True, "enable_tools": False},
    ],
)
def test_invalid_feature_dependencies_fail_at_construction(overrides):
    with pytest.raises(ValueError, match="requires"):
        _minimal_config(**overrides)


def test_required_verifier_must_be_reachable_by_model_call_budget():
    with pytest.raises(ValueError, match="at least two model calls"):
        _minimal_config(
            enable_verifier=True,
            enable_evidence=True,
            enable_proof_obligations=True,
            max_model_calls=1,
        )


def test_named_profiles_are_versioned_and_fully_expanded():
    root = Path(__file__).resolve().parents[1]
    expected_settings = HarnessConfig.setting_names()
    for name in ("safe", "balanced", "competition"):
        payload = json.loads(
            (root / "config" / f"{name}.json").read_text(encoding="utf-8")
        )
        assert payload["schema_version"] == HarnessConfig.SCHEMA_VERSION
        assert payload["profile"] == name
        assert expected_settings <= set(payload)
        assert HarnessConfig.from_dict(payload).profile == name


def test_public_and_benchmark_use_the_same_semantic_config_hash(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "competition.json"
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text('{"problem":"1"}\n', encoding="utf-8")
    config = _minimal_config(profile="competition")
    _write_config(config_path, config)
    monkeypatch.setattr(config_module, "COMPETITION_CONFIG_PATH", config_path)

    result = ReasoningAgent(FakeClient()).solve("1 + 1", {})
    public_hash = result["trace"][0]["config_hash"]
    metadata = build_benchmark_metadata(dataset, config_path)
    benchmark_hash = metadata["config_sha256"]

    assert public_hash == benchmark_hash == config.fingerprint
    assert result["trace"][0]["config_schema_version"] == HarnessConfig.SCHEMA_VERSION
    assert result["trace"][0]["prompt_hash"] == metadata["prompt_sha256"]
    assert result["trace"][0]["skill_hash"] == metadata["skill_sha256"]
    assert result["trace"][0]["rag_hash"] == metadata["rag_sha256"]
    assert result["trace"][0]["tool_hash"] == metadata["tool_sha256"]
    assert len(metadata["prompt_sha256"]) == 64
    assert len(metadata["skill_sha256"]) == 64
    assert len(metadata["rag_sha256"]) == 64
    assert len(metadata["tool_sha256"]) == 64


def test_changing_competition_config_changes_public_behavior(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "competition.json"
    monkeypatch.setattr(config_module, "COMPETITION_CONFIG_PATH", config_path)

    disabled = _minimal_config(profile="competition")
    _write_config(config_path, disabled)
    without_tools = ReasoningAgent(FakeClient()).solve("1 + 1", {})

    enabled = replace(disabled, enable_tools=True)
    _write_config(config_path, enabled)
    with_tools = ReasoningAgent(FakeClient()).solve("1 + 1", {})

    assert not any(event["event"] == "tool_checks" for event in without_tools["trace"])
    assert any(event["event"] == "tool_checks" for event in with_tools["trace"])
    assert without_tools["trace"][0]["config_hash"] != with_tools["trace"][0]["config_hash"]


def test_tests_can_inject_validated_config_without_an_external_path():
    config = _minimal_config()
    result = ReasoningAgent(FakeClient(), config=config).solve("x", {})
    assert result["trace"][0]["config_hash"] == config.fingerprint
