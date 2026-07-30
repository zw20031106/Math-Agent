from __future__ import annotations

from mathforge.harness.schemas import CandidateSolution, ProblemIR, ProofObligation
from mathforge.verification.capabilities import derive_claim_kind


class ProofObligationEngine:
    def plan_problem(
        self,
        problem: ProblemIR,
    ) -> list[ProofObligation]:
        """Plan candidate-independent obligations before any Solver call."""

        obligations: list[ProofObligation] = []

        def add(kind: str, description: str) -> None:
            if any(item.kind == kind for item in obligations):
                return
            obligations.append(
                ProofObligation(
                    obligation_id=f"problem:{kind}",
                    kind=kind,
                    description=description,
                    origin="problem",
                )
            )

        lowered = problem.normalized_problem.lower()
        if problem.problem_type == "proof":
            add(
                "definition",
                "all nonstandard objects and predicates are defined",
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
        ):
            add("boundary", "boundary and degenerate cases are handled")
        if any(
            marker in lowered
            for marker in (
                "交换",
                "interchange",
                "differentiate under",
                "sum and integral",
                "double sum",
                "order of summation",
            )
        ):
            add(
                "interchange",
                "limit, sum, integral, or derivative interchange is justified",
            )
        return obligations

    def generate(
        self,
        problem: ProblemIR,
        candidate: CandidateSolution,
        *,
        problem_obligations: list[ProofObligation] | None = None,
    ) -> list[ProofObligation]:
        templates = (
            self.plan_problem(problem)
            if problem_obligations is None
            else problem_obligations
        )
        obligations = [
            ProofObligation(
                obligation_id=f"{candidate.candidate_id}:{template.kind}",
                kind=template.kind,
                description=template.description,
                required=template.required,
                origin="problem",
            )
            for template in templates
        ]

        def add(kind: str, description: str, *, origin: str = "method") -> None:
            if not any(item.kind == kind for item in obligations):
                obligations.append(
                    ProofObligation(
                        obligation_id=f"{candidate.candidate_id}:{kind}",
                        kind=kind,
                        description=description,
                        origin=origin,
                    )
                )

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
        if (
            "boundary" in claim_kinds
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
                marker in public_text
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
        claim_by_id = {
            claim.claim_id: claim
            for claim in candidate.claims
        }
        conclusion_ids = [
            claim_id
            for step in candidate.method_steps
            if step.kind == "conclusion"
            for claim_id in step.claim_ids
            if claim_id in claim_by_id
        ]
        critical_ids = [
            claim.claim_id
            for claim in candidate.claims
            if claim.importance == "critical"
        ]
        fallback_ids = list(
            dict.fromkeys(
                [
                    *conclusion_ids,
                    *critical_ids,
                    *(claim.claim_id for claim in candidate.claims),
                ]
            )
        )
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
            if not matches and fallback_ids:
                matches = [claim_by_id[fallback_ids[0]]]
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
