from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Iterable

from mathforge.agents.registry import SkillComposition
from mathforge.agents.registry import SkillRegistry as LegacySkillRegistry
from mathforge.harness.fingerprints import content_tree_fingerprint
from mathforge.resources import resource_path
from mathforge.skills.loader import load_legacy_v2_skill, load_v3_package
from mathforge.skills.quality import SkillQualityGate, SkillQualityReport
from mathforge.skills.schema import SkillPackage


_SKILL_SECTION_ZH = {
    "recognition": "识别",
    "do not use when": "不适用情形",
    "core theorem": "核心定理",
    "exact preconditions": "精确前提",
    "procedure": "步骤",
    "branch conditions": "分支条件",
    "failure modes": "失败模式",
    "counterexample patterns": "反例模式",
    "verification recipe": "验证方法",
    "mini example": "简短示例",
    "alternative strategy": "替代策略",
    "stop / escalate conditions": "停止或升级条件",
    "triggers": "触发条件",
    "roles": "适用角色",
}


def _chinese_skill_block(name: str, body: str) -> str:
    """Render a model-facing Skill block with an explicit Chinese contract."""

    lines = [
        f"# Skill: {name}",
        "格式：mmat-method-card-v1；先执行适用性与前提门，再执行方法、验证和工件交接。",
        "语言要求：用中文理解并输出以下数学方法；公式、LaTeX、字段名和技能标识保持原样。",
    ]
    for line in str(body).splitlines():
        if line.startswith("## "):
            title = line[3:].strip().casefold()
            lines.append(f"## {_SKILL_SECTION_ZH.get(title, line[3:].strip())}")
        else:
            lines.append(line)
    return "\n".join(lines).strip()


class SkillRegistry:
    """One read-only catalog spanning V3 packages and validated V2 Skills."""

    def __init__(self, package_root: Path | None = None, legacy_root: Path | None = None) -> None:
        self._package_root = package_root or Path(__file__).with_name("packages")
        self._legacy_root = legacy_root or resource_path("skills")
        legacy = LegacySkillRegistry(self._legacy_root)
        loaded: dict[str, SkillPackage] = {}
        for name in legacy.names():
            definition = legacy.definition(name)
            matches = list(self._legacy_root.rglob(f"{name}.md"))
            source = matches[0] if matches else self._legacy_root / f"{name}.md"
            loaded[name] = load_legacy_v2_skill(definition, source)
        if self._package_root.exists():
            for path in sorted(self._package_root.rglob("SKILL.md")):
                package = load_v3_package(path)
                if package.name in loaded:
                    raise ValueError(f"duplicate Skill: {package.name}")
                loaded[package.name] = package
        self._skills = loaded
        self._quality_report: SkillQualityReport = SkillQualityGate(
            minimum_high_value_count=20
        ).assert_valid(loaded.values())
        value = (
            f"{content_tree_fingerprint(self._legacy_root)}:"
            f"{content_tree_fingerprint(self._package_root)}"
        )
        self._fingerprint = sha256(value.encode("utf-8")).hexdigest()

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    @property
    def quality_report(self) -> SkillQualityReport:
        """Immutable content-gate result bound to this registry load."""

        return self._quality_report

    @property
    def manifest(self) -> list[dict[str, str]]:
        return [
            {
                "name": skill.name,
                "version": skill.version,
                "format": skill.format_version,
                "roles": ",".join(skill.roles),
                "sha256": sha256(skill.source_path.read_bytes()).hexdigest(),
            }
            for skill in sorted(self._skills.values(), key=lambda item: item.name)
        ]

    def names(self) -> list[str]:
        return sorted(self._skills)

    def definition(self, name: str) -> SkillPackage:
        return self._skills[name]

    def names_for_role(self, names: Iterable[str], role: str) -> list[str]:
        return [name for name in dict.fromkeys(names) if name in self._skills and role in self._skills[name].roles]

    def compose(self, names: Iterable[str], max_chars: int) -> str:
        return self.compose_for_role(names, max_chars=max_chars).text

    def compose_for_role(self, names: Iterable[str], *, max_chars: int, role: str | None = None) -> SkillComposition:
        if max_chars < 0:
            raise ValueError("skill composition budget must be nonnegative")
        blocks: list[str] = []
        included: list[str] = []
        omitted: list[str] = []
        unknown: list[str] = []
        used = 0
        for name in dict.fromkeys(names):
            skill = self._skills.get(name)
            if skill is None:
                unknown.append(name)
                continue
            if role is not None and role not in skill.roles:
                continue
            block = _chinese_skill_block(name, skill.body)
            extra = len(block) + (2 if blocks else 0)
            if used + extra > max_chars:
                omitted.append(name)
                continue
            blocks.append(block)
            included.append(name)
            used += extra
        return SkillComposition("\n\n".join(blocks), tuple(included), tuple(omitted), tuple(unknown))
