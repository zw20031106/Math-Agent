from __future__ import annotations

from mathforge.harness.schemas import CandidateSolution, Claim, MethodStep
from mathforge.verification.candidate_pool import CandidatePool
from mathforge.verification.cross_review import (
    CandidateConflictMatrix,
    CandidateReviewSummary,
    has_reviewable_work,
)


def _candidate(candidate_id: str, role: str, method: str, answer: str) -> CandidateSolution:
    candidate = CandidateSolution(
        candidate_id=candidate_id,
        role=role,
        method=method,
        final_answer=answer,
        answer_type="integer",
        claims=[Claim(f"{candidate_id}:claim", f"{answer} is the result")],
        method_steps=[
            MethodStep(
                f"{candidate_id}:step",
                "conclusion",
                [f"{candidate_id}:claim"],
            )
        ],
        public_solution_steps=[f"Therefore the result is {answer}."],
        solution_text=f"Therefore the result is {answer}.",
        source=(
            "llm_primary"
            if role == "PrimarySolver"
            else "llm_alternative"
        ),
    )
    candidate.validate()
    return candidate


def test_three_candidates_get_a_directed_coverage_review_graph():
    candidates = [
        _candidate("primary-1", "PrimarySolver", "direct-deduction", "4"),
        _candidate("alternative-1", "AlternativeSolver", "structural-transform", "4"),
        _candidate("alternative-2", "AlternativeSolver", "constructive-computation", "5"),
    ]
    matrix = CandidateConflictMatrix.build(
        [CandidateReviewSummary.from_candidate(item) for item in candidates]
    )

    assert len(matrix.review_edges) == 3
    assert {edge.target_candidate_id for edge in matrix.review_edges} == {
        item.candidate_id for item in candidates
    }
    assert has_reviewable_work(candidates, {}, matrix)
    assert len(matrix.to_dict()["review_graph"]) == 3


def test_independence_records_prompt_skill_model_and_correlated_answer():
    pool = CandidatePool()
    first = _candidate("primary-1", "PrimarySolver", "direct-deduction", "4")
    second = _candidate("alternative-1", "AlternativeSolver", "structural-transform", "4")
    provenance = {
        "branch_id": "branch-1",
        "plan_id": "plan",
        "plan_version": 1,
        "skill_set_hash": "skills-a",
        "prompt_hash": "prompt-a",
        "model_identity": "intern-s2-preview-397b",
        "shared_context_hash": "shared-a",
        "branch_context_hash": "branch-a",
        "lemma_ids": (),
        "tool_evidence_refs": (),
    }
    entry = pool.submit(
        first,
        author_agent_id="agent-primary",
        source_turn_id="turn-1",
        candidate_artifact_id="artifact-1",
        provenance=provenance,
    )
    duplicate = pool.submit(
        second,
        author_agent_id="agent-alternative",
        source_turn_id="turn-2",
        candidate_artifact_id="artifact-2",
        provenance={**provenance, "branch_id": "branch-b", "branch_context_hash": "branch-b"},
    )

    assert entry.independent
    assert duplicate.independent is False
    assert second.is_method_duplicate is True
    assert duplicate.correlated_corroboration is True
    assert "same_prompt_hash" in duplicate.independence_reason_codes
    assert "correlated_same_model_answer" in duplicate.independence_reason_codes


def test_unreviewed_candidate_is_explicitly_incomplete():
    pool = CandidatePool()
    candidate = _candidate("alternative-2", "AlternativeSolver", "constructive-computation", "5")
    pool.submit(
        candidate,
        author_agent_id="agent-alternative-2",
        source_turn_id="turn-2",
        candidate_artifact_id="artifact-2",
        provenance={"branch_id": "branch-2"},
    )
    pool.mark_peer_reviewing(candidate.candidate_id)
    pool.mark_review_incomplete(candidate.candidate_id)

    coverage = pool.review_coverage()[candidate.candidate_id]
    assert coverage["reviewed"] is False
    assert coverage["review_incomplete"] is True
    assert coverage["status"] == "submitted"
    assert candidate.candidate_id in pool.active_candidate_ids()
