from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from mathforge.skills.reference_loader import ReferenceFragment, ReferenceLoader
from mathforge.skills.registry import SkillRegistry
from mathforge.skills.execution_plan import (
    SkillCheckTask,
    SkillExecutionPlan,
    SkillOutcome,
)
from mathforge.tools.registry import ToolRegistry


@dataclass(frozen=True)
class SkillCapabilities:
    skill_name: str
    requested: tuple[str, ...]
    authorized: tuple[str, ...]
    unavailable: tuple[str, ...]


@dataclass(frozen=True)
class SkillCheckPlan:
    """Host-owned admission and verification plan for one Skill package."""

    skill_name: str
    required_capabilities: tuple[str, ...]
    admitted_capabilities: tuple[str, ...]
    unavailable_capabilities: tuple[str, ...]
    verification_hooks: tuple[str, ...]
    admitted_hooks: tuple[str, ...]
    unavailable_hooks: tuple[str, ...]
    selected_tools: tuple[str, ...]
    status: str

    @property
    def admitted(self) -> bool:
        return self.status == "admitted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "required_capabilities": list(self.required_capabilities),
            "admitted_capabilities": list(self.admitted_capabilities),
            "unavailable_capabilities": list(self.unavailable_capabilities),
            "verification_hooks": list(self.verification_hooks),
            "admitted_hooks": list(self.admitted_hooks),
            "unavailable_hooks": list(self.unavailable_hooks),
            "selected_tools": list(self.selected_tools),
            "status": self.status,
            "admitted": self.admitted,
        }


