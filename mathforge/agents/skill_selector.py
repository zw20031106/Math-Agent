from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from mathforge.agents.registry import SkillDefinition, SkillRegistry
from mathforge.harness.reasoning_state import ReasoningState
from mathforge.harness.schemas import ProblemIR


_TOKEN = re.compile(r"[A-Za-z0-9_+-]+|[\u4e00-\u9fff]+")
_ROLE_SECTIONS = {
    "PrimarySolver": (
        "method decision tree",
        "theorem preconditions",
        "common errors",
        "compatible check types",
        "answer normalization",
    ),
    "AlternativeSolver": (
        "method decision tree",
        "theorem preconditions",
        "common errors",
        "counterexample checklist",
        "compatible check types",
    ),
    "LemmaCurator": (
        "method decision tree",
        "theorem preconditions",
        "compatible check types",
        "trace step guidance",
    ),
    "VerifierSkeptic": (
        "theorem preconditions",
        "common errors",
        "counterexample checklist",
        "compatible check types",
    ),
    "RepairAgent": (
        "method decision tree",
        "theorem preconditions",
        "common errors",
        "compatible check types",
    ),
    "LLMFinalizer": (
        "answer normalization",
        "trace step guidance",
    ),
}


@dataclass(frozen=True)
class SkillFragmentDecision:
    name: str
    version: str
    rank: int
    score: int
    included_sections: tuple[str, ...]
    omitted_sections: tuple[str, ...]
    reasons: tuple[str, ...]

    def to_trace_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "rank": self.rank,
            "score": self.score,
            "included_sections": list(self.included_sections),
            "omitted_sections": list(self.omitted_sections),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class DynamicSkillComposition:
    role: str
    text: str
    included: tuple[SkillFragmentDecision, ...]
    omitted: tuple[SkillFragmentDecision, ...]
    selection_context: str

    def to_trace_dict(self) -> dict:
        return {
            "role": self.role,
            "selection_context": self.selection_context,
            "included": [item.to_trace_dict() for item in self.included],
            "omitted": [item.to_trace_dict() for item in self.omitted],
        }


