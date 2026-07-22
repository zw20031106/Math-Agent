from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mathforge.harness.budget import CallBudget


@dataclass
class ProblemIR:
    raw_problem: str
    normalized_problem: str
    problem_type: str
    answer_type: str
    subject_candidates: list[tuple[str, float]] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    domains: dict[str, str] = field(default_factory=dict)
    requested_output: str = ""
    options: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "raw_problem": self.raw_problem,
            "normalized_problem": self.normalized_problem,
            "problem_type": self.problem_type,
            "answer_type": self.answer_type,
            "subject_candidates": [list(item) for item in self.subject_candidates],
            "symbols": list(self.symbols),
            "assumptions": list(self.assumptions),
            "domains": dict(self.domains),
            "requested_output": self.requested_output,
            "options": list(self.options),
            "risk_flags": list(self.risk_flags),
        }


@dataclass
class Claim:
    claim_id: str
    statement: str
    depends_on: list[str] = field(default_factory=list)
    check_type: str = "reasoning"
    importance: str = "supporting"
    status: str = "unverified"

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "depends_on": list(self.depends_on),
            "check_type": self.check_type,
            "importance": self.importance,
            "status": self.status,
        }


@dataclass
class CandidateSolution:
    candidate_id: str
    role: str
    method: str
    final_answer: str
    answer_type: str
    assumptions: list[str] = field(default_factory=list)
    theorems: list[str] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    solution_text: str = ""
    unresolved_obligations: list[str] = field(default_factory=list)
    parse_status: str = "parsed"
    version: int = 1

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "role": self.role,
            "method": self.method,
            "final_answer": self.final_answer,
            "answer_type": self.answer_type,
            "assumptions": list(self.assumptions),
            "theorems": list(self.theorems),
            "claims": [claim.to_dict() for claim in self.claims],
            "solution_text": self.solution_text,
            "unresolved_obligations": list(self.unresolved_obligations),
            "parse_status": self.parse_status,
            "version": self.version,
        }


@dataclass
class RoutePlan:
    primary_subject: str
    auxiliary_subject: str | None
    problem_type: str
    answer_type: str
    risk_level: str
    selected_skills: list[str] = field(default_factory=list)
    selected_tools: list[str] = field(default_factory=list)
    candidate_count: int = 1
    max_reasoning_rounds: int = 1
    use_rag: bool = False
    use_lemma_loop: bool = False
    use_llm_finalizer: bool = False

    def to_dict(self) -> dict:
        return {
            "primary_subject": self.primary_subject,
            "auxiliary_subject": self.auxiliary_subject,
            "problem_type": self.problem_type,
            "answer_type": self.answer_type,
            "risk_level": self.risk_level,
            "selected_skills": list(self.selected_skills),
            "selected_tools": list(self.selected_tools),
            "candidate_count": self.candidate_count,
            "max_reasoning_rounds": self.max_reasoning_rounds,
            "use_rag": self.use_rag,
            "use_lemma_loop": self.use_lemma_loop,
            "use_llm_finalizer": self.use_llm_finalizer,
        }


@dataclass
class EvidenceRecord:
    evidence_id: str
    candidate_id: str
    claim_id: str | None
    evidence_type: str
    status: str
    strength: str
    description: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "candidate_id": self.candidate_id,
            "claim_id": self.claim_id,
            "evidence_type": self.evidence_type,
            "status": self.status,
            "strength": self.strength,
            "description": self.description,
            "payload": dict(self.payload),
        }


@dataclass
class ProofObligation:
    obligation_id: str
    kind: str
    description: str
    required: bool = True
    status: str = "unresolved"
    source_claim_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "obligation_id": self.obligation_id,
            "kind": self.kind,
            "description": self.description,
            "required": self.required,
            "status": self.status,
            "source_claim_ids": list(self.source_claim_ids),
        }


@dataclass
class LemmaCard:
    lemma_id: str
    statement: str
    conditions: list[str]
    dependencies: list[str]
    proof_sketch: str
    status: str
    evidence_ids: list[str]
    source_round: int
    scope: str = "current_problem"

    def to_dict(self) -> dict:
        return {
            "lemma_id": self.lemma_id,
            "statement": self.statement,
            "conditions": list(self.conditions),
            "dependencies": list(self.dependencies),
            "proof_sketch": self.proof_sketch,
            "status": self.status,
            "evidence_ids": list(self.evidence_ids),
            "source_round": self.source_round,
            "scope": self.scope,
        }


@dataclass
class RoundState:
    round_id: int
    input_lemma_ids: list[str]
    candidate_lemma_ids: list[str]
    verified_lemma_ids: list[str]
    rejected_lemma_ids: list[str]
    resolved_obligations: list[str]
    unresolved_obligations: list[str]
    conflict_count: int
    progress_score: float

    def to_dict(self) -> dict:
        return {
            "round_id": self.round_id,
            "input_lemma_ids": list(self.input_lemma_ids),
            "candidate_lemma_ids": list(self.candidate_lemma_ids),
            "verified_lemma_ids": list(self.verified_lemma_ids),
            "rejected_lemma_ids": list(self.rejected_lemma_ids),
            "resolved_obligations": list(self.resolved_obligations),
            "unresolved_obligations": list(self.unresolved_obligations),
            "conflict_count": self.conflict_count,
            "progress_score": self.progress_score,
        }


@dataclass
class MathSession:
    session_id: str
    problem: str
    metadata: dict[str, Any]
    budget: CallBudget
    problem_ir: ProblemIR | None = None
    route_plan: RoutePlan | None = None
    candidates: list[CandidateSolution] = field(default_factory=list)
    evidence: list[EvidenceRecord] = field(default_factory=list)
    proof_obligations: dict[str, list[ProofObligation]] = field(default_factory=dict)
    working_memory: Any = None
    lemma_memory: Any = None
    lemmas: list[LemmaCard] = field(default_factory=list)
    rounds: list[RoundState] = field(default_factory=list)
    trace_events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "problem": self.problem,
            "metadata": dict(self.metadata),
            "budget": self.budget.to_dict(),
            "problem_ir": self.problem_ir.to_dict() if self.problem_ir else None,
            "route_plan": self.route_plan.to_dict() if self.route_plan else None,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "evidence": [record.to_dict() for record in self.evidence],
            "proof_obligations": {
                candidate_id: [obligation.to_dict() for obligation in obligations]
                for candidate_id, obligations in self.proof_obligations.items()
            },
            "working_memory": (
                self.working_memory.to_dict()
                if self.working_memory is not None and hasattr(self.working_memory, "to_dict")
                else None
            ),
            "lemma_memory": (
                self.lemma_memory.to_dict()
                if self.lemma_memory is not None and hasattr(self.lemma_memory, "to_dict")
                else None
            ),
            "lemmas": [lemma.to_dict() for lemma in self.lemmas],
            "rounds": [round_state.to_dict() for round_state in self.rounds],
            "trace_events": [dict(event) for event in self.trace_events],
        }
