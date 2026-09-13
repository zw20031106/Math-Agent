from __future__ import annotations

from dataclasses import dataclass
import math
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
# These fields are intentionally optional so existing version-3 packages and
# legacy V2 adapters keep loading unchanged.  They provide retrieval and
# admission context without becoming a second mathematical contract.
V3_OPTIONAL_FIELDS = (
    "description",
    "negative_triggers",
    "required_observables",
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
    # Optional retrieval metadata.  ``negative_triggers`` are ranking
    # penalties, not hard vetoes; ``required_observables`` describe evidence
    # worth looking for before applying the Skill's exact preconditions.
    description: str = ""
    negative_triggers: tuple[str, ...] = ()
    required_observables: tuple[str, ...] = ()
    legacy: bool = False
    # Optional offline priors used by SkillExecutionPlan.  They are not
    # model-generated and default conservatively for historical V2 Skills.
    expected_gain: float = 0.0
    historical_precision: float = 1.0
    token_cost: int = 0
    # MechMath-inspired method-card presentation.  The mathematical and
    # lifecycle semantics remain owned by the existing MathForge schema.
    format_version: str = "mmat-method-card-v1"

    def __post_init__(self) -> None:
        description = "" if self.description is None else str(self.description)
        object.__setattr__(self, "description", " ".join(description.split()))
        for field_name in ("negative_triggers", "required_observables"):
            value = getattr(self, field_name)
            if isinstance(value, str):
                values = (value,)
            else:
                values = value or ()
            normalized = tuple(
                dict.fromkeys(
                    str(item).strip()
                    for item in values
                    if str(item).strip()
                )
            )
            object.__setattr__(self, field_name, normalized)

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
        if not isinstance(self.description, str):
            raise ValueError(f"{self.name} description must be a string")
        for field_name in ("negative_triggers", "required_observables"):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or any(
                not isinstance(item, str) or not item.strip() for item in values
            ):
                raise ValueError(f"{self.name} {field_name} must be non-empty strings")
        if not math.isfinite(float(self.expected_gain)) or self.expected_gain < 0:
            raise ValueError(f"{self.name} expected_gain must be finite and nonnegative")
        if not 0.0 <= float(self.historical_precision) <= 1.0:
            raise ValueError(f"{self.name} historical_precision must be in [0, 1]")
        if type(self.token_cost) is not int or self.token_cost < 0:
            raise ValueError(f"{self.name} token_cost must be a nonnegative integer")
        if not str(self.format_version).strip():
            raise ValueError(f"{self.name} format_version must be non-empty")
