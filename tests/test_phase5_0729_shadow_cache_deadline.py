from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path

import pytest

from mathforge.config import HarnessConfig, load_competition_config
from mathforge.harness.schemas import ProblemIR
from mathforge.memory.frozen_lemma_store import FrozenLemmaStore
from mathforge.runtime import MathForgeHarness
from mathforge.tools.executor import ToolExecutor
from mathforge.tools.mcp_server import StdioMCPServer
from mathforge.tools.shadow_solver import ShadowCapabilityRegistry
from scripts.build_frozen_lemma_store import build_store
from tests.fake_client import FakeClient


def _problem(text: str, answer_type: str = "expression") -> ProblemIR:
    return ProblemIR(
        raw_problem=text,
        normalized_problem=text,
        problem_type="calculation",
        answer_type=answer_type,
    )


def _shadow_config(**overrides) -> HarnessConfig:
    values = {
        "profile": "phase5-test",
        "status": "test",
        "max_model_calls": 1,
        "primary_max_tokens": 2048,
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
        "enable_shadow": True,
        "enable_frozen_lemma_store": False,
    }
    values.update(overrides)
    return HarnessConfig(**values)


@pytest.mark.parametrize(
    ("problem", "answer"),
    [
        ("Compute 1 + 1.", "2"),
        ("Solve x + 1 = 3 for x.", "2"),
        (
            "Solve the system x + y = 3; x - y = 1 for x, y.",
            "(2, 1)",
        ),
        ("Compute the determinant of [[1,2],[3,4]].", "-2"),
        ("Limit of sin(x)/x as x -> 0.", "1"),
        ("Integral of x from 0 to 2 with respect to x.", "2"),
        ("Indefinite integral of x with respect to x.", "x**2/2 + C"),
        ("Sum of 1/2^k for k from 0 to infinity.", "2"),
    ],
)
def test_shadow_registry_first_capability_set(problem, answer):
    outcome = ShadowCapabilityRegistry().solve(_problem(problem))

    assert outcome.status == "exact"
    assert outcome.final_answer == answer
    assert outcome.capability
    assert outcome.limitations


def test_shadow_unsupported_shape_does_not_create_a_candidate():
    outcome = ShadowCapabilityRegistry().solve(
        _problem("Prove that every finite subgroup of a field is cyclic.")
    )

    assert outcome.status == "unsupported"
    assert outcome.to_candidate("text") is None


def test_runtime_shadow_probe_is_registered_as_an_isolated_host_tool():
    executor = ToolExecutor(default_timeout=5.0)

    assert executor.is_isolated("deterministic_shadow_probe")
    assert executor.validate_arguments(
        "deterministic_shadow_probe",
        {
            "problem_ir": _problem("Compute 1 + 1.").to_dict(),
            "time_budget_seconds": 5.0,
        },
    ) == []
    listed = StdioMCPServer().handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    assert "deterministic_shadow_probe" not in {
        item["name"] for item in listed["result"]["tools"]
    }
    rejected = StdioMCPServer().handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "deterministic_shadow_probe",
                "arguments": {
                    "problem_ir": _problem("Compute 1 + 1.").to_dict(),
                },
            },
        }
    )
    assert rejected["error"]["message"] == "tool is not model-callable"


def test_exact_shadow_is_a_degraded_concrete_fallback_when_model_is_offline():
    result = MathForgeHarness(
        FakeClient(fail=True),
        _shadow_config(),
    ).solve("Compute 1 + 1.", {})

    assert "2" in result["final_response"]
    selected = next(
        event
        for event in result["trace"]
        if event["event"] == "final_answer_selected"
    )
    assert selected["candidate_id"] == "shadow-1"
    assert selected["selected_source"] == "deterministic_shadow"
    assert selected["selection_quality"] == "degraded_shadow_only"
    assert result["run_metrics"]["model_calls"] == 1


def test_shadow_answer_is_not_exposed_to_primary_prompt():
    client = FakeClient()
    MathForgeHarness(client, _shadow_config()).solve("Compute 1 + 1.", {})

    rendered = json.dumps(client.calls[0]["messages"], ensure_ascii=False)
    assert "deterministic_shadow" not in rendered
    assert "shadow-1" not in rendered
    assert "shadow_probe_completed" not in rendered


def test_four_concurrent_shadow_sessions_do_not_share_answers_or_nonces():
    harness = MathForgeHarness(
        FakeClient(fail=True),
        _shadow_config(model_max_concurrency=4),
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda value: harness.solve(
                    f"Compute {value} + {value}.",
                    {"benchmark_nonce": f"private-{value}"},
                ),
                range(1, 5),
            )
        )

    for value, result in enumerate(results, start=1):
        selected = next(
            event
            for event in result["trace"]
            if event["event"] == "final_answer_selected"
        )
        assert selected["public_solution"]["final_answer"] == str(2 * value)
        rendered = json.dumps(result, ensure_ascii=False)
        assert all(
            f"private-{other}" not in rendered
            for other in range(1, 5)
        )


