from __future__ import annotations

from mathforge.harness.schemas import CandidateSolution, ProblemIR, ProofObligation
from mathforge.verification.capabilities import derive_claim_kind


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
        public_text = " ".join(
            [
                candidate.method,
                candidate.solution_text,
                *candidate.public_solution_steps,
                *(claim.statement for claim in candidate.claims),
                *(step.theorem for step in candidate.method_steps),
            ]
        ).lower()
        operation_kinds = {step.kind for step in candidate.method_steps}
        claim_kinds = {
            derive_claim_kind(claim.check_type)
            for claim in candidate.claims
        }

        if problem.problem_type == "proof":
            add("definition", "all nonstandard objects and predicates are defined")
        if (
            candidate.theorems
            or "theorem_application" in operation_kinds
            or any(
                marker in public_text
                for marker in (
                    " theorem",
                    "generating function",
                    "定理",
                    "恒等式",
                    "母函数",
                )
            )
        ):
            add(
                "theorem_preconditions",
                "every invoked theorem has its hypotheses checked",
            )
        if any(
            marker in lowered
            for marker in ("if and only if", "iff", "当且仅当", "充要")
        ):
            add("necessity", "the necessary direction is established")
            add("sufficiency", "the sufficient direction is established")
        elif problem.problem_type == "proof":
            add(
                "sufficiency",
                "the requested implication or conclusion is established",
            )
        if any(marker in lowered for marker in ("存在", "exist")):
            add("existence", "existence is constructed or proved")
        if any(marker in lowered for marker in ("唯一", "unique")):
            add("uniqueness", "uniqueness is proved separately")
        if (
            problem.problem_type in {"proof", "derivation"}
            or problem.answer_type in {"interval", "set"}
            or "boundary" in claim_kinds
            or any(
                marker in public_text
                for marker in (
                    "boundary",
                    "endpoint",
                    "degenerate",
                    "边界",
                    "端点",
                )
            )
        ):
            add("boundary", "boundary and degenerate cases are handled")
        if (
            "interchange" in claim_kinds
            or any(
                marker in f"{lowered} {public_text}"
                for marker in (
                    "交换",
                    "interchange",
                    "differentiate under",
                    "sum and integral",
                    "double sum",
                    "order of summation",
                )
            )
        ):
            add(
                "interchange",
                "limit, sum, integral, or derivative interchange is justified",
            )
        if candidate.assumptions and any(
            marker in public_text
            for marker in ("assume", "provided", "condition", "假设", "条件")
        ):
            add(
                "theorem_preconditions",
                "candidate assumptions and invoked conditions are justified",
            )
        self._resolve_from_claims(obligations, candidate)
        return obligations

    @staticmethod
    def _resolve_from_claims(
        obligations: list[ProofObligation],
        candidate: CandidateSolution,
    ) -> None:
        for claim in candidate.claims:
            claim.claim_kind = derive_claim_kind(claim.check_type)
        for obligation in obligations:
            matches = [
                claim
                for claim in candidate.claims
                if claim.claim_kind == obligation.kind
            ]
            if obligation.kind == "theorem_preconditions":
                referenced = {
                    claim_id
                    for step in candidate.method_steps
                    if step.kind == "theorem_application"
                    for claim_id in step.claim_ids
                }
                matches.extend(
                    claim
                    for claim in candidate.claims
                    if claim.claim_id in referenced and claim not in matches
                )
            obligation.source_claim_ids = [
                claim.claim_id for claim in matches
            ]
            obligation.satisfaction_evidence_ids = []
            if any(claim.status == "rejected" for claim in matches):
                obligation.status = "failed"
            else:
                obligation.status = "unresolved"
        candidate.unresolved_obligations = [
            obligation.obligation_id
            for obligation in obligations
            if obligation.required and obligation.status != "satisfied"
        ]
