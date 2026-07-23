from __future__ import annotations

from mathforge.harness.lemma_loop import VerifiedLemmaLoop
from mathforge.harness.schemas import CandidateSolution, Claim, EvidenceRecord, RoutePlan
from mathforge.memory.lemma_memory import LemmaMemory
from mathforge.memory.session_memory import SessionMemory
from mathforge.verification.capabilities import (
    ClaimVerificationState,
    VerificationCapability,
)


def _route(risk: str = "high") -> RoutePlan:
    return RoutePlan(
        "algebra",
        None,
        "proof",
        "text",
        risk,
        use_lemma_loop=risk == "high",
        max_reasoning_rounds=2,
    )


def test_only_verified_lemmas_enter_memory_and_rounds_stop_without_new_work():
    candidate = CandidateSolution(
        "c",
        "PrimarySolver",
        "direct",
        "proved",
        "text",
        claims=[
            Claim(
                "verified",
                "sufficiency lemma",
                status="verified",
                verification_state=ClaimVerificationState.SEMANTICALLY_VERIFIED.value,
            ),
            Claim("unknown", "boundary lemma", status="unverified"),
        ],
    )
    memory = LemmaMemory(SessionMemory())
    result = VerifiedLemmaLoop().run(_route(), [candidate], [], {}, memory)
    assert [lemma.status for lemma in result.lemmas] == ["verified", "conflicted"]
    assert len(memory.verified()) == 1
    assert result.rounds[0].progress_score == 0.0
    assert result.stop_reason == "no_new_progress"


def test_non_high_risk_never_runs_lemma_loop():
    memory = LemmaMemory(SessionMemory())
    result = VerifiedLemmaLoop().run(_route("medium"), [], [], {}, memory)
    assert result.rounds == []
    assert result.stop_reason == "not_high_risk"


def test_rejected_lemma_is_not_reintroduced():
    candidate = CandidateSolution(
        "c",
        "PrimarySolver",
        "direct",
        "x",
        "text",
        claims=[
            Claim(
                "bad",
                "false lemma",
                status="rejected",
                verification_state=ClaimVerificationState.REJECTED.value,
            )
        ],
    )
    result = VerifiedLemmaLoop().run(
        _route(), [candidate], [], {}, LemmaMemory(SessionMemory())
    )
    assert [lemma.status for lemma in result.lemmas] == ["rejected"]
    assert result.stop_reason == "no_new_progress"


def test_soft_obligation_review_does_not_promote_solver_visible_lemma():
    candidate = CandidateSolution(
        "c",
        "PrimarySolver",
        "direct",
        "QED",
        "text",
        claims=[Claim("claim", "sufficiency statement")],
    )
    evidence = [
        EvidenceRecord(
            "ev",
            "c",
            "claim",
            "llm:VerifierSkeptic",
            "pass",
            "soft",
            "reviewed",
            {"obligation_ids": ["c:sufficiency"]},
            {"role": "VerifierSkeptic"},
            VerificationCapability.PROOF_OBLIGATION_REVIEW.value,
        )
    ]
    result = VerifiedLemmaLoop().run(
        _route(),
        [candidate],
        evidence,
        {},
        LemmaMemory(SessionMemory()),
    )
    assert [lemma.status for lemma in result.lemmas] == ["conflicted"]


def test_verified_progress_can_drive_one_bounded_next_round():
    first = CandidateSolution(
        "first",
        "PrimarySolver",
        "direct",
        "x",
        "text",
        claims=[
            Claim(
                "first-claim",
                "first verified lemma",
                status="verified",
                verification_state=ClaimVerificationState.SEMANTICALLY_VERIFIED.value,
            )
        ],
    )
    calls: list[list[str]] = []

    def expand(verified, round_id):
        calls.append([lemma.lemma_id for lemma in verified])
        assert round_id == 2
        return CandidateSolution(
            "second",
            "PrimarySolver",
            "lemma-guided",
            "x",
            "text",
            claims=[
                Claim(
                    "second-claim",
                    "second verified lemma",
                    status="verified",
                    verification_state=ClaimVerificationState.SEMANTICALLY_VERIFIED.value,
                )
            ],
        )

    memory = LemmaMemory(SessionMemory())
    result = VerifiedLemmaLoop().run(
        _route(),
        [first],
        [],
        {},
        memory,
        expand_round=expand,
    )
    assert len(calls) == 1
    assert [candidate.candidate_id for candidate in result.generated_candidates] == ["second"]
    assert len(result.rounds) == 2
    assert result.rounds[1].input_lemma_ids == result.rounds[0].verified_lemma_ids
    assert len(memory.verified()) == 2
