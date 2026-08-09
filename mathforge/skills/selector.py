from __future__ import annotations

import re
from typing import Iterable

from mathforge.agents.skill_selector import (
    DynamicSkillComposition,
    SkillFragmentDecision,
)
from mathforge.harness.reasoning_state import ReasoningState
from mathforge.harness.schemas import ProblemIR
from mathforge.skills.projection import project
from mathforge.skills.registry import SkillRegistry
from mathforge.skills.schema import SkillPackage


_TOKEN = re.compile(r"[A-Za-z0-9_+-]+|[\u4e00-\u9fff]+")


class DynamicSkillSelector:
    """Pattern-aware, role-projected selector with explicit Top-K disclosure."""

    def __init__(self, registry: SkillRegistry, *, top_k: int = 3) -> None:
        if top_k < 1:
            raise ValueError("Skill top_k must be positive")
        self._registry = registry
        self._top_k = top_k

    def compose_for_role(
        self,
        problem: ProblemIR,
        *,
        role: str,
        route_skill_names: Iterable[str],
        max_chars: int,
        state: ReasoningState | None = None,
        failure_codes: Iterable[str] = (),
        selection_context: str = "initial",
    ) -> DynamicSkillComposition:
        if max_chars < 0:
            raise ValueError("skill composition budget must be nonnegative")
        route_names = set(route_skill_names)
        failures = tuple(dict.fromkeys(str(item).strip().casefold() for item in failure_codes if item))
        context = self._context(problem, state, failures)
        ranked: list[tuple[int, str, tuple[str, ...]]] = []
        for name in self._registry.names():
            skill = self._registry.definition(name)
            if role not in skill.roles:
                continue
            score, reasons = self._score(skill, problem, context, route_names, failures, state)
            ranked.append((score, name, reasons))
        ranked.sort(key=lambda item: (-item[0], item[1]))

        blocks: list[str] = []
        included: list[SkillFragmentDecision] = []
        omitted: list[SkillFragmentDecision] = []
        used = 0
        v3_included = 0
        for rank, (score, name, reasons) in enumerate(ranked, start=1):
            skill = self._registry.definition(name)
            block, selected, unselected = project(skill, role) if not skill.legacy else self._legacy_projection(skill, role)
            decision = SkillFragmentDecision(name, skill.version, rank, score, selected, unselected, reasons)
            if score <= 0 or not selected:
                omitted.append(decision)
                continue
            if not skill.legacy and v3_included >= self._top_k:
                omitted.append(self._with_reason(decision, "top_k"))
                continue
            extra = len(block) + (2 if blocks else 0)
            if used + extra > max_chars:
                omitted.append(self._with_reason(decision, "character_budget"))
                continue
            blocks.append(block)
            included.append(decision)
            if not skill.legacy:
                v3_included += 1
            used += extra
        return DynamicSkillComposition(role, "\n\n".join(blocks), tuple(included), tuple(omitted), selection_context)

    @staticmethod
    def _with_reason(decision: SkillFragmentDecision, reason: str) -> SkillFragmentDecision:
        return SkillFragmentDecision(
            decision.name,
            decision.version,
            decision.rank,
            decision.score,
            decision.included_sections,
            decision.omitted_sections,
            (*decision.reasons, reason),
        )

    @staticmethod
    def _legacy_projection(skill: SkillPackage, role: str) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
        role_sections = {
            "PrimarySolver": ("method decision tree", "theorem preconditions", "common errors", "compatible check types", "answer normalization"),
            "AlternativeSolver": ("method decision tree", "theorem preconditions", "common errors", "counterexample checklist", "compatible check types"),
            "LemmaCurator": ("method decision tree", "theorem preconditions", "compatible check types", "trace step guidance"),
            "VerifierSkeptic": ("theorem preconditions", "common errors", "counterexample checklist", "compatible check types"),
            "RepairAgent": ("method decision tree", "theorem preconditions", "common errors", "compatible check types"),
            "LLMFinalizer": ("answer normalization", "trace step guidance"),
        }
        selected = tuple(name for name in role_sections.get(role, ()) if skill.sections.get(name))
        omitted = tuple(name for name in skill.sections if name not in selected)
        blocks = [f"# Skill: {skill.name} ({skill.version})"]
        for name in selected:
            blocks.append(f"## {name.title()}\n{skill.sections[name]}")
        return "\n".join(blocks), selected, omitted

    @staticmethod
    def _subject_names(problem: ProblemIR) -> set[str]:
        names: set[str] = set()
        for item in problem.subject_candidates:
            if isinstance(item, (tuple, list)) and item:
                names.add(str(item[0]).casefold())
            elif isinstance(item, dict):
                value = item.get("subject") or item.get("name")
                if value:
                    names.add(str(value).casefold())
            else:
                names.add(str(item).casefold())
        return names

    @classmethod
    def _context(cls, problem: ProblemIR, state: ReasoningState | None, failures: tuple[str, ...]) -> str:
        values: list[object] = [
            problem.normalized_problem,
            problem.problem_type,
            problem.target_kind,
            problem.target_phrase,
            *cls._subject_names(problem),
            *problem.assumptions,
            *problem.constraints,
            *failures,
        ]
        if state is not None:
            values.extend(item.statement for item in state.subgoal_ledger.items if item.status in {"open", "active", "blocked"})
            values.extend(item.statement for item in state.open_obligations)
            values.extend(item.summary for item in state.tool_results)
            values.append(state.strategy)
        return " ".join(str(value) for value in values if value is not None).casefold()

    @classmethod
    def _score(
        cls,
        skill: SkillPackage,
        problem: ProblemIR,
        context: str,
        route_names: set[str],
        failures: tuple[str, ...],
        state: ReasoningState | None,
    ) -> tuple[int, tuple[str, ...]]:
        score = 0
        reasons: list[str] = []
        if skill.name in route_names:
            score += 40
            reasons.append("route_seed")
        if skill.domain.casefold() in cls._subject_names(problem):
            score += 24
            reasons.append("problem_subject")
        pattern_hits = [pattern for pattern in skill.problem_patterns if _matches(pattern, context)]
        if pattern_hits:
            score += min(36, 12 * len(pattern_hits))
            reasons.append(f"pattern:{pattern_hits[0]}")
        trigger_hits = [trigger for trigger in skill.triggers if _matches(trigger, context)]
        if trigger_hits:
            score += min(24, 8 * len(trigger_hits))
            reasons.append(f"trigger:{trigger_hits[0]}")
        if skill.failure_signals and any(_matches(signal, " ".join(failures)) for signal in skill.failure_signals):
            score += 28
            reasons.append("failure_feedback")
        if skill.name == "numerical-stability" and "numerical" in context:
            score += 35
            reasons.append("numerical_context")
        if skill.name == "counterexample-search" and any(
            marker in context
            for marker in ("contradiction", "if and only if", "unique", "forall")
        ):
            score += 35
            reasons.append("adversarial_proof_context")
        if skill.kind == "method" and problem.target_kind and _matches(problem.target_kind, " ".join(skill.problem_patterns)):
            score += 8
            reasons.append("target_kind")
        if skill.name == "proof-obligation" and (problem.problem_type in {"proof", "derivation"} or (state is not None and state.open_obligations)):
            score += 30
            reasons.append("open_proof_obligation")
        if skill.name == "lemma-compression" and state is not None and (state.version > 1 or state.open_obligations):
            score += 20
            reasons.append("multi_round_state")
        if score == 0:
            reasons.append("no_dynamic_trigger")
        return score, tuple(reasons)


def _matches(needle: str, context: str) -> bool:
    normalized = str(needle).strip().casefold()
    if not normalized:
        return False
    if normalized in context:
        return True
    needle_tokens = set(_TOKEN.findall(normalized))
    context_tokens = set(_TOKEN.findall(context))
    return bool(needle_tokens) and needle_tokens.issubset(context_tokens)
