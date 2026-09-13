from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Iterable, Mapping

from mathforge.harness.reasoning_state import ReasoningState
from mathforge.harness.schemas import ProblemIR
from mathforge.skills.execution_plan import (
    SkillExecutionPlan,
    skill_utility,
)
from mathforge.skills.mechmath_format import (
    COMMON_METHOD_CARD_SECTIONS,
    render_method_card,
)
from mathforge.skills.projection import project
from mathforge.skills.registry import SkillRegistry


_TOKEN = re.compile(r"[A-Za-z0-9_+-]+|[\u4e00-\u9fff]+")


@dataclass(frozen=True)
class SkillFragmentDecision:
    name: str
    version: str
    rank: int
    score: int
    included_sections: tuple[str, ...]
    omitted_sections: tuple[str, ...]
    reasons: tuple[str, ...]
    admission_status: str = "admitted"
    required_capabilities: tuple[str, ...] = ()
    verification_hooks: tuple[str, ...] = ()
    reference_hashes: tuple[str, ...] = ()
    expected_gain: float = 0.0
    token_cost: int = 0
    capability_available: bool = True
    historical_precision: float = 1.0
    expected_accuracy_gain: float = 0.0
    utility: float = 0.0
    source_skill_name: str = ""
    # V3 optional retrieval metadata is carried into the public selection
    # trace so an admission decision can be audited without reopening the
    # package source.  These fields are empty for legacy V2 Skills.
    description: str = ""
    negative_triggers: tuple[str, ...] = ()
    required_observables: tuple[str, ...] = ()
    format_version: str = "mmat-method-card-v1"

    def to_trace_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "rank": self.rank,
            "score": self.score,
            "included_sections": list(self.included_sections),
            "omitted_sections": list(self.omitted_sections),
            "reasons": list(self.reasons),
            "admission_status": self.admission_status,
            "required_capabilities": list(self.required_capabilities),
            "verification_hooks": list(self.verification_hooks),
            "reference_hashes": list(self.reference_hashes),
            "expected_gain": self.expected_gain,
            "token_cost": self.token_cost,
            "capability_available": self.capability_available,
            "historical_precision": self.historical_precision,
            "expected_accuracy_gain": self.expected_accuracy_gain,
            "utility": self.utility,
            "source_skill_name": self.source_skill_name,
            "description": self.description,
            "negative_triggers": list(self.negative_triggers),
            "required_observables": list(self.required_observables),
            "format_version": self.format_version,
        }


@dataclass(frozen=True)
class DynamicSkillComposition:
    role: str
    text: str
    included: tuple[SkillFragmentDecision, ...]
    omitted: tuple[SkillFragmentDecision, ...]
    selection_context: str

    def to_trace_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "selection_context": self.selection_context,
            "included": [item.to_trace_dict() for item in self.included],
            "omitted": [item.to_trace_dict() for item in self.omitted],
        }


