from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from mathforge.agents.router_planner import RouterRuleEngine
from mathforge.parsing.problem_parser import ProblemParser


SUBJECT_LABELS = {
    "抽象代数": "abstract-algebra",
    "高等代数": "advanced-linear-algebra",
    "数学分析": "advanced-real-analysis",
    "复分析": "complex-analysis",
    "泛函分析": "functional-analysis",
    "测度积分": "measure-integration",
    "常微分方程": "ordinary-differential-equations",
    "偏微分方程": "partial-differential-equations",
    "随机过程": "stochastic-processes",
    "运筹学": "operations-research",
    "线性回归": "regression",
    "微分几何": "differential-geometry",
    "数值分析": "numerical-analysis",
    "概率论": "probability",
    "统计推断": "statistics",
    "拓扑学": "topology",
}


@dataclass(frozen=True)
class RoutingEvaluation:
    case_count: int
    top1_hits: int
    top2_hits: int
    general_top1_count: int
    top1_misses: tuple[dict[str, object], ...]
    top2_misses: tuple[dict[str, object], ...]

    @property
    def top1_accuracy(self) -> float:
        return self.top1_hits / self.case_count if self.case_count else 0.0

    @property
    def top2_accuracy(self) -> float:
        return self.top2_hits / self.case_count if self.case_count else 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "case_count": self.case_count,
            "top1_hits": self.top1_hits,
            "top1_accuracy": self.top1_accuracy,
            "top2_hits": self.top2_hits,
            "top2_accuracy": self.top2_accuracy,
            "general_top1_count": self.general_top1_count,
            "top1_misses": list(self.top1_misses),
            "top2_misses": list(self.top2_misses),
        }


def evaluate_router_gold(
    path: Path,
    *,
    router: RouterRuleEngine | None = None,
    parser: ProblemParser | None = None,
) -> RoutingEvaluation:
    rule_engine = router or RouterRuleEngine()
    problem_parser = parser or ProblemParser()
    top1_hits = 0
    top2_hits = 0
    general_top1_count = 0
    top1_misses: list[dict[str, object]] = []
    top2_misses: list[dict[str, object]] = []
    case_count = 0

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw_line.strip():
            continue
        payload = json.loads(raw_line)
        expected = SUBJECT_LABELS.get(str(payload.get("subject", "")))
        if expected is None:
            raise ValueError(
                f"unsupported routing subject at line {line_number}: "
                f"{payload.get('subject')}"
            )
        ranked = rule_engine.rank(
            problem_parser.parse(str(payload.get("problem", "")))
        )
        predicted = [subject for subject, _ in ranked]
        case_count += 1
        if predicted[0] == "general-math":
            general_top1_count += 1
        miss = {
            "idx": payload.get("idx"),
            "expected": expected,
            "predicted": predicted[:2],
        }
        if expected == predicted[0]:
            top1_hits += 1
        else:
            top1_misses.append(miss)
        if expected in predicted[:2]:
            top2_hits += 1
        else:
            top2_misses.append(miss)

    return RoutingEvaluation(
        case_count=case_count,
        top1_hits=top1_hits,
        top2_hits=top2_hits,
        general_top1_count=general_top1_count,
        top1_misses=tuple(top1_misses),
        top2_misses=tuple(top2_misses),
    )
