from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mathforge.agents.registry import FIXED_ROLES


V3_REQUIRED_FIELDS = (
    "name",
    "version",
    "domain",
    "subdomain",
    "kind",
    "roles",
    "triggers",
    "problem_patterns",
    "method_family",
    "alternative_skills",
    "requires",
    "failure_signals",
    "verification_hooks",
)
V3_REQUIRED_SECTIONS = (
    "recognition",
    "do not use when",
    "core theorem",
    "exact preconditions",
    "procedure",
    "branch conditions",
    "failure modes",
    "counterexample patterns",
    "verification recipe",
    "mini example",
    "alternative strategy",
    "stop / escalate conditions",
)


@dataclass(frozen=True)
class SkillPackage:
    name: str
    version: str
    domain: str
    subdomain: str
    kind: str
    roles: tuple[str, ...]
    triggers: tuple[str, ...]
    problem_patterns: tuple[str, ...]
    method_family: str
    alternative_skills: tuple[str, ...]
    requires: tuple[str, ...]
    failure_signals: tuple[str, ...]
    verification_hooks: tuple[str, ...]
    sections: dict[str, str]
    package_root: Path
    source_path: Path
    legacy: bool = False

    @property
    def subject(self) -> str:
        return self.domain

    @property
    def body(self) -> str:
        blocks: list[str] = []
        for name, content in self.sections.items():
            blocks.append(f"## {name.title()}\n{content}".strip())
        return "\n\n".join(blocks)

    def validate(self) -> None:
        if self.version != "3.0":
            raise ValueError(f"{self.name} must use Skill version 3.0")
        if self.kind not in {"method", "domain", "general"}:
            raise ValueError(f"{self.name} has invalid Skill kind: {self.kind}")
        invalid_roles = sorted(set(self.roles) - set(FIXED_ROLES))
        if not self.roles or invalid_roles:
            raise ValueError(f"{self.name} has invalid roles: {invalid_roles}")
        missing = [name for name in V3_REQUIRED_SECTIONS if not self.sections.get(name)]
        if missing:
            raise ValueError(f"{self.name} sections missing: {', '.join(missing)}")
        if self.kind == "method" and not self.problem_patterns:
            raise ValueError(f"{self.name} method Skill must declare problem_patterns")