class DynamicSkillSelector:
    """The single selector for V3 packages and legacy V2 compatibility.

    V3 packages receive pattern ranking, capability admission and bounded
    disclosure. The legacy adapter intentionally keeps its old projection
    semantics, but no longer owns a second ranking implementation.
    """

    def __init__(
        self,
        registry: SkillRegistry,
        *,
        top_k: int | None = 3,
        runtime: Any | None = None,
    ) -> None:
        if top_k is not None and top_k < 1:
            raise ValueError("Skill top_k must be positive")
        self._registry = registry
        self._top_k = top_k
        self._runtime = runtime

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
        reference_fragments: Mapping[str, Iterable[Any]] | None = None,
    ) -> DynamicSkillComposition:
        if max_chars < 0:
            raise ValueError("skill composition budget must be nonnegative")
        route_names = set(route_skill_names)
        failures = tuple(
            dict.fromkeys(
                str(item).strip().casefold() for item in failure_codes if item
            )
        )
        context = self._context(problem, state, failures)
        ranked: list[tuple[float, int, str, tuple[str, ...], float, int, float]] = []
        for name in self._registry.names():
            definition = self._registry.definition(name)
            if role not in getattr(definition, "roles", ()):
                continue
            score, reasons = self._score(
                definition,
                problem,
                context,
                route_names,
                failures,
                state,
            )
            expected_gain = _expected_gain(definition, score)
            historical_precision = _historical_precision(definition)
            token_cost = _token_cost(definition)
            utility = skill_utility(
                expected_gain,
                token_cost,
                capability_available=True,
                historical_precision=historical_precision,
            )
            ranked.append(
                (
                    utility,
                    score,
                    name,
                    reasons,
                    expected_gain,
                    token_cost,
                    historical_precision,
                )
            )
        # Router-selected Skills are the dispatch contract, not merely a soft
        # relevance hint.  Keep them ahead of generic utility-ranked cards so
        # a long MechMath method card cannot evict the route owner from the
        # bounded prompt.  Utility still orders cards within each group.
        ranked.sort(
            key=lambda item: (
                0 if item[2] in route_names else 1,
                -item[0],
                -item[1],
                item[2],
            )
        )

        references = reference_fragments or {}
        blocks: list[str] = []
        included: list[SkillFragmentDecision] = []
        omitted: list[SkillFragmentDecision] = []
        used = 0
        v3_included = 0
        seen_effective: set[str] = set()
        for rank, (
            utility,
            score,
            name,
            reasons,
            expected_gain,
            token_cost,
            historical_precision,
        ) in enumerate(ranked, start=1):
            definition = self._registry.definition(name)
            plan = self._execution_plan(
                definition,
                role=role,
                score=score,
                reasons=reasons,
                expected_gain=expected_gain,
                historical_precision=historical_precision,
                token_cost=token_cost,
            )
            effective_definition = definition
            if plan.admission_status == "alternative":
                effective_definition = self._registry.definition(plan.skill_name)
            selected, unselected = self._project_sections(effective_definition, role)
            effective_name = str(getattr(effective_definition, "name", name))
            effective_gain = float(plan.expected_gain)
            effective_precision = float(plan.historical_precision)
            effective_cost = int(plan.token_cost)
            effective_utility = float(plan.utility)
            skill_refs = tuple(
                references.get(effective_name, references.get(name, ()))
            )
            reference_hashes = tuple(
                str(getattr(item, "sha256", ""))
                for item in skill_refs
                if str(getattr(item, "sha256", ""))
            )
            decision = SkillFragmentDecision(
                name=effective_name,
                version=str(getattr(effective_definition, "version", "")),
                rank=rank,
                score=score,
                included_sections=selected,
                omitted_sections=unselected,
                reasons=(*reasons, *plan.admission_reasons),
                admission_status=plan.admission_status,
                required_capabilities=plan.required_capabilities,
                verification_hooks=plan.verification_hooks,
                reference_hashes=reference_hashes,
                expected_gain=effective_gain,
                token_cost=effective_cost,
                capability_available=plan.capability_available,
                historical_precision=effective_precision,
                expected_accuracy_gain=plan.expected_accuracy_gain,
                utility=effective_utility,
                source_skill_name=(
                    plan.source_skill_name
                    if plan.source_skill_name != effective_name
                    else ""
                ),
                description=str(getattr(effective_definition, "description", "")),
                negative_triggers=tuple(
                    str(item)
                    for item in getattr(effective_definition, "negative_triggers", ())
                ),
                required_observables=tuple(
                    str(item)
                    for item in getattr(effective_definition, "required_observables", ())
                ),
                format_version=str(
                    getattr(effective_definition, "format_version", "mmat-method-card-v1")
                ),
            )
            if score <= 0 or not selected:
                omitted.append(decision)
                continue
            if plan.admission_status not in {"admitted", "alternative"}:
                omitted.append(decision)
                continue
            if effective_name in seen_effective:
                omitted.append(
                    replace(decision, reasons=(*decision.reasons, "duplicate_effective_skill"))
                )
                continue
            if (
                self._is_v3(effective_definition)
                and self._top_k is not None
                and v3_included >= self._top_k
            ):
                omitted.append(replace(decision, reasons=(*decision.reasons, "top_k")))
                continue
            block = self._render(effective_definition, selected, skill_refs, role)
            separator = 2 if blocks else 0
            if used + separator + len(block) > max_chars:
                omitted.append(
                    replace(decision, reasons=(*decision.reasons, "character_budget"))
                )
                continue
            blocks.append(block)
            included.append(decision)
            seen_effective.add(effective_name)
            if self._is_v3(effective_definition):
                v3_included += 1
            used += separator + len(block)
        return DynamicSkillComposition(
            role=role,
            text="\n\n".join(blocks),
            included=tuple(included),
            omitted=tuple(omitted),
            selection_context=selection_context,
        )

    def _admission(
        self,
        definition: Any,
    ) -> tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        required = tuple(str(item) for item in getattr(definition, "requires", ()))
        hooks = tuple(
            str(item) for item in getattr(definition, "verification_hooks", ())
        )
        if self._runtime is None:
            return "admitted", required, hooks, ()
        check_plan = getattr(self._runtime, "check_plan", None)
        if callable(check_plan):
            plan = check_plan(definition.name)
            if not plan.admitted:
                unavailable = tuple(
                    dict.fromkeys(
                        (
                            *plan.unavailable_capabilities,
                            *plan.unavailable_hooks,
                            *plan.audit_errors,
                        )
                    )
                )
                return (
                    "rejected",
                    required,
                    hooks,
                    ("capability_admission:" + ",".join(unavailable),),
                )
            return "admitted", required, hooks, ()
        capabilities = self._runtime.capabilities(definition.name)
        if capabilities.unavailable:
            return (
                "rejected",
                required,
                hooks,
                (
                    "capability_admission:" + ",".join(capabilities.unavailable),
                ),
            )
        return "admitted", required, hooks, ()

    def _execution_plan(
        self,
        definition: Any,
        *,
        role: str,
        score: int,
        reasons: tuple[str, ...],
        expected_gain: float,
        historical_precision: float,
        token_cost: int,
    ) -> SkillExecutionPlan:
        # Metadata penalties may make a candidate score negative.  The
        # public execution-plan contract uses a nonnegative admission score;
        # retain the raw score in SkillFragmentDecision but clamp only this
        # downstream accounting field.
        plan_score = max(0, int(score))
        if self._runtime is not None:
            builder = getattr(self._runtime, "execution_plan", None)
            if callable(builder):
                return builder(
                    definition.name,
                    role=role,
                    selection_score=plan_score,
                    selection_reasons=reasons,
                    expected_gain=expected_gain,
                    historical_precision=historical_precision,
                    token_cost=token_cost,
                    allow_degraded=False,
                )
        return SkillExecutionPlan.from_definition(
            definition,
            role=role,
            selection_score=plan_score,
            selection_reasons=reasons,
            expected_gain=expected_gain,
            historical_precision=historical_precision,
            token_cost=token_cost,
        )

    @staticmethod
    def _is_v3(definition: Any) -> bool:
        return str(getattr(definition, "version", "")) == "3.0"

    @staticmethod
    def _project_sections(
        definition: Any,
        role: str,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        if DynamicSkillSelector._is_v3(definition):
            _, selected, omitted = project(definition, role)
            return selected, omitted
        sections = _section_map(str(getattr(definition, "body", "")))
        selected_names = {
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
            "LLMFinalizer": ("answer normalization", "trace step guidance"),
        }.get(role, ())
        selected = tuple(name for name in selected_names if name in sections)
        omitted = tuple(
            name
            for name in sections
            if name not in selected and name not in COMMON_METHOD_CARD_SECTIONS
        )
        return selected, omitted

    @staticmethod
    def _render(
        definition: Any,
        selected: tuple[str, ...],
        references: tuple[Any, ...],
        role: str = "Host",
    ) -> str:
        block = render_method_card(definition, role, selected)
        if references:
            blocks = [block]
            for fragment in references:
                blocks.append(
                    f"## Reference: {fragment.relative_path}\n{fragment.text}"
                )
            return "\n\n".join(blocks).strip()
        return block

    @staticmethod
    def _context(
        problem: ProblemIR,
        state: ReasoningState | None,
        failures: tuple[str, ...],
    ) -> str:
        values: list[object] = [
            problem.normalized_problem,
            problem.problem_type,
            problem.target_kind,
            problem.target_phrase,
            *(_subject_name(item) for item in problem.subject_candidates),
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
        return " ".join(str(value) for value in values if value is not None).casefold()

    @classmethod
    def _score(
        cls,
        definition: Any,
        problem: ProblemIR,
        context: str,
        route_names: set[str],
        failures: tuple[str, ...],
        state: ReasoningState | None,
    ) -> tuple[int, tuple[str, ...]]:
        name = str(getattr(definition, "name", ""))
        subject = str(
            getattr(definition, "domain", getattr(definition, "subject", ""))
        )
        patterns = tuple(
            getattr(definition, "problem_patterns", ())
            or getattr(definition, "triggers", ())
        )
        triggers = tuple(getattr(definition, "triggers", ()))
        score = 0
        reasons: list[str] = []
        if name in route_names:
            score += 40
            reasons.append("route_seed")
        if subject.casefold() in {
            _subject_name(item).casefold() for item in problem.subject_candidates
        }:
            score += 24
            reasons.append("problem_subject")
        pattern_hits = [pattern for pattern in patterns if _matches(pattern, context)]
        if pattern_hits:
            score += min(36, 12 * len(pattern_hits))
            reasons.append(f"pattern:{pattern_hits[0]}")
        trigger_hits = [trigger for trigger in triggers if _matches(trigger, context)]
        if trigger_hits:
            score += min(24, 8 * len(trigger_hits))
            reasons.append(f"trigger:{trigger_hits[0]}")
        failure_text = " ".join(failures)
        failure_signals = tuple(getattr(definition, "failure_signals", ()))
        if failure_signals and any(_matches(signal, failure_text) for signal in failure_signals):
            score += 28
            reasons.append("failure_feedback")

        # Optional V3 metadata refines ranking but never substitutes for the
        # Skill's exact preconditions.  Negative triggers are deliberately a
        # bounded penalty (not a first-version hard veto), while required
        # observables reward evidence already present in the problem/state and
        # penalize missing observables so near-miss Skills rank lower.
        description = str(getattr(definition, "description", "")).strip()
        if description and _matches(description, context):
            score += 4
            reasons.append("description_match")
        negative_triggers = tuple(
            str(item)
            for item in getattr(definition, "negative_triggers", ())
            if str(item).strip()
        )
        negative_hits = [item for item in negative_triggers if _matches(item, context)]
        if negative_hits:
            score -= min(32, 16 * len(negative_hits))
            reasons.append(f"negative_trigger:{negative_hits[0]}")
        required_observables = tuple(
            str(item)
            for item in getattr(definition, "required_observables", ())
            if str(item).strip()
        )
        if required_observables:
            observable_hits = [
                item for item in required_observables if _matches(item, context)
            ]
            missing_observables = [
                item for item in required_observables if item not in observable_hits
            ]
            if observable_hits:
                score += min(18, 6 * len(observable_hits))
                reasons.append(f"required_observable:{observable_hits[0]}")
            if missing_observables:
                score -= min(24, 8 * len(missing_observables))
                reasons.append(
                    f"missing_required_observable:{missing_observables[0]}"
                )
        if name == "counterexample-search" and any(
            marker in context
            for marker in ("contradiction", "if and only if", "unique", "forall")
        ):
            score += 35
            reasons.append("adversarial_proof_context")
        if name == "numerical-stability" and "numerical" in context:
            score += 35
            reasons.append("numerical_context")
        if name == "proof-obligation" and (
            problem.problem_type in {"proof", "derivation"}
            or (state is not None and state.open_obligations)
        ):
            score += 30
            reasons.append("open_proof_obligation")
        if name == "lemma-compression" and state is not None and (
            state.version > 1 or state.open_obligations
        ):
            score += 20
            reasons.append("multi_round_state")
        if score == 0:
            reasons.append("no_dynamic_trigger")
        return score, tuple(reasons)


def _subject_name(value: Any) -> str:
    if isinstance(value, (tuple, list)) and value:
        return str(value[0])
    if isinstance(value, dict):
        return str(value.get("subject") or value.get("name") or "")
    return str(value)


def _section_map(body: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = ""
    for line in body.splitlines():
        if line.startswith("## "):
            current = line[3:].strip().casefold()
            sections.setdefault(current, [])
        elif current:
            sections[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def _matches(needle: str, context: str) -> bool:
    normalized = str(needle).strip().casefold()
    if not normalized:
        return False
    if normalized in context:
        return True
    needle_tokens = set(_TOKEN.findall(normalized))
    context_tokens = set(_TOKEN.findall(context))
    return bool(needle_tokens) and needle_tokens.issubset(context_tokens)


def _expected_gain(definition: Any, score: int) -> float:
    """Return an offline-only prior for utility ordering.

    Packages may publish a benchmark prior in frontmatter.  Until that is
    present, the existing rule score is retained as a small deterministic
    feature rather than pretending that an online estimate exists.
    """

    explicit = getattr(definition, "expected_gain", None)
    try:
        explicit_value = float(explicit) if explicit is not None else 0.0
    except (TypeError, ValueError):
        explicit_value = 0.0
    if explicit_value > 0.0:
        return explicit_value
    return max(0.01, min(1.0, (max(0, int(score)) + 1) / 100.0))


def _historical_precision(definition: Any) -> float:
    value = getattr(definition, "historical_precision", 1.0)
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _token_cost(definition: Any) -> int:
    value = getattr(definition, "token_cost", 0)
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 0
    if value > 0:
        return value
    return max(1, int(round(len(str(getattr(definition, "body", ""))) / 4.0)))
