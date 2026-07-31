from __future__ import annotations

import re
from typing import Any

from mathforge.harness.schemas import (
    AnswerType,
    ProblemIR,
    ProblemType,
    ResponseMode,
)
from mathforge.parsing.latex import braces_balanced
from mathforge.parsing.normalization import normalize_problem


_OPTION_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:"
    r"\((?P<ascii_paren>[A-H])\)|"
    r"（(?P<cjk_paren>[A-H])）|"
    r"(?P<punctuated>[A-H])[)）.、:：]"
    r")\s*(?P<content>[^\n]+)",
    re.IGNORECASE,
)
_SYMBOL_PATTERN = re.compile(r"(?<![\\A-Za-z])([a-zA-Z])(?![A-Za-z])")
_DOMAIN_PATTERN = re.compile(
    r"([a-zA-Z])\s*(?:\\in|in)\s*(\\mathbb\{[RZQNC]\}|[RZQNC])",
    re.IGNORECASE,
)
_REQUEST_PATTERN = re.compile(
    r"(?:求解|求|计算|确定|写出|给出|判断|解答|"
    r"\b(?:find|compute|calculate|determine|write\s+down|give|solve|"
    r"prove|show|explain|select)\b)\s*",
    re.IGNORECASE,
)
_CHOICE_INTENT = re.compile(
    r"(?:选择|下列|which\s+of|select\s+(?:the\s+)?(?:correct|best))",
    re.IGNORECASE,
)
_QUANTIFIER_PATTERN = re.compile(
    r"\b(?:for\s+all|for\s+every|every|any|there\s+exists|exists?|unique(?:ly)?)\b"
    r"|(?:任意|所有|每个|存在|唯一)",
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
    def parse(
        self,
        problem: str,
        metadata: dict[str, Any] | None = None,
    ) -> ProblemIR:
        raw = problem if isinstance(problem, str) else str(problem)
        normalized = normalize_problem(raw)
        lowered = normalized.lower()
        options = self._options(normalized)
        requested_output = self._requested_output(normalized)
        target_phrase, target_confidence = self._target_phrase(requested_output)
        target_lowered = target_phrase.lower()
        problem_type = self._metadata_enum(
            metadata,
            "problem_type",
            ProblemType,
        ) or self._problem_type(target_lowered, options)
        answer_type, type_confidence = self._answer_type(
            target_lowered,
            problem_type,
            lowered,
        )
        metadata_answer_type = self._metadata_enum(
            metadata,
            "answer_type",
            AnswerType,
        )
        if metadata_answer_type:
            answer_type = metadata_answer_type
            type_confidence = 1.0
        response_mode = self._metadata_enum(
            metadata,
            "response_mode",
            ResponseMode,
        ) or self._response_mode(problem_type, lowered)
        parser_confidence = round(
            min(target_confidence, type_confidence),
            4,
        )
        domains = {symbol: domain for symbol, domain in _DOMAIN_PATTERN.findall(normalized)}
        constraints = self._constraints(normalized)
        assumptions = self._assumptions(normalized)
        definitions = self._definitions(normalized)
        quantifiers = self._quantifiers(normalized)
        target_kind = self._target_kind(
            problem_type,
            answer_type,
            target_lowered,
            lowered,
        )
        difficulty_features = self._difficulty_features(
            normalized,
            problem_type=problem_type,
            constraints=constraints,
            quantifiers=quantifiers,
            target_kind=target_kind,
        )
        ambiguities = self._ambiguities(
            normalized,
            options=options,
            target_phrase=target_phrase,
            answer_type_confidence=type_confidence,
            target_kind=target_kind,
        )
        risk_flags: list[str] = []
        if not normalized:
            risk_flags.append("empty_problem")
        if not braces_balanced(normalized):
            risk_flags.append("unbalanced_latex")
        if problem_type in {"proof", "derivation"}:
            risk_flags.append("long_reasoning")
        if ambiguities:
            risk_flags.append("parser_ambiguity")
        if difficulty_features:
            risk_flags.append("structural_difficulty")
        parsed = ProblemIR(
            raw_problem=raw,
            normalized_problem=normalized,
            problem_type=problem_type,
            answer_type=answer_type,
            response_mode=response_mode,
            symbols=sorted(set(_SYMBOL_PATTERN.findall(normalized))),
            assumptions=assumptions,
            domains=domains,
            requested_output=requested_output,
            target_phrase=target_phrase,
            target_kind=target_kind,
            parser_confidence=parser_confidence,
            answer_type_confidence=round(type_confidence, 4),
            options=options,
            definitions=definitions,
            quantifiers=quantifiers,
            constraints=constraints,
            ambiguities=ambiguities,
            difficulty_features=difficulty_features,
            subproblem_hints=self._subproblem_hints(
                difficulty_features,
                target_kind,
            ),
            risk_flags=risk_flags,
        )
        parsed.validate()
        return parsed

    @staticmethod
    def _metadata_enum(
        metadata: dict[str, Any] | None,
        key: str,
        enum_type,
    ) -> str:
        if not isinstance(metadata, dict):
            return ""
        value = metadata.get(key)
        if not isinstance(value, str):
            return ""
        normalized = value.strip().lower()
        return (
            normalized
            if normalized in {item.value for item in enum_type}
            else ""
        )

    @staticmethod
    def _response_mode(problem_type: str, lowered: str) -> str:
        if problem_type == ProblemType.PROOF.value or any(
            marker in lowered
            for marker in (
                "证明",
                "证实",
                "试证",
                "prove ",
                "prove that",
                "show that",
            )
        ):
            return ResponseMode.PROOF_FULL.value
        if problem_type in {
            ProblemType.DERIVATION.value,
            ProblemType.EXPLANATION.value,
        } or any(
            marker in lowered
            for marker in (
                "写出过程",
                "给出过程",
                "推导",
                "说明理由",
                "解释原因",
                "show your work",
                "derive",
                "deduce",
                "explain",
                "justify",
            )
        ):
            return ResponseMode.WORKED_SOLUTION.value
        return ResponseMode.ANSWER_ONLY.value

    @staticmethod
    def _problem_type(lowered: str, options: list[str]) -> str:
        if options:
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
    def _options(normalized: str) -> list[str]:
        matches = list(_OPTION_PATTERN.finditer(normalized))
        labels = [
            next(
                group.upper()
                for group in (
                    match.group("ascii_paren"),
                    match.group("cjk_paren"),
                    match.group("punctuated"),
                )
                if group
            )
            for match in matches
        ]
        expected = [chr(ord("A") + index) for index in range(len(labels))]
        if len(labels) < 2 or labels != expected:
            return []
        return [match.group("content").strip() for match in matches]

    @staticmethod
    def _assumptions(normalized: str) -> list[str]:
        parts = re.split(r"[。.;；]|\b(?:where|given that|such that)\b", normalized)
        markers = (r"\in", ">", "<", "正", "非负", "integer", "real")
        return [part.strip() for part in parts if any(marker in part for marker in markers)][:8]

    @staticmethod
    def _constraints(normalized: str) -> list[str]:
        parts = re.split(
            r"[。.;；，,]|\b(?:where|given that|such that|subject to|with)\b",
            normalized,
            flags=re.IGNORECASE,
        )
        markers = (
            r"\in",
            "=",
            ">",
            "<",
            "positive",
            "negative",
            "integer",
            "real",
            "continuous",
            "differentiable",
            "满足",
            "正",
            "非负",
        )
        return list(
            dict.fromkeys(
                part.strip()
                for part in parts
                if part.strip()
                and any(marker in part.lower() for marker in markers)
            )
        )[:12]

    @staticmethod
    def _definitions(normalized: str) -> list[str]:
        parts = [
            part.strip()
            for part in re.split(r"[。.;；]", normalized)
            if part.strip()
        ]
        markers = (
            "let ",
            "define",
            "defined by",
            "denote",
            "where ",
            "设",
            "定义",
            "记",
            "其中",
        )
        return [
            part
            for part in parts
            if any(marker in part.lower() for marker in markers)
        ][:8]

    @staticmethod
    def _quantifiers(normalized: str) -> list[str]:
        return list(
            dict.fromkeys(
                match.group(0).casefold()
                for match in _QUANTIFIER_PATTERN.finditer(normalized)
            )
        )[:8]

    @staticmethod
    def _target_kind(
        problem_type: str,
        answer_type: str,
        target: str,
        full_problem: str,
    ) -> str:
        if problem_type == "multiple_choice":
            return "select_option"
        if problem_type == "proof":
            return "prove_statement"
        if problem_type == "derivation":
            return "derive_statement"
        if problem_type == "explanation":
            return "explain_reason"
        target_markers = (
            "det(",
            "tr(",
            "eigenvalue",
            "eigenvector",
            "every requested target",
        )
        if sum(marker in full_problem for marker in target_markers) >= 2:
            return "multiple_targets"
        if answer_type in {
            "vector",
            "tuple",
            "set",
            "matrix",
            "polynomial",
            "algebraic_structure",
        }:
            return "construct_object"
        return "compute_value"

    @staticmethod
    def _ambiguities(
        normalized: str,
        *,
        options: list[str],
        target_phrase: str,
        answer_type_confidence: float,
        target_kind: str,
    ) -> list[str]:
        ambiguities: list[str] = []
        if _CHOICE_INTENT.search(normalized) and not options:
            ambiguities.append("choice_intent_without_reliable_options")
        if not target_phrase:
            ambiguities.append("missing_target")
        if answer_type_confidence < 0.85:
            ambiguities.append("low_answer_type_confidence")
        if target_kind == "multiple_targets":
            ambiguities.append("multiple_requested_targets")
        if not braces_balanced(normalized):
            ambiguities.append("unbalanced_latex")
        return ambiguities

    @staticmethod
    def _difficulty_features(
        normalized: str,
        *,
        problem_type: str,
        constraints: list[str],
        quantifiers: list[str],
        target_kind: str,
    ) -> list[str]:
        lowered = normalized.lower()
        features: list[str] = []

        def add(condition: bool, name: str) -> None:
            if condition:
                features.append(name)

        add(
            (
                lowered.count("sum") >= 2
                or ("series" in lowered and ("h_n" in lowered or "harmonic" in lowered))
            ),
            "nested_aggregation",
        )
        add(
            "limit" in lowered
            and (
                len(re.findall(r"1/\(?\d*n\^?\d*", lowered)) >= 2
                or bool(re.search(r"\bn\^\d+\s*\(", lowered))
            ),
            "asymptotic_cancellation",
        )
        add(
            any(
                marker in lowered
                for marker in (
                    "characteristic polynomial",
                    "minimal polynomial",
                    "jordan",
                )
            ),
            "spectral_inference",
        )
        add(
            "until" in lowered
            and any(marker in lowered for marker in ("first", "either", "stopping")),
            "state_dependent_probability",
        )
        add(lowered.count(" mod ") >= 2, "coupled_congruences")
        add(
            any(marker in lowered for marker in ("surjection", "onto a")),
            "surjective_counting",
        )
        add(
            "sqrt" in lowered
            and any(marker in lowered for marker in ("all real", "satisfying", "solve")),
            "radical_domain_constraints",
        )
        add(
            any(marker in lowered for marker in ("minimum", "maximum", "minimize", "maximize"))
            and (
                bool(re.search(r"\bxyz\b", lowered))
                or len(re.findall(r"\b[a-z]\b", lowered)) >= 3
            ),
            "multivariable_global_constraint",
        )
        add(
            bool(re.search(r"[a-z]''|d\^2[a-z]/d", lowered))
            or "second-order" in lowered,
            "higher_order_differential_system",
        )
        add(
            any(marker in lowered for marker in ("integral", r"\int"))
            and any(marker in lowered for marker in ("ln(", "log(", "zeta", "improper")),
            "singular_or_special_integral",
        )
        add(
            bool(
                re.search(
                    r"(?:find|determine)\s+all\s+(?:real\s+)?[a-z]\s+for\s+which",
                    lowered,
                )
            ),
            "parameter_regime",
        )
        add(target_kind == "multiple_targets", "multiple_targets")
        add(len(constraints) >= 3, "long_condition_chain")
        add(len(quantifiers) >= 2, "nested_quantifiers")
        add(
            any(
                marker in lowered
                for marker in (
                    "if and only if",
                    "necessary and sufficient",
                    "converse",
                )
            ),
            "bidirectional_proof",
        )
        add(
            problem_type in {"proof", "derivation"}
            and any(
                marker in lowered
                for marker in ("lemma", "induction", "case", "contradiction")
            ),
            "multi_stage_proof",
        )
        add(
            "proposed solutions" in lowered
            and any(marker in lowered for marker in ("conflict", "give final answers")),
            "candidate_conflict",
        )
        return list(dict.fromkeys(features))

    @staticmethod
    def _subproblem_hints(
        difficulty_features: list[str],
        target_kind: str,
    ) -> list[str]:
        hints: list[str] = []
        feature_set = set(difficulty_features)
        if "bidirectional_proof" in feature_set:
            hints.extend(["prove_forward_direction", "prove_reverse_direction"])
        if feature_set.intersection(
            {
                "radical_domain_constraints",
                "parameter_regime",
                "long_condition_chain",
            }
        ):
            hints.append("establish_domain_and_constraints")
        if feature_set.intersection(
            {
                "state_dependent_probability",
                "surjective_counting",
                "candidate_conflict",
            }
        ):
            hints.append("build_independent_case_or_state_check")
        if feature_set.intersection(
            {
                "asymptotic_cancellation",
                "singular_or_special_integral",
                "higher_order_differential_system",
            }
        ):
            hints.append("verify_boundary_and_convergence_conditions")
        if target_kind == "multiple_targets":
            hints.append("resolve_each_requested_target")
        return list(dict.fromkeys(hints))

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