class SkillRuntime:
    """Capability and disclosure boundary for passive Skill packages."""

    def __init__(self, registry: SkillRegistry, tools: ToolRegistry) -> None:
        self._registry = registry
        self._tools = tools
        self._references = ReferenceLoader()

    def capabilities(self, skill_name: str) -> SkillCapabilities:
        requested = tuple(
            str(item)
            for item in getattr(self._registry.definition(skill_name), "requires", ())
        )
        known = set(self._tools.names())
        authorized = tuple(name for name in requested if name in known)
        unavailable = tuple(name for name in requested if name not in known)
        return SkillCapabilities(skill_name, requested, authorized, unavailable)

    def check_plan(self, skill_name: str) -> SkillCheckPlan:
        definition = self._registry.definition(skill_name)
        required = tuple(
            str(item) for item in getattr(definition, "requires", ())
        )
        hooks = tuple(
            str(item) for item in getattr(definition, "verification_hooks", ())
        )
        known = set(self._tools.names())
        admitted_capabilities = tuple(item for item in required if item in known)
        unavailable_capabilities = tuple(item for item in required if item not in known)
        admitted_hooks = tuple(item for item in hooks if item in known)
        unavailable_hooks = tuple(item for item in hooks if item not in known)
        selected_tools = tuple(
            dict.fromkeys((*admitted_capabilities, *admitted_hooks))
        )
        status = "admitted"
        if unavailable_capabilities:
            status = "capability_unavailable"
        elif unavailable_hooks:
            status = "verification_hook_unavailable"
        return SkillCheckPlan(
            skill_name=skill_name,
            required_capabilities=required,
            admitted_capabilities=admitted_capabilities,
            unavailable_capabilities=unavailable_capabilities,
            verification_hooks=hooks,
            admitted_hooks=admitted_hooks,
            unavailable_hooks=unavailable_hooks,
            selected_tools=selected_tools,
            status=status,
        )

    def check_plans(self, skill_names: Iterable[str]) -> dict[str, SkillCheckPlan]:
        plans: dict[str, SkillCheckPlan] = {}
        for name in dict.fromkeys(str(item) for item in skill_names):
            if name not in self._registry.names():
                continue
            plans[name] = self.check_plan(name)
        return plans

    def execution_plan(
        self,
        skill_name: str,
        *,
        role: str = "",
        selection_score: float = 0.0,
        selection_reasons: Iterable[str] = (),
        allow_degraded: bool = True,
        expected_gain: float | None = None,
        historical_precision: float | None = None,
        token_cost: int | None = None,
    ) -> SkillExecutionPlan:
        """Build the executable admission plan for a selected Skill.

        Alternatives are considered in declaration order.  A missing
        capability is never hidden: the returned status is ``alternative``,
        ``degraded``, or ``rejected`` and the reason remains in the public
        plan.  ``allow_degraded`` is false for prompt admission when a Skill
        would otherwise make an unverifiable claim.
        """

        definition = self._registry.definition(skill_name)
        check = self.check_plan(skill_name)
        role_name = str(role or (definition.roles[0] if getattr(definition, "roles", ()) else ""))
        unavailable = tuple(
            dict.fromkeys((*check.unavailable_capabilities, *check.unavailable_hooks))
        )
        reasons = tuple(
            f"capability_unavailable:{item}" for item in unavailable
        )
        if check.admitted:
            return SkillExecutionPlan.from_definition(
                definition,
                role=role_name,
                selection_score=selection_score,
                selection_reasons=selection_reasons,
                expected_gain=expected_gain,
                historical_precision=historical_precision,
                token_cost=(token_cost if token_cost is not None else getattr(definition, "token_cost", 0) or None),
                capability_available=True,
                admission_status="admitted",
            )

        for alternative in getattr(definition, "alternative_skills", ()):
            alternative_name = str(alternative).strip()
            if not alternative_name or alternative_name not in self._registry.names():
                continue
            alternative_check = self.check_plan(alternative_name)
            if not alternative_check.admitted:
                continue
            alternative_definition = self._registry.definition(alternative_name)
            return SkillExecutionPlan.from_definition(
                alternative_definition,
                role=role_name,
                selection_score=selection_score,
                selection_reasons=(
                    *tuple(str(item) for item in selection_reasons),
                    f"alternative_for:{skill_name}",
                ),
                expected_gain=expected_gain,
                historical_precision=historical_precision,
                token_cost=(token_cost if token_cost is not None else getattr(alternative_definition, "token_cost", 0) or None),
                capability_available=True,
                admission_status="alternative",
                admission_reasons=(
                    *reasons,
                    f"alternative_for:{skill_name}",
                ),
                source_skill_name=skill_name,
            )

        status = "degraded" if allow_degraded else "rejected"
        return SkillExecutionPlan.from_definition(
            definition,
            role=role_name,
            selection_score=selection_score,
            selection_reasons=selection_reasons,
            expected_gain=expected_gain,
            historical_precision=historical_precision,
            token_cost=(token_cost if token_cost is not None else getattr(definition, "token_cost", 0) or None),
            capability_available=False,
            admission_status=status,
            admission_reasons=reasons or ("capability_admission_failed",),
        )

    def execution_plans(
        self,
        skill_names: Iterable[str],
        *,
        role: str = "",
        allow_degraded: bool = True,
    ) -> dict[str, SkillExecutionPlan]:
        plans: dict[str, SkillExecutionPlan] = {}
        for name in dict.fromkeys(str(item) for item in skill_names):
            if name not in self._registry.names():
                continue
            plans[name] = self.execution_plan(
                name,
                role=role,
                allow_degraded=allow_degraded,
            )
        return plans

    # Descriptive aliases keep the admission boundary discoverable to
    # callers while preserving the E2 ``check_plan`` API.
    def build_execution_plan(self, skill_name: str, **kwargs: Any) -> SkillExecutionPlan:
        return self.execution_plan(skill_name, **kwargs)

    def admit(self, skill_name: str, **kwargs: Any) -> SkillExecutionPlan:
        return self.execution_plan(skill_name, **kwargs)

    def hook_tasks(
        self,
        skill_names: Iterable[str],
        *,
        dependencies: Iterable[str] = (),
        role: str = "VerifierSkeptic",
        allow_degraded: bool = False,
        node_prefix: str = "skill-check",
    ) -> tuple[SkillCheckTask, ...]:
        """Materialize one public check task for every admitted hook."""

        dependency_ids = tuple(dict.fromkeys(str(item) for item in dependencies if str(item)))
        tasks: list[SkillCheckTask] = []
        seen: set[tuple[str, str]] = set()
        for source_name, plan in self.execution_plans(
            skill_names,
            role=role,
            allow_degraded=allow_degraded,
        ).items():
            if not plan.admitted:
                continue
            effective_name = plan.skill_name
            for hook in plan.verification_hooks:
                identity = (effective_name, hook)
                if identity in seen:
                    continue
                seen.add(identity)
                digest = f"{effective_name}:{hook}".replace(" ", "-")
                node_id = f"{node_prefix}:{digest}"
                tasks.append(
                    SkillCheckTask(
                        task_id=node_id,
                        node_id=node_id,
                        skill_name=effective_name,
                        hook=hook,
                        tool_name=hook,
                        dependencies=dependency_ids,
                    )
                )
        return tuple(tasks)

    @staticmethod
    def consume_hook_evidence(
        tasks: Iterable[SkillCheckTask],
        evidence_records: Iterable[Any],
    ) -> tuple[SkillCheckTask, ...]:
        """Bind real EvidenceRecord IDs/statuses back to hook tasks.

        A hook with no corresponding evidence is explicitly marked skipped;
        no successful check is synthesized merely because a node exists.
        """

        records = tuple(evidence_records)
        updated: list[SkillCheckTask] = []
        for task in tasks:
            matching = tuple(
                record
                for record in records
                if _evidence_matches_hook(record, task.hook)
            )
            evidence_ids = tuple(
                str(getattr(record, "evidence_id", ""))
                for record in matching
                if str(getattr(record, "evidence_id", ""))
            )
            statuses = {str(getattr(record, "status", "unknown")) for record in matching}
            if not matching:
                status = "skipped"
            elif "fail" in statuses or "error" in statuses:
                status = "failed"
            elif "unknown" in statuses:
                status = "failed"
            else:
                status = "completed"
            updated.append(
                SkillCheckTask(
                    task_id=task.task_id,
                    node_id=task.node_id,
                    skill_name=task.skill_name,
                    hook=task.hook,
                    tool_name=task.tool_name,
                    dependencies=task.dependencies,
                    status=status,
                    evidence_ids=evidence_ids,
                )
            )
        return tuple(updated)

    def resolve_failure(
        self,
        skill_name: str,
        failure_codes: Iterable[str],
        *,
        evidence_ids: Iterable[str] = (),
        role: str = "",
    ) -> SkillOutcome:
        """Convert matching failure evidence into a fallback transition."""

        definition = self._registry.definition(skill_name)
        signals = tuple(
            str(item).strip().casefold()
            for item in getattr(definition, "failure_signals", ())
            if str(item).strip()
        )
        codes = tuple(
            str(item).strip().casefold()
            for item in failure_codes
            if str(item).strip()
        )
        signal = next(
            (
                candidate
                for candidate in signals
                if any(_signal_matches(candidate, code) for code in codes)
            ),
            "",
        )
        if not signal:
            return SkillOutcome(
                skill_name=skill_name,
                status="passed",
                reason="no_declared_failure_signal",
                evidence_ids=tuple(evidence_ids),
                source_skill_name=skill_name,
            )
        for alternative in getattr(definition, "alternative_skills", ()):
            name = str(alternative).strip()
            if not name or name not in self._registry.names():
                continue
            if self.check_plan(name).admitted:
                return SkillOutcome(
                    skill_name=name,
                    status="fallback",
                    signal=signal,
                    reason=f"failure_signal:{signal}",
                    alternative_skill=name,
                    replan_required=True,
                    evidence_ids=tuple(evidence_ids),
                    source_skill_name=skill_name,
                )
        return SkillOutcome(
            skill_name=skill_name,
            status="degraded",
            signal=signal,
            reason=f"failure_signal:{signal};no_admitted_alternative",
            replan_required=True,
            evidence_ids=tuple(evidence_ids),
            source_skill_name=skill_name,
        )

    def resolve_failures(
        self,
        skill_names: Iterable[str],
        failure_codes: Iterable[str],
        *,
        evidence_ids: Iterable[str] = (),
        role: str = "",
    ) -> tuple[SkillOutcome, ...]:
        codes = tuple(failure_codes)
        return tuple(
            self.resolve_failure(
                name,
                codes,
                evidence_ids=evidence_ids,
                role=role,
            )
            for name in dict.fromkeys(str(item) for item in skill_names)
            if name in self._registry.names()
        )

    def alternative_skill_names(self, skill_names: Iterable[str]) -> list[str]:
        """Return route Skills plus declared methods for an independent branch."""
        result: list[str] = []
        for name in dict.fromkeys(str(item) for item in skill_names):
            if name not in self._registry.names():
                continue
            result.append(name)
            definition = self._registry.definition(name)
            for alternative in getattr(definition, "alternative_skills", ()):
                alternative_name = str(alternative).strip()
                if alternative_name in self._registry.names() and alternative_name not in result:
                    result.append(alternative_name)
        return result

    def disclose_reference(self, skill_name: str, relative_path: str, *, max_chars: int) -> ReferenceFragment:
        package = self._registry.definition(skill_name)
        return self._references.load(package.package_root, relative_path, max_chars=max_chars)


def _signal_matches(signal: str, code: str) -> bool:
    if signal == code or signal in code or code in signal:
        return True
    signal_tokens = set(signal.replace("_", "-").split("-"))
    code_tokens = set(code.replace("_", "-").split("-"))
    signal_tokens.discard("")
    code_tokens.discard("")
    return bool(signal_tokens) and signal_tokens <= code_tokens


def _evidence_matches_hook(record: Any, hook: str) -> bool:
    hook_name = str(hook).strip().casefold()
    if not hook_name:
        return False
    evidence_type = str(getattr(record, "evidence_type", "")).casefold()
    capability = str(getattr(record, "capability", "")).casefold()
    invocation = getattr(record, "invocation", {}) or {}
    tool_name = str(invocation.get("tool_name", "")).casefold()
    return hook_name in {capability, tool_name} or f"tool:{hook_name}" in evidence_type