class DynamicSkillSelector:
    """Select role-specific Skill fragments from public solve-local state."""

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

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
        failures = tuple(
            dict.fromkeys(str(item).strip().casefold() for item in failure_codes if item)
        )
        context = self._context(problem, state, failures)
        ranked: list[tuple[int, str, tuple[str, ...]]] = []
        for name in self._registry.names():
            definition = self._registry.definition(name)
            if role not in definition.roles:
                continue
            score, reasons = self._score(
                definition,
                problem,
                context,
                route_names,
                failures,
                state,
            )
            ranked.append((score, name, reasons))
        ranked.sort(key=lambda item: (-item[0], item[1]))

        blocks: list[str] = []
        included: list[SkillFragmentDecision] = []
        omitted: list[SkillFragmentDecision] = []
        used = 0
        for rank, (score, name, reasons) in enumerate(ranked, start=1):
            definition = self._registry.definition(name)
            sections = _section_map(definition.body)
            selected_sections = tuple(
                section
                for section in _ROLE_SECTIONS.get(role, ())
                if section in sections
            )
            unselected_sections = tuple(
                section for section in sections if section not in selected_sections
            )
            decision = SkillFragmentDecision(
                name=name,
                version=definition.version,
                rank=rank,
                score=score,
                included_sections=selected_sections,
                omitted_sections=unselected_sections,
                reasons=reasons,
            )
            if score <= 0 or not selected_sections:
                omitted.append(decision)
                continue
            block = _render_fragments(name, sections, selected_sections)
            separator = 2 if blocks else 0
            if used + separator + len(block) > max_chars:
                omitted.append(
                    SkillFragmentDecision(
                        **{
                            **decision.__dict__,
                            "reasons": (*decision.reasons, "character_budget"),
                        }
                    )
                )
                continue
            blocks.append(block)
            included.append(decision)
            used += separator + len(block)
        return DynamicSkillComposition(
            role=role,
            text="\n\n".join(blocks),
            included=tuple(included),
            omitted=tuple(omitted),
            selection_context=selection_context,
        )

    @staticmethod
    def _context(
        problem: ProblemIR,
        state: ReasoningState | None,
        failures: tuple[str, ...],
    ) -> str:
        values = [
            problem.normalized_problem,
            problem.problem_type,
            problem.target_kind,
            problem.target_phrase,
            *problem.subject_candidates,
            *problem.assumptions,
            *problem.constraints,
            *failures,
        ]
        if state is not None:
            values.extend(
                item.statement
                for item in state.subgoal_ledger.items
                if item.status in {"open", "active", "blocked"}
            )
            values.extend(item.statement for item in state.open_obligations)
            values.extend(item.summary for item in state.tool_results)
            values.append(state.strategy)
        return " ".join(
            str(value) for value in values if value is not None
        ).casefold()

    @staticmethod
    def _score(
        definition: SkillDefinition,
        problem: ProblemIR,
        context: str,
        route_names: set[str],
        failures: tuple[str, ...],
        state: ReasoningState | None,
    ) -> tuple[int, tuple[str, ...]]:
        score = 0
        reasons: list[str] = []
        if definition.name in route_names:
            score += 40
            reasons.append("route_seed")
        subject_candidates = {
            str(item).casefold() for item in problem.subject_candidates
        }
        if definition.subject.casefold() in subject_candidates:
            score += 24
            reasons.append("problem_subject")
        trigger_hits = [
            trigger
            for trigger in definition.triggers
            if _trigger_matches(trigger, context)
        ]
        if trigger_hits:
            score += min(30, 10 * len(trigger_hits))
            reasons.append(f"trigger:{trigger_hits[0]}")
        failure_text = " ".join(failures)
        if definition.name == "counterexample-search" and any(
            marker in failure_text
            for marker in ("fail", "contradiction", "missing_condition", "rejected")
        ):
            score += 35
            reasons.append("failure_counterexample")
        if definition.name == "symbolic-equivalence" and any(
            marker in failure_text
            for marker in ("symbolic", "equivalence", "tool_fail")
        ):
            score += 35
            reasons.append("symbolic_tool_feedback")
        if definition.name == "numerical-stability" and "numerical" in failure_text:
            score += 35
            reasons.append("numerical_tool_feedback")
        if (
            definition.name == "proof-obligation"
            and (
                problem.problem_type in {"proof", "derivation"}
                or (state is not None and state.open_obligations)
            )
        ):
            score += 30
            reasons.append("open_proof_obligation")
        if definition.name == "lemma-compression" and state is not None and (
            state.version > 1 or state.open_obligations
        ):
            score += 20
            reasons.append("multi_round_state")
        if definition.kind == "general" and score == 0:
            reasons.append("no_dynamic_trigger")
        elif definition.kind == "domain" and score == 0:
            reasons.append("domain_not_active")
        return score, tuple(reasons)


def _section_map(body: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = ""
    for line in body.splitlines():
        if line.startswith("## "):
            current = line[3:].strip().casefold()
            sections.setdefault(current, [])
        elif current:
            sections[current].append(line)
    return {
        name: "\n".join(lines).strip()
        for name, lines in sections.items()
    }


def _render_fragments(
    name: str,
    sections: dict[str, str],
    selected: tuple[str, ...],
) -> str:
    blocks = [f"# Skill: {name}"]
    for section in selected:
        blocks.append(f"## {section.title()}\n{sections[section]}")
    return "\n".join(blocks).strip()


def _trigger_matches(trigger: str, context: str) -> bool:
    normalized = str(trigger).strip().casefold()
    if not normalized:
        return False
    if normalized in context:
        return True
    trigger_tokens = set(_TOKEN.findall(normalized))
    context_tokens = set(_TOKEN.findall(context))
    return bool(trigger_tokens) and trigger_tokens.issubset(context_tokens)
