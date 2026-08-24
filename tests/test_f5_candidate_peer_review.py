from __future__ import annotations

import json

from mathforge.config import HarnessConfig
from mathforge.harness.schemas import CandidateSolution, Claim
from mathforge.runtime import MathForgeHarness
from mathforge.verification.candidate_pool import CandidatePool, ReviewThreadGuard
from tests.fake_client import FakeClient


def _config(**overrides) -> HarnessConfig:
    values = {
        "profile": "f5-test",
        "status": "test",
        "primary_max_tokens": 65_536,
        "max_model_calls": 16,
        "model_call_policy": "adaptive_bounded",
        "max_logical_model_calls_per_problem": 16,
        "soft_call_checkpoints": (4, 8, 12),
        "speculative_exploration_cutoff": 12,
        "closure_reserve_calls": 4,
        "enable_router": True,
        "enable_skills": False,
        "enable_alternatives": True,
        "enable_tools": False,
        "enable_evidence": False,
        "enable_proof_obligations": False,
        "enable_peer_cross_review": True,
        "enable_verifier": False,
        "enable_memory": False,
        "enable_lemma_loop": False,
        "enable_rag": False,
        "enable_repair": False,
        "enable_finalizer": False,
        "enable_shadow": False,
        "enable_frozen_lemma_store": False,
        "enable_long_horizon": True,
    }
    values.update(overrides)
    return HarnessConfig(**values)


def _event(result: dict, name: str) -> dict:
    return next(item for item in result["trace"] if item["event"] == name)


def test_bidirectional_solver_reviews_and_rebuttals_have_real_lineage():
    result = MathForgeHarness(FakeClient(), _config()).solve("Compute 2+2.", {})
    initialized = _event(result, "candidate_pool_initialized")
    completed = _event(result, "solver_peer_review_phase_completed")
    protocol = _event(result, "agent_protocol")
    records = _event(result, "budget_summary")["model_call_records"]

    assert initialized["independent_count"] == 2
    entries = initialized["entries"]
    assert len({item["author_agent_id"] for item in entries}) == 2
    assert len({item["source_turn_id"] for item in entries}) == 2
    assert all(item["independent"] for item in entries)
    assert completed["status"] == "completed"
    assert completed["bidirectional_reviews"] == 2
    assert completed["rebuttals"] == 2

    collaboration = [item for item in records if item["turn_kind"] == "peer_review"]
    assert len(collaboration) == 4
    assert [item["agent_mode"] for item in collaboration].count("peer_review") == 2
    assert [item["agent_mode"] for item in collaboration].count("rebuttal") == 2
    assert len({item["turn_id"] for item in collaboration}) == 4
    assert all(item["output_artifact_id"] for item in collaboration)

    reviews = [
        item for item in result["trace"] if item["event"] == "peer_review_completed"
    ]
    assert {(item["reviewer_role"], item["candidate_id"]) for item in reviews} == {
        ("PrimarySolver", "alternative-1"),
        ("AlternativeSolver", "primary-1"),
    }
    assert all(item["independent_model_call"] for item in reviews)
    assert all(item["host_generated"] is False for item in reviews)
    assert all(item["claim_ids"] == ["host-c1"] for item in reviews)

    task_types = [item["task_type"] for item in protocol["tasks"]]
    assert task_types.count("peer_review_candidate") == 2
    assert task_types.count("respond_to_peer_review") == 2
    message_types = [item["message_type"] for item in protocol["messages"]]
    assert message_types.count("peer_review_requested") == 2
    assert message_types.count("peer_review_published") >= 2
    assert message_types.count("rebuttal_published") == 2
    review_threads = [
        thread
        for thread in protocol["threads"]
        if any(
            message["message_type"] == "peer_review_requested"
            and message["thread_id"] == thread["thread_id"]
            for message in protocol["messages"]
        )
    ]
    assert len(review_threads) == 2
    assert all(item["status"] == "closed" for item in review_threads)
    assert all(len(item["message_ids"]) == 3 for item in review_threads)


