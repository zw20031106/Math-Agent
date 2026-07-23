from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from time import perf_counter

from mathforge.harness.budget import CallBudget
from mathforge.harness.errors import BudgetExceeded
from mathforge.harness.schemas import CandidateSolution, ProblemIR
from mathforge.tools.executor import ToolExecutor


class EquivalenceStatus(str, Enum):
    EQUIVALENT = "equivalent"
    DIFFERENT = "different"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EquivalenceAnalysis:
    clusters: list[list[str]]
    unknown_pairs: list[tuple[str, str]]
    disagreement_pairs: list[tuple[str, str]]


def normalized_answer(answer: str) -> str:
    return re.sub(r"\s+", "", answer).strip(".$").lower()


def equivalent_answers(
    left: CandidateSolution,
    right: CandidateSolution,
    problem: ProblemIR | None = None,
    tool_executor: ToolExecutor | None = None,
    budget: CallBudget | None = None,
) -> EquivalenceStatus:
    if normalized_answer(left.final_answer) == normalized_answer(right.final_answer):
        return EquivalenceStatus.EQUIVALENT

    answer_type = problem.answer_type if problem is not None else left.answer_type
    assumptions = list(problem.assumptions) if problem is not None else []
    domains = dict(problem.domains) if problem is not None else {}
    high_risk = answer_type in {"interval", "set"} or any(
        marker in f"{left.final_answer} {right.final_answer}".lower()
        for marker in ("sqrt", "piecewise", "abs(", "|")
    )
    if high_risk and not assumptions and not domains:
        return EquivalenceStatus.UNKNOWN
    if answer_type != "expression":
        return (
            EquivalenceStatus.UNKNOWN
            if high_risk
            else EquivalenceStatus.DIFFERENT
        )

    tools = tool_executor or ToolExecutor()
    timeout = tools.default_timeout
    if budget is not None:
        try:
            timeout = budget.begin_tool_call(
                isolated=tools.is_isolated("symbolic_equivalence"),
                default_timeout=tools.default_timeout,
            )
        except BudgetExceeded:
            return EquivalenceStatus.UNKNOWN
    started = perf_counter()
    try:
        result = tools.execute(
            "symbolic_equivalence",
            {
                "left": left.final_answer,
                "right": right.final_answer,
                "assumptions": assumptions,
                "domains": domains,
            },
            timeout=timeout,
        )
    finally:
        if budget is not None:
            budget.finish_tool_call(perf_counter() - started)
    if result.status == "pass" and result.strength == "hard":
        return EquivalenceStatus.EQUIVALENT
    if result.status == "fail" and result.strength == "hard":
        return EquivalenceStatus.DIFFERENT
    return EquivalenceStatus.UNKNOWN


def analyze_equivalence(
    candidates: list[CandidateSolution],
    problem: ProblemIR | None = None,
    tool_executor: ToolExecutor | None = None,
    budget: CallBudget | None = None,
) -> EquivalenceAnalysis:
    parent = list(range(len(candidates)))
    unknown_pairs: list[tuple[str, str]] = []
    disagreement_pairs: list[tuple[str, str]] = []

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left_index: int, right_index: int) -> None:
        left_root = find(left_index)
        right_root = find(right_index)
        if left_root != right_root:
            parent[right_root] = left_root

    for left_index, left in enumerate(candidates):
        for right_index in range(left_index + 1, len(candidates)):
            right = candidates[right_index]
            status = equivalent_answers(
                left,
                right,
                problem,
                tool_executor,
                budget,
            )
            pair = (left.candidate_id, right.candidate_id)
            if status == EquivalenceStatus.EQUIVALENT:
                union(left_index, right_index)
            elif status == EquivalenceStatus.DIFFERENT:
                disagreement_pairs.append(pair)
            else:
                unknown_pairs.append(pair)

    grouped: dict[int, list[str]] = {}
    for index, candidate in enumerate(candidates):
        grouped.setdefault(find(index), []).append(candidate.candidate_id)
    return EquivalenceAnalysis(
        clusters=list(grouped.values()),
        unknown_pairs=unknown_pairs,
        disagreement_pairs=disagreement_pairs,
    )


def equivalence_clusters(
    candidates: list[CandidateSolution],
    tool_executor: ToolExecutor | None = None,
    budget: CallBudget | None = None,
    *,
    problem: ProblemIR | None = None,
) -> list[list[str]]:
    return analyze_equivalence(
        candidates,
        problem,
        tool_executor,
        budget,
    ).clusters
