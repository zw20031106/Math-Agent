from __future__ import annotations

import pytest

from mathforge.model_identity import (
    EXACT_INTERN_MODEL,
    ModelIdentity,
    require_exact_intern_model,
)
from scripts.scan_secrets import SecretFinding, scan_repository
from tests.fake_client import FakeClient
from user_agent import ReasoningAgent


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"INTERN_MODEL": "intern-s2-preview"},
        {"INTERN_MODEL": "intern-latest"},
        {"INTERN_MODEL": "INTERN-S2-PREVIEW-397B"},
        {"INTERN_MODEL": "intern-s2-preview-397B"},
        {"INTERN_MODEL": "INTERN-S2-PREVIEW"},
        {"INTERN_MODEL": " intern-s2-preview-397b"},
    ],
)
def test_exact_model_gate_rejects_missing_alias_and_noncanonical_values(environment):
    with pytest.raises(RuntimeError, match="intern-s2-preview-397b"):
        require_exact_intern_model(environment)


def test_exact_model_gate_uses_one_environment_source_and_marks_boundaries():
    identity = require_exact_intern_model({"INTERN_MODEL": EXACT_INTERN_MODEL})

    assert identity == ModelIdentity(
        requested_model=EXACT_INTERN_MODEL,
        request_source="environment:INTERN_MODEL",
    )
    assert identity.response_model_observable is False
    assert identity.thinking_mode_observable is False


def test_public_runner_uses_the_injected_official_client_without_local_model_env(
    monkeypatch,
):
    monkeypatch.delenv("INTERN_MODEL", raising=False)
    client = FakeClient()

    result = ReasoningAgent(client).solve("1 + 1", {})

    assert result["status"] == "success"
    assert client.calls


def test_caller_cannot_replace_environment_model_with_a_display_label():
    result = ReasoningAgent(
        FakeClient(),
        model_identifier="intern-latest",
    ).solve("1 + 1", {})
    session_started = result["trace"][0]

    assert session_started["requested_model"] == EXACT_INTERN_MODEL
    assert session_started["request_source"] == "official_client_injected"
    assert session_started["response_model_observable"] is False
    assert session_started["thinking_mode_observable"] is False
    assert "model_identifier" not in session_started
    assert "response_model" not in session_started


def test_secret_scan_reports_location_without_echoing_secret(tmp_path):
    token = "s" + "k-" + "A" * 32
    (tmp_path / "leak.txt").write_text(f"credential={token}\n", encoding="utf-8")

    findings = scan_repository(tmp_path)

    assert findings == [SecretFinding("leak.txt", 1, "api_token")]
    assert token not in repr(findings)


def test_repository_secret_scan_is_clean():
    assert scan_repository() == []
