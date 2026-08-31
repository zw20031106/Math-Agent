from __future__ import annotations

from dataclasses import replace
import json

import pytest

from mathforge.evaluation.production_preflight import run_production_preflight
from mathforge.governance.release import (
    ReleaseReadiness,
    evaluate_release_readiness,
)
from scripts.validate_release import validate_release


def _agent_turn() -> str:
    return json.dumps(
        {
            "protocol_version": "1.0",
            "task_result_type": "PreflightArtifact",
            "action": "complete",
            "public_state_delta": {},
            "result_payload": {"status": "ok"},
            "outbound_intents": [],
            "progress_summary": "preflight ok",
            "stop_reason": "preflight complete",
        }
    )


def _router() -> str:
    return json.dumps(
        {
            "primary_domain": "general-math",
            "secondary_domain": None,
            "risk": "medium",
            "patterns": ["decisive-relation"],
            "preferred_methods": ["direct-deduction"],
            "alternative_methods": ["constructive-computation"],
            "needs_long_horizon": False,
        }
    )


def _candidate() -> str:
    return json.dumps(
        {
            "method": "direct-deduction",
            "method_steps": [
                {
                    "step_id": "s1",
                    "kind": "conclusion",
                    "claim_ids": ["c1"],
                    "theorem": "",
                }
            ],
            "solution_text": "One plus one equals two.",
            "public_solution_steps": ["Compute 1+1=2."],
            "final_answer": "2",
            "assumptions": [],
            "theorems": [],
            "claims": [
                {
                    "claim_id": "c1",
                    "statement": "The sum is 2.",
                    "depends_on": [],
                    "check_type": "reasoning",
                    "importance": "critical",
                }
            ],
            "unresolved_obligations": [],
        }
    )


def _verifier(*, findings: bool = True) -> str:
    return json.dumps(
        {
            "findings": (
                [
                    {
                        "candidate_id": "preflight-l4",
                        "claim_id": "host-c1",
                        "obligation_ids": ["preflight-l4:sufficiency"],
                        "review_target_ids": [],
                        "review_level": "obligation",
                        "status": "pass",
                        "public_rationale": "The final claim supports 2.",
                        "missing_condition": "",
                        "counterexample_summary": "",
                    }
                ]
                if findings
                else []
            )
        }
    )


class _ScriptedClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


@pytest.mark.parametrize(
    ("responses", "failed_level"),
    [
        (["not-json"], "L1"),
        (['{"status":"ok"}', '{"status":"ok"}'], "L2"),
        (['{"status":"ok"}', _agent_turn(), "{}"], "L3"),
        (
            [
                '{"status":"ok"}',
                _agent_turn(),
                _router(),
                '{"final_answer":""}',
                '{"final_answer":""}',
            ],
            "L4",
        ),
        (
            [
                '{"status":"ok"}',
                _agent_turn(),
                _router(),
                _candidate(),
                _verifier(findings=False),
            ],
            "L5",
        ),
    ],
)
def test_preflight_failure_is_attributed_to_the_exact_layer(
    responses,
    failed_level,
):
    report = run_production_preflight(_ScriptedClient(responses))

    assert report["status"] == "failed"
    assert report["failed_level"] == failed_level
    assert report["levels"][-1]["level"] == failed_level


def test_optional_l5_is_explicitly_skipped_without_hiding_l0_to_l4():
    client = _ScriptedClient(
        ['{"status":"ok"}', _agent_turn(), _router(), _candidate()]
    )

    report = run_production_preflight(
        client,
        include_optional_verification=False,
    )

    assert report["status"] == "passed"
    assert [item["status"] for item in report["levels"]] == [
        "passed",
        "passed",
        "passed",
        "passed",
        "passed",
        "skipped",
    ]
    assert report["levels"][-1]["error_code"] == "optional_verification_disabled"


def test_preflight_retries_transient_router_and_verifier_protocol_failures():
    client = _ScriptedClient(
        [
            '{"status":"ok"}',
            _agent_turn(),
            "{}",
            _router(),
            _candidate(),
            _verifier(findings=False),
            _verifier(),
        ]
    )

    report = run_production_preflight(client)

    assert report["status"] == "passed"
    assert report["levels"][3]["transport_attempts"] == 2
    assert report["levels"][5]["transport_attempts"] == 2


def _ready() -> ReleaseReadiness:
    return ReleaseReadiness(
        active_baseline=True,
        clean_commit=True,
        all_tests=True,
        content_manifest=True,
        prompt_hash=True,
        skill_hash=True,
        benchmark_evidence=True,
        human_review=True,
        competition_frozen=True,
        competition_hash=True,
        test_attestation=True,
        baseline_commit=True,
    )


def test_strict_release_requires_every_independent_gate():
    assert evaluate_release_readiness(_ready()) == []
    for field in _ready().to_dict():
        errors = evaluate_release_readiness(replace(_ready(), **{field: False}))
        assert len(errors) == 1


def test_current_candidate_is_truthfully_blocked_before_phase11_and_phase12():
    errors = validate_release(results_root=None, run_commands=False)

    assert "active benchmark baseline is missing or invalid" in errors
    assert "benchmark evidence is unavailable or fingerprint-invalid" in errors
    assert "human review signatures are incomplete" in errors
    assert "competition config is not frozen" in errors
    assert "release test attestation is missing or stale" in errors
