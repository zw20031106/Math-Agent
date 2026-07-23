from __future__ import annotations

import re
from time import perf_counter

from mathforge.harness.budget import CallBudget
from mathforge.harness.errors import BudgetExceeded
from mathforge.harness.schemas import CandidateSolution
from mathforge.tools.executor import ToolExecutor


def normalized_answer(answer: str) -> str:
    return re.sub(r"\s+", "", answer).strip(".$").lower()


def equivalent_answers(
    left: CandidateSolution,
    right: CandidateSolution,
    tool_executor: ToolExecutor | None = None,
    budget: CallBudget | None = None,
) -> bool:
    if normalized_answer(left.final_answer) == normalized_answer(right.final_answer):
        return True
    if left.answer_type != "expression" or right.answer_type != "expression":
        return False
    tools = tool_executor or ToolExecutor()
    timeout = tools.default_timeout
    if budget is not None:
        try:
            timeout = budget.begin_tool_call(
                isolated=tools.is_isolated("symbolic_equivalence"),
                default_timeout=tools.default_timeout,
            )
        except BudgetExceeded:
            return False
    started = perf_counter()
    try:
        result = tools.execute(
            "symbolic_equivalence",
            {"left": left.final_answer, "right": right.final_answer},
            timeout=timeout,
        )
    finally:
        if budget is not None:
            budget.finish_tool_call(perf_counter() - started)
    return result.status == "pass" and result.strength == "hard"


def equivalence_clusters(
    candidates: list[CandidateSolution],
    tool_executor: ToolExecutor | None = None,
    budget: CallBudget | None = None,
) -> list[list[str]]:
    clusters: list[list[CandidateSolution]] = []
    for candidate in candidates:
        for cluster in clusters:
            if equivalent_answers(
                candidate,
                cluster[0],
                tool_executor,
                budget,
            ):
                cluster.append(candidate)
                break
        else:
            clusters.append([candidate])
    return [[candidate.candidate_id for candidate in cluster] for cluster in clusters]
