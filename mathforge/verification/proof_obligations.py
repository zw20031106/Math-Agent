from __future__ import annotations

from mathforge.harness.schemas import CandidateSolution, ProblemIR, ProofObligation


class ProofObligationEngine:
    def generate(
        self,
        problem: ProblemIR,
        candidate: CandidateSolution,
    ) -> list[ProofObligation]:
        obligations: list[ProofObligation] = []

        def add(kind: str, description: str) -> None:
            if not any(item.kind == kind for item in obligations):
                obligations.append(
                    ProofObligation(
                        obligation_id=f"{candidate.candidate_id}:{kind}",
                        kind=kind,
                        description=description,
                    )
                )

        lowered = problem.normalized_problem.lower()
        if problem.problem_type == "proof":
            add("definition", "all nonstandard objects and predicates are defined")
        if candidate.theorems:
            add("theorem_preconditions", "every invoked theorem has its hypotheses checked")
        if any(marker in lowered for marker in ("if and only if", "iff", "当且仅当", "充要")):
            add("necessity", "the necessary direction is established")
            add("sufficiency", "the sufficient direction is established")
        elif problem.problem_type == "proof":
            add("sufficiency", "the requested implication or conclusion is established")
        if any(marker in lowered for marker in ("存在", "exist")):
            add("existence", "existence is constructed or proved")
        if any(marker in lowered for marker in ("唯一", "unique")):
            add("uniqueness", "uniqueness is proved separately")
        if problem.problem_type in {"proof", "derivation"} or problem.answer_type in {"interval", "set"}:
            add("boundary", "boundary and degenerate cases are handled")
        if any(
            marker in lowered
            for marker in ("交换", "interchange", "differentiate under", "sum and integral")
        ):
            add("interchange", "limit, sum, integral, or derivative interchange is justified")
        self._resolve_from_claims(obligations, candidate)
        return obligations

    @staticmethod
    def _resolve_from_claims(
        obligations: list[ProofObligation], candidate: CandidateSolution
    ) -> None:
        for obligation in obligations:
            matches = [
                claim
                for claim in candidate.claims
                if claim.check_type == obligation.kind or obligation.kind in claim.statement.lower()
            ]
            obligation.source_claim_ids = [claim.claim_id for claim in matches]
            if matches and all(claim.status == "verified" for claim in matches):
                obligation.status = "satisfied"
            elif any(claim.status == "rejected" for claim in matches):
                obligation.status = "failed"
        candidate.unresolved_obligations = [
            obligation.obligation_id
            for obligation in obligations
            if obligation.required and obligation.status != "satisfied"
        ]
