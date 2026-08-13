from __future__ import annotations

import json

import pytest

from mathforge.benchmark import BenchmarkCase
from mathforge.config import HarnessConfig
from mathforge.output.loop_health import build_closed_loop_health
from mathforge.runtime import MathForgeHarness
from scripts.run_case_outputs import (
    CaseRunManifest,
    RUN_MANIFEST_FILENAME,
    _safe_print,
    validate_case_output,
)
from tests.fake_client import FakeClient
from user_agent import ReasoningAgent


def _config(**overrides) -> HarnessConfig:
    values = {
        "profile": "phase6-test",
        "status": "test",
        "max_model_calls": 1,
        "model_max_concurrency": 1,
        "max_background_model_tails": 1,
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


def _manifest_paths(tmp_path):
    input_path = tmp_path / "cases.jsonl"
    config_path = tmp_path / "competition.json"
    output_dir = tmp_path / "outputs"
    input_path.write_text(
        '{"idx":"1","problem":"1+1","expected_answer":"2"}\n',
        encoding="utf-8",
    )
    config_path.write_text('{"profile":"phase6"}\n', encoding="utf-8")
    return input_path, config_path, output_dir


def test_public_result_has_exactly_one_consistent_closed_loop_health():
    result = MathForgeHarness(FakeClient(), _config()).solve(
        "Compute 1+1.",
        {"idx": "health"},
    )
    health_events = [
        event
        for event in result["trace"]
        if event["event"] == "closed_loop_health"
    ]

    assert len(health_events) == 1
    assert health_events[0]["health"] in {"healthy", "degraded"}
    assert health_events[0]["candidate_flow"]["selected_candidate_id"]
    assert health_events[0]["closure"]["answer_available"] is True


def test_health_keeps_specific_transport_root_cause():
    health = build_closed_loop_health(
        [
            {
                "event": "candidate_generation_failed",
                "candidate_id": "primary-1",
                "reason": "network_connect_failure",
            }
        ],
        budget={
            "max_calls": 2,
            "used_calls": 1,
            "transport_attempts": 1,
            "model_call_records": [
                {
                    "failure_code": "network_connect_failure",
                    "transport_attempts": 1,
                }
            ],
        },
        selected_candidate_id="",
        outcome="fallback",
        error_code="all_candidates_failed",
    )

    assert health["health"] == "failed"
    assert health["model_dispatch"]["root_failure_codes"] == [
        "network_connect_failure"
    ]


def test_safe_console_failure_does_not_escape(monkeypatch):
    def broken_print(*_args, **_kwargs):
        raise UnicodeEncodeError("utf-8", "x", 0, 1, "closed")

    monkeypatch.setattr("builtins.print", broken_print)
    _safe_print("already persisted")


def test_manifest_attempt_history_and_contract_are_resume_safe(tmp_path):
    input_path, config_path, output_dir = _manifest_paths(tmp_path)
    case = BenchmarkCase("1", "1+1", expected_answer="2")
    _, first = CaseRunManifest.prepare(
        cases=[case],
        input_path=input_path,
        config_path=config_path,
        output_dir=output_dir,
        seed=0,
        concurrency=4,
        resume=False,
    )
    first.record_preflight({"status": "passed", "levels": []})
    first.mark_running()

    _, second = CaseRunManifest.prepare(
        cases=[case],
        input_path=input_path,
        config_path=config_path,
        output_dir=output_dir,
        seed=0,
        concurrency=4,
        resume=True,
    )
    attempts = second.payload["attempts"]

    assert [item["attempt_id"] for item in attempts] == [
        "attempt-0001",
        "attempt-0002",
    ]
    assert attempts[0]["status"] == "interrupted"
    assert attempts[1]["status"] == "created"
    assert attempts[0]["cases"] == {}
    assert second.payload["run_contract"]["output_contract"][
        "top_level_fields"
    ] == ["id", "status", "final_response", "trace"]

    manifest_path = output_dir / RUN_MANIFEST_FILENAME
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["run_contract"]["output_contract"][
        "judge_trace_schema_version"
    ] = "tampered"
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="run contract"):
        CaseRunManifest.prepare(
            cases=[case],
            input_path=input_path,
            config_path=config_path,
            output_dir=output_dir,
            seed=0,
            concurrency=4,
            resume=True,
        )


def test_health_and_decisions_survive_tight_trace_projection():
    result = ReasoningAgent(
        FakeClient(),
        config=_config(
            judge_trace_max_events=12,
            judge_trace_max_chars=12000,
            judge_trace_event_max_chars=3000,
        ),
    ).solve("Compute 1+1.", {"idx": "compact"})
    names = [event["step"] for event in result["trace"]]

    assert "reasoning" in names
    assert "verification" in names
    assert "arbitration" in names
    assert names[-1] == "finalize"


def test_resume_rejects_a_non_official_trace_schema(tmp_path):
    result = ReasoningAgent(FakeClient(), config=_config()).solve(
        "Compute 1+1.",
        {"idx": "legacy"},
    )
    for event in result["trace"]:
        event["schema_version"] = "3.0"
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(result, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="trace item"):
        validate_case_output(path, "legacy")
