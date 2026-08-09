from __future__ import annotations

from dataclasses import dataclass

from mathforge.skills.reference_loader import ReferenceFragment, ReferenceLoader
from mathforge.skills.registry import SkillRegistry
from mathforge.tools.registry import ToolRegistry


@dataclass(frozen=True)
class SkillCapabilities:
    skill_name: str
    requested: tuple[str, ...]
    authorized: tuple[str, ...]
    unavailable: tuple[str, ...]


class SkillRuntime:
    """Capability and disclosure boundary for passive Skill packages."""

    def __init__(self, registry: SkillRegistry, tools: ToolRegistry) -> None:
        self._registry = registry
        self._tools = tools
        self._references = ReferenceLoader()

    def capabilities(self, skill_name: str) -> SkillCapabilities:
        requested = self._registry.definition(skill_name).requires
        known = set(self._tools.names())
        authorized = tuple(name for name in requested if name in known)
        unavailable = tuple(name for name in requested if name not in known)
        return SkillCapabilities(skill_name, requested, authorized, unavailable)

    def disclose_reference(self, skill_name: str, relative_path: str, *, max_chars: int) -> ReferenceFragment:
        package = self._registry.definition(skill_name)
        return self._references.load(package.package_root, relative_path, max_chars=max_chars)
