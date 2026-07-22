from __future__ import annotations

import re

from mathforge.harness.schemas import CandidateSolution
from mathforge.tools.executor import ToolExecutor


def normalized_answer(answer: str) -> str:
    return re.sub(r"\s+", "", answer).strip(".$").lower()


def equivalent_answers(
    left: CandidateSolution,
    right: CandidateSolution,
    tool_executor: ToolExecutor | None = None,
) -> bool:
    if normalized_answer(left.final_answer) == normalized_answer(right.final_answer):
        return True
    if left.answer_type != "expression" or right.answer_type != "expression":
        return False
    result = (tool_executor or ToolExecutor()).execute(
        "symbolic_equivalence",
        {"left": left.final_answer, "right": right.final_answer},
    )
    return result.status == "pass" and result.strength == "hard"


def equivalence_clusters(
    candidates: list[CandidateSolution],
    tool_executor: ToolExecutor | None = None,
) -> list[list[str]]:
    clusters: list[list[CandidateSolution]] = []
    for candidate in candidates:
        for cluster in clusters:
            if equivalent_answers(candidate, cluster[0], tool_executor):
                cluster.append(candidate)
                break
        else:
            clusters.append([candidate])
    return [[candidate.candidate_id for candidate in cluster] for cluster in clusters]
