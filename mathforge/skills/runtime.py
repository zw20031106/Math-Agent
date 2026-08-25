from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from mathforge.skills.reference_loader import ReferenceFragment, ReferenceLoader
from mathforge.skills.registry import SkillRegistry
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
