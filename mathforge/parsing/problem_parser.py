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


class ProblemParser:
    def parse(self, problem: str) -> ProblemIR:
        raw = problem if isinstance(problem, str) else str(problem)
        normalized = normalize_problem(raw)
        lowered = normalized.lower()
        options = [match.group(3).strip() for match in _OPTION_PATTERN.finditer(normalized)]
        problem_type = self._problem_type(lowered, options)
        answer_type = self._answer_type(lowered, problem_type)
        domains = {symbol: domain for symbol, domain in _DOMAIN_PATTERN.findall(normalized)}
        assumptions = self._assumptions(normalized)
        risk_flags: list[str] = []
        if not normalized:
            risk_flags.append("empty_problem")
        if not braces_balanced(normalized):
            risk_flags.append("unbalanced_latex")
        if problem_type in {"proof", "derivation"}:
            risk_flags.append("long_reasoning")
        return ProblemIR(
            raw_problem=raw,
            normalized_problem=normalized,
            problem_type=problem_type,
            answer_type=answer_type,
            symbols=sorted(set(_SYMBOL_PATTERN.findall(normalized))),
            assumptions=assumptions,
            domains=domains,
            requested_output=self._requested_output(normalized),
            options=options,
            risk_flags=risk_flags,
        )

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
    def _answer_type(lowered: str, problem_type: str) -> str:
        if problem_type == "multiple_choice":
            return "choice"
        if problem_type in {"proof", "explanation", "derivation"}:
            return "text"
        if any(marker in lowered for marker in ("矩阵", "matrix")):
            return "matrix"
        if any(marker in lowered for marker in ("区间", "interval")):
            return "interval"
        if any(marker in lowered for marker in ("集合", "solution set", "set of")):
            return "set"
        if any(marker in lowered for marker in ("整数", "integer")):
            return "integer"
        if any(marker in lowered for marker in ("分数", "fraction", "rational number")):
            return "fraction"
        return "expression"

    @staticmethod
    def _assumptions(normalized: str) -> list[str]:
        parts = re.split(r"[。.;；]|\b(?:where|given that|such that)\b", normalized)
        markers = (r"\in", ">", "<", "正", "非负", "integer", "real")
        return [part.strip() for part in parts if any(marker in part for marker in markers)][:8]

    @staticmethod
    def _requested_output(normalized: str) -> str:
        sentences = [part.strip() for part in re.split(r"[。.!?！？]", normalized) if part.strip()]
        return sentences[-1] if sentences else normalized
