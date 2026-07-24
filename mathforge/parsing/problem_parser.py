from __future__ import annotations

import re

from mathforge.harness.schemas import ProblemIR
from mathforge.parsing.latex import braces_balanced
from mathforge.parsing.normalization import normalize_problem


_OPTION_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:[（(]?([A-H])[)）.、:]|([A-H])\s+)\s*([^\n]+)",
    re.IGNORECASE,
)
_SYMBOL_PATTERN = re.compile(r"(?<![\\A-Za-z])([a-zA-Z])(?![A-Za-z])")
_DOMAIN_PATTERN = re.compile(
    r"([a-zA-Z])\s*(?:\\in|in)\s*(\\mathbb\{[RZQNC]\}|[RZQNC])",
    re.IGNORECASE,
)
_REQUEST_PATTERN = re.compile(
    r"(?:求解|求|计算|确定|写出|给出|判断|解答|"
    r"\b(?:find|compute|calculate|determine|write\s+down|give)\b)\s*",
    re.IGNORECASE,
)
_INTEGER_TARGETS = (
    "个数",
    "多少个",
    "维数",
    "零度",
    "计重数",
    "映射度数",
)
_SCALAR_TARGETS = (
    "极限",
    "积分",
    "期望",
    "概率",
    "方差",
    "范数",
    "距离",
    "半径",
    "系数",
    "留数",
    "曲率",
    "误差",
    "条件数",
    "长度",
    "成本",
    "流值",
    "统计量",
    "估计",
    "行列式",
)


class ProblemParser:
    def parse(self, problem: str) -> ProblemIR:
        raw = problem if isinstance(problem, str) else str(problem)
        normalized = normalize_problem(raw)
        lowered = normalized.lower()
        options = [match.group(3).strip() for match in _OPTION_PATTERN.finditer(normalized)]
        requested_output = self._requested_output(normalized)
        target_phrase, target_confidence = self._target_phrase(requested_output)
        target_lowered = target_phrase.lower()
        problem_type = self._problem_type(target_lowered, options)
        answer_type, type_confidence = self._answer_type(
            target_lowered,
            problem_type,
            lowered,
        )
        parser_confidence = round(
            min(target_confidence, type_confidence),
            4,
        )
        domains = {symbol: domain for symbol, domain in _DOMAIN_PATTERN.findall(normalized)}
        assumptions = self._assumptions(normalized)
        risk_flags: list[str] = []
        if not normalized:
            risk_flags.append("empty_problem")
        if not braces_balanced(normalized):
            risk_flags.append("unbalanced_latex")
        if problem_type in {"proof", "derivation"}:
            risk_flags.append("long_reasoning")
        parsed = ProblemIR(
            raw_problem=raw,
            normalized_problem=normalized,
            problem_type=problem_type,
            answer_type=answer_type,
            symbols=sorted(set(_SYMBOL_PATTERN.findall(normalized))),
            assumptions=assumptions,
            domains=domains,
            requested_output=requested_output,
            target_phrase=target_phrase,
            parser_confidence=parser_confidence,
            options=options,
            risk_flags=risk_flags,
        )
        parsed.validate()
        return parsed

    @staticmethod
    def _problem_type(lowered: str, options: list[str]) -> str:
        if options or any(marker in lowered for marker in ("选择", "which of", "select ")):
            return "multiple_choice"
        if any(marker in lowered for marker in ("证明", "prove", "show that", "证毕")):
            return "proof"
        if any(marker in lowered for marker in ("推导", "derive", "deduce")):
            return "derivation"
        if any(marker in lowered for marker in ("解释", "说明为什么", "explain", "why ")):
            return "explanation"
        if any(marker in lowered for marker in ("填空", "fill in", "____")):
            return "fill_blank"
        return "calculation"

    @staticmethod
    def _answer_type(
        target: str,
        problem_type: str,
        full_problem: str,
    ) -> tuple[str, float]:
        if problem_type == "multiple_choice":
            return "choice", 1.0
        if problem_type in {"proof", "explanation", "derivation"}:
            return "text", 0.98
        if any(marker in target for marker in _INTEGER_TARGETS):
            return "integer", 0.98
        if any(marker in target for marker in ("收敛区间", "解的区间", "interval of")):
            return "interval", 0.98
        if any(marker in target for marker in ("特征多项式", "最小多项式")):
            return "polynomial", 0.98
        if any(
            marker in target
            for marker in (
                "斜率向量",
                "系数向量",
                "平稳分布",
                "向量",
            )
        ):
            return "vector", 0.96
        if "最优解" in target and re.search(
            r"\([A-Za-z]\s*,\s*[A-Za-z]\)",
            target,
        ):
            return "vector", 0.94
        if (
            re.search(r"\bx\s*\(", target)
            and re.search(r"\bx\s*\(\s*0\s*\)\s*=.*\^t", full_problem)
        ):
            return "vector", 0.9
        if any(marker in target for marker in ("jordan 块大小", "惯性指数")):
            return "tuple", 0.96
        if any(marker in target for marker in ("同调群", "商群", "群结构", "环结构")):
            return "algebraic_structure", 0.98
        if (
            any(marker in target for marker in ("的谱", "其谱", "solution set", "解集"))
            and "谱半径" not in target
        ):
            return "set", 0.94
        if any(marker in target for marker in _SCALAR_TARGETS):
            return "expression", 0.98
        if any(marker in target for marker in ("逆矩阵", "矩阵表示", "matrix representation")):
            return "matrix", 0.94
        if any(marker in target for marker in ("有序对", "ordered tuple")):
            return "tuple", 0.9
        if any(marker in target for marker in ("分数", "fraction", "rational number")):
            return "fraction", 0.9
        return "expression", 0.78

    @staticmethod
    def _assumptions(normalized: str) -> list[str]:
        parts = re.split(r"[。.;；]|\b(?:where|given that|such that)\b", normalized)
        markers = (r"\in", ">", "<", "正", "非负", "integer", "real")
        return [part.strip() for part in parts if any(marker in part for marker in markers)][:8]

    @staticmethod
    def _requested_output(normalized: str) -> str:
        sentences = [part.strip() for part in re.split(r"[。.!?！？]", normalized) if part.strip()]
        return sentences[-1] if sentences else normalized

    @staticmethod
    def _target_phrase(requested_output: str) -> tuple[str, float]:
        matches = list(_REQUEST_PATTERN.finditer(requested_output))
        if matches:
            target = requested_output[matches[-1].start() :].strip(" ，,;；:")
            return target, 0.98 if target else 0.6
        if any(marker in requested_output for marker in ("是多少", "有多少", "为何")):
            return requested_output.strip(), 0.86
        return requested_output.strip(), 0.72 if requested_output.strip() else 0.0