def test_shadow_conflict_is_visible_and_admits_an_alternative():
    client = FakeClient()
    result = MathForgeHarness(
        client,
        _shadow_config(
            max_model_calls=3,
            enable_alternatives=True,
        ),
    ).solve("Compute 1 + 1.", {})

    decision = next(
        event
        for event in result["trace"]
        if event["event"] == "adaptive_fanout_decided"
    )
    matrix = next(
        event
        for event in result["trace"]
        if event["event"] == "candidate_conflict_matrix"
    )
    assert "shadow_conflict" in decision["reason_codes"]
    assert decision["admitted_candidates"] >= 2
    assert any(
        {
            pair["left_candidate_id"],
            pair["right_candidate_id"],
        }
        == {"primary-1", "shadow-1"}
        and pair["answer_conflict"]
        for pair in matrix["matrix"]["conflicts"]
    )


def _staged_lemma(*, assumption: str = "x > 0") -> dict:
    return {
        "lemma_id": "positive-square",
        "statement": "For positive real x, x squared is positive.",
        "normalized_signature": "positive real square",
        "domain": "real analysis",
        "assumptions": [assumption],
        "preconditions": [],
        "conclusion": "x^2 > 0",
        "proof_outline_public": ["Multiply two positive real factors."],
        "verification_type": "deterministic_and_human_review",
        "verification_artifact_hash": "a" * 64,
        "source_version": "phase5-test",
        "review_status": "human_approved",
    }


def test_offline_builder_and_runtime_store_are_hash_checked_and_read_only(
    tmp_path: Path,
):
    staging = tmp_path / "staging.jsonl"
    output = tmp_path / "frozen.jsonl"
    manifest = tmp_path / "manifest.json"
    staging.write_text(
        json.dumps(_staged_lemma(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    built = build_store(staging, output, manifest)
    store = FrozenLemmaStore(output, manifest)
    before = (
        output.stat().st_mtime_ns,
        sha256(output.read_bytes()).hexdigest(),
    )
    problem = _problem(
        "Assume x > 0. Use positivity to determine the sign of x squared."
    )
    problem.assumptions = ["x > 0"]

    hits = store.retrieve(problem)
    after = (
        output.stat().st_mtime_ns,
        sha256(output.read_bytes()).hexdigest(),
    )

    assert built["record_count"] == store.count == 1
    assert hits[0].lemma.lemma_id == "positive-square"
    assert hits[0].assumption_checks == (
        {"condition": "x > 0", "satisfied": True},
    )
    assert before == after
    assert not hasattr(store, "write") and not hasattr(store, "add")


def test_frozen_lemma_hit_is_rejected_when_current_assumption_is_missing(
    tmp_path: Path,
):
    staging = tmp_path / "staging.jsonl"
    output = tmp_path / "frozen.jsonl"
    manifest = tmp_path / "manifest.json"
    staging.write_text(
        json.dumps(_staged_lemma(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    build_store(staging, output, manifest)

    hits = FrozenLemmaStore(output, manifest).retrieve(
        _problem("Determine the sign of x squared.")
    )

    assert hits == ()


def test_frozen_builder_rejects_unreviewed_content_and_store_rejects_tampering(
    tmp_path: Path,
):
    staging = tmp_path / "staging.jsonl"
    output = tmp_path / "frozen.jsonl"
    manifest = tmp_path / "manifest.json"
    unreviewed = _staged_lemma()
    unreviewed["review_status"] = "model_generated"
    staging.write_text(
        json.dumps(unreviewed, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="human approval"):
        build_store(staging, output, manifest)

    staging.write_text(
        json.dumps(_staged_lemma(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    build_store(staging, output, manifest)
    output.write_text(output.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="store hash mismatch"):
        FrozenLemmaStore(output, manifest)


def test_competition_uses_the_900_second_candidate_boundary_and_unbounded_trace():
    config = load_competition_config()

    assert config.outer_platform_limit_seconds == 900.0
    assert config.hard_deadline_seconds == 850.0
    assert config.soft_deadline_seconds == 600.0
    assert config.exploration_deadline_seconds == 720.0
    assert config.deterministic_finalize_reserve_seconds == 50.0
    assert config.final_response_max_chars == 20000
    assert config.trace_max_chars == 4000
    assert config.trace_max_events == 0
    assert not config.enable_shadow
    assert not config.enable_frozen_lemma_store
