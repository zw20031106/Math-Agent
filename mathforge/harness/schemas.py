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
class MathSession:
    session_id: str
    problem: str
    metadata: dict[str, Any]
    budget: CallBudget
    problem_ir: ProblemIR | None = None
    candidates: list[CandidateSolution] = field(default_factory=list)
    trace_events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "problem": self.problem,
            "metadata": dict(self.metadata),
            "budget": self.budget.to_dict(),
            "problem_ir": self.problem_ir.to_dict() if self.problem_ir else None,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "trace_events": [dict(event) for event in self.trace_events],
        }
