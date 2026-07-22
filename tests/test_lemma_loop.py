from __future__ import annotations

from mathforge.harness.lemma_loop import VerifiedLemmaLoop
from mathforge.harness.schemas import CandidateSolution, Claim, RoutePlan
from mathforge.memory.lemma_memory import LemmaMemory
from mathforge.memory.session_memory import SessionMemory


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
            Claim("verified", "sufficiency lemma", status="verified"),
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
        claims=[Claim("bad", "false lemma", status="rejected")],
    )
    result = VerifiedLemmaLoop().run(
        _route(), [candidate], [], {}, LemmaMemory(SessionMemory())
    )
    assert [lemma.status for lemma in result.lemmas] == ["rejected"]
    assert result.stop_reason == "no_new_progress"
