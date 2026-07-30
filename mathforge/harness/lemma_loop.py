from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

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
    generated_candidates: list[CandidateSolution]
    expansion_dependencies: dict[str, list[str]] = field(default_factory=dict)

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
        *,
        expand_round: Callable[[list[LemmaCard], int], CandidateSolution | None] | None = None,
        target: str = "",
    ) -> LemmaLoopResult:
        if route.risk_level != "high" or not route.use_lemma_loop:
            return LemmaLoopResult([], [], "not_high_risk", [])
        max_rounds = max(1, min(2, route.max_reasoning_rounds))
        all_lemmas: list[LemmaCard] = []
        rounds: list[RoundState] = []
        excluded: set[str] = set()
        input_verified: list[str] = []
        working_candidates = list(candidates)
        generated_candidates: list[CandidateSolution] = []
        expansion_dependencies: dict[str, list[str]] = {}
        for round_id in range(1, max_rounds + 1):
            cards = self._curator.curate(
                working_candidates,
                round_id=round_id,
                excluded_statements=excluded,
                obligations=obligations,
                target=target,
            )
            verified: list[LemmaCard] = []
            rejected: list[LemmaCard] = []
            conflicts = 0
            for card in cards:
                checked = self._verifier.verify(card, working_candidates, evidence)
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
                return LemmaLoopResult(
                    all_lemmas,
                    rounds,
                    "no_new_lemmas",
                    generated_candidates,
                    expansion_dependencies,
                )
            if progress <= 0:
                return LemmaLoopResult(
                    all_lemmas,
                    rounds,
                    "no_new_progress",
                    generated_candidates,
                    expansion_dependencies,
                )
            if round_id < max_rounds and verified and expand_round is not None:
                try:
                    expanded = expand_round(verified, round_id + 1)
                except Exception:
                    return LemmaLoopResult(
                        all_lemmas,
                        rounds,
                        "round_expansion_failed",
                        generated_candidates,
                        expansion_dependencies,
                    )
                if expanded is not None:
                    working_candidates.append(expanded)
                    generated_candidates.append(expanded)
                    expansion_dependencies[expanded.candidate_id] = [
                        lemma.lemma_id for lemma in verified
                    ]
        return LemmaLoopResult(
            all_lemmas,
            rounds,
            "round_limit",
            generated_candidates,
            expansion_dependencies,
        )

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
                if any(
                    obligation.obligation_id in lemma.target_obligation_ids
                    for lemma in lemmas
                ):
                    obligation.status = "satisfied"
                    obligation.satisfaction_evidence_ids.extend(
                        evidence_id
                        for lemma in lemmas
                        if obligation.obligation_id
                        in lemma.target_obligation_ids
                        for evidence_id in lemma.evidence_ids
                        if evidence_id
                        not in obligation.satisfaction_evidence_ids
                    )
                    resolved.append(obligation.obligation_id)
        return resolved
