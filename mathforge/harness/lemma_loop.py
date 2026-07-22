from __future__ import annotations

from dataclasses import dataclass

from mathforge.agents.lemma_curator import LemmaCurator
from mathforge.agents.verifier import LemmaVerifier
from mathforge.harness.schemas import (
    CandidateSolution,
    EvidenceRecord,
    LemmaCard,
    ProofObligation,
    RoundState,
    RoutePlan,
)
from mathforge.memory.lemma_memory import LemmaMemory


@dataclass
class LemmaLoopResult:
    lemmas: list[LemmaCard]
    rounds: list[RoundState]
    stop_reason: str

    @property
    def error_rate(self) -> float:
        checked = [lemma for lemma in self.lemmas if lemma.status in {"verified", "rejected", "conflicted"}]
        if not checked:
            return 0.0
        return sum(lemma.status != "verified" for lemma in checked) / len(checked)


class VerifiedLemmaLoop:
    def __init__(
        self,
        curator: LemmaCurator | None = None,
        verifier: LemmaVerifier | None = None,
    ) -> None:
        self._curator = curator or LemmaCurator()
        self._verifier = verifier or LemmaVerifier()

    def run(
        self,
        route: RoutePlan,
        candidates: list[CandidateSolution],
        evidence: list[EvidenceRecord],
        obligations: dict[str, list[ProofObligation]],
        lemma_memory: LemmaMemory,
    ) -> LemmaLoopResult:
        if route.risk_level != "high" or not route.use_lemma_loop:
            return LemmaLoopResult([], [], "not_high_risk")
        max_rounds = max(1, min(2, route.max_reasoning_rounds))
        all_lemmas: list[LemmaCard] = []
        rounds: list[RoundState] = []
        excluded: set[str] = set()
        input_verified: list[str] = []
        for round_id in range(1, max_rounds + 1):
            cards = self._curator.curate(
                candidates,
                round_id=round_id,
                excluded_statements=excluded,
            )
            verified: list[LemmaCard] = []
            rejected: list[LemmaCard] = []
            conflicts = 0
            for card in cards:
                checked = self._verifier.verify(card, candidates, evidence)
                all_lemmas.append(checked)
                excluded.add(" ".join(checked.statement.lower().split()))
                if checked.status == "verified":
                    verified.append(checked)
                    lemma_memory.add_verified(checked.to_dict())
                elif checked.status == "rejected":
                    rejected.append(checked)
                else:
                    conflicts += 1
            resolved = self._resolve_obligations(verified, obligations)
            unresolved = [
                item.obligation_id
                for items in obligations.values()
                for item in items
                if item.required and item.status != "satisfied"
            ]
            progress = len(verified) + len(resolved) - conflicts
            rounds.append(
                RoundState(
                    round_id=round_id,
                    input_lemma_ids=list(input_verified),
                    candidate_lemma_ids=[card.lemma_id for card in cards],
                    verified_lemma_ids=[card.lemma_id for card in verified],
                    rejected_lemma_ids=[card.lemma_id for card in rejected],
                    resolved_obligations=resolved,
                    unresolved_obligations=unresolved,
                    conflict_count=conflicts,
                    progress_score=float(progress),
                )
            )
            input_verified.extend(card.lemma_id for card in verified)
            if not cards:
                return LemmaLoopResult(all_lemmas, rounds, "no_new_lemmas")
            if progress <= 0:
                return LemmaLoopResult(all_lemmas, rounds, "no_new_progress")
        return LemmaLoopResult(all_lemmas, rounds, "round_limit")

    @staticmethod
    def _resolve_obligations(
        lemmas: list[LemmaCard],
        obligations: dict[str, list[ProofObligation]],
    ) -> list[str]:
        resolved: list[str] = []
        for obligation_list in obligations.values():
            for obligation in obligation_list:
                if obligation.status == "satisfied":
                    continue
                if any(obligation.kind in lemma.statement.lower() for lemma in lemmas):
                    obligation.status = "satisfied"
                    resolved.append(obligation.obligation_id)
        return resolved