def test_peer_review_artifacts_cite_claims_and_rebuttals_cite_findings():
    result = MathForgeHarness(FakeClient(), _config()).solve("Compute 2+2.", {})
    protocol = _event(result, "agent_protocol")
    artifacts = protocol["artifacts"]
    reviews = [item for item in artifacts if item["artifact_type"] == "PeerReviewArtifact"]
    rebuttals = [item for item in artifacts if item["artifact_type"] == "RebuttalArtifact"]

    assert len(reviews) == len(rebuttals) == 2
    finding_ids = {
        finding["finding_id"]
        for review in reviews
        for finding in review["payload"]["result_payload"]["finding_items"]
    }
    assert finding_ids
    assert all(
        finding["claim_id"] == "host-c1"
        for review in reviews
        for finding in review["payload"]["result_payload"]["finding_items"]
    )
    rebuttal_refs = {
        response["finding_id"]
        for rebuttal in rebuttals
        for response in rebuttal["payload"]["result_payload"]["responses"]
    }
    assert rebuttal_refs == finding_ids
    assert all(item["producer_agent_id"] != "Host" for item in reviews + rebuttals)


def _candidate(candidate_id: str, role: str) -> CandidateSolution:
    source = "llm_primary" if role == "PrimarySolver" else "llm_alternative"
    candidate = CandidateSolution(
        candidate_id=candidate_id,
        role=role,
        method="direct-deduction",
        planned_method_family="direct-deduction",
        final_answer="4",
        answer_type="integer",
        claims=[
            Claim(
                "c1",
                "$2+2=4$.",
                importance="critical",
            )
        ],
        public_solution_steps=["$2+2=4$."],
        solution_text="$2+2=4$.",
        source=source,
    )
    candidate.validate()
    return candidate


def test_semantically_duplicate_candidate_does_not_pass_independence_gate():
    pool = CandidatePool()
    first = pool.submit(
        _candidate("primary-1", "PrimarySolver"),
        author_agent_id="agent-primary",
        source_turn_id="turn-1",
        candidate_artifact_id="artifact-1",
    )
    duplicate = pool.submit(
        _candidate("alternative-1", "AlternativeSolver"),
        author_agent_id="agent-alternative",
        source_turn_id="turn-2",
        candidate_artifact_id="artifact-2",
    )

    assert first.independent is True
    assert duplicate.independent is False
    assert duplicate.status == "submitted"
    assert duplicate.duplicate_of == "primary-1"
    assert "semantic_candidate_duplicate" in duplicate.independence_reason_codes
    assert len(pool.independent_entries()) == 1
    assert len(pool.viable_entries()) == 2


def test_repeated_review_content_closes_thread_and_only_new_content_reopens():
    guard = ReviewThreadGuard("review-thread")
    assert guard.record({"finding_id": "f1", "status": "unknown"})
    assert not guard.record({"finding_id": "f1", "status": "unknown"})
    assert guard.status == "closed"
    assert not guard.reopen({"finding_id": "f1", "status": "unknown"})
    assert guard.reopen({"finding_id": "f1", "status": "fail"})
    assert guard.status == "open"


class _ConcedingClient(FakeClient):
    def chat(self, *, messages, temperature, max_tokens) -> str:
        response = super().chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        system = messages[0]["content"]
        if "Public protocol mode is peer_review" in system and system.startswith(
            "You are PrimarySolver"
        ):
            payload = json.loads(response)
            finding = payload["result_payload"]["finding_items"][0]
            finding["status"] = "fail"
            finding["severity"] = "critical"
            finding["public_rationale"] = "The terminal Claim is unsupported."
            payload["result_payload"]["recommended_action"] = "concede"
            return json.dumps(payload)
        if "Public protocol mode is respond_to_review" in system:
            request = json.loads(messages[-1]["content"])
            if any(
                item["status"] == "fail"
                for item in request["peer_review"]["finding_items"]
            ):
                payload = json.loads(response)
                payload["result_payload"]["responses"][0]["action"] = "concede"
                payload["result_payload"]["responses"][0]["response"] = (
                    "I concede this critical Finding."
                )
                return json.dumps(payload)
        return response


def test_author_concession_requests_local_repair_without_global_rejection():
    result = MathForgeHarness(_ConcedingClient(), _config()).solve(
        "Compute 2+2.",
        {},
    )
    completed = _event(result, "solver_peer_review_phase_completed")
    alternative = next(
        item
        for item in completed["candidate_pool"]
        if item["candidate_id"] == "alternative-1"
    )
    rebuttals = [
        item for item in result["trace"] if item["event"] == "rebuttal_completed"
    ]

    assert alternative["status"] == "repair_requested"
    assert alternative["conceded_finding_ids"]
    assert "alternative-1" in completed["active_candidate_ids"]
    assert any(item["conceded_finding_ids"] for item in rebuttals)
    assert completed["downstream_candidate_filter_applied"] is True
