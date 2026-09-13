"""Shared MechMath-inspired rendering for MathForge Skill method cards.

MechMath's public harness separates dispatch, specialist work, artifact
handoffs, verification, and revision.  MathForge keeps its own deterministic
host and V2/V3 schemas, so this module only standardizes the model-facing card
presentation.  It never creates an Agent result, tool evidence, lifecycle ID,
or verification status.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


MECHMATH_SKILL_FORMAT = "mmat-method-card-v1"

# These sections are added to every source Skill by the migration utility.  A
# fallback renderer is retained for tests or third-party packages that have
# not yet been migrated; it keeps the runtime format safe without fabricating
# mathematical content.
COMMON_METHOD_CARD_SECTIONS = (
    "quick dispatch",
    "input contract",
    "workflow",
    "shared artifacts",
    "verification boundary",
    "failure routing",
    "output contract",
)


def _value(definition: Any, name: str, default: Any = "") -> Any:
    value = getattr(definition, name, default)
    return default if value is None else value


def _items(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        value = value.replace("|", ",").split(",")
    if not isinstance(value, Sequence):
        return ()
    return tuple(
        dict.fromkeys(
            str(item).strip()
            for item in value
            if str(item).strip()
        )
    )


def _join(value: Any, fallback: str = "无") -> str:
    items = _items(value)
    return ", ".join(items) if items else fallback


def _fallback_common_sections(definition: Any, role: str) -> dict[str, str]:
    """Build only protocol guidance when a non-migrated package is supplied."""

    name = str(_value(definition, "name", "unnamed"))
    version = str(_value(definition, "version", ""))
    roles = _join(_value(definition, "roles"))
    triggers = _join(_value(definition, "triggers"))
    patterns = _join(_value(definition, "problem_patterns", ()))
    method = str(_value(definition, "method_family", name))
    requires = _join(_value(definition, "requires", ()))
    hooks = _join(_value(definition, "verification_hooks", ()))
    alternatives = _join(_value(definition, "alternative_skills", ()))
    failures = _join(_value(definition, "failure_signals", ()))
    return {
        "quick dispatch": (
            f"`{name}` v{version} owner={role}；触发={triggers}；"
            f"模式={patterns}；方法=`{method}`；需过前提门。"
        ),
        "input contract": (
            f"读原题/ProblemIR/公开义务/状态；能力={requires}；hooks={hooks}；"
            f"替代={alternatives}；不可用由 Host 降级。"
        ),
        "workflow": (
            "识别 → 前提/域/边界/分支 → Claim/步骤 → 证据 → 交接。"
        ),
        "shared artifacts": (
            "公开条件、Claim/Obligation、证据、未决项、下一步；Host 管理 ID/版本。"
        ),
        "verification boundary": (
            f"hooks={hooks} 仅限 policy 范围；未知/缺证据/版本错/开放义务="
            "unknown；计数、哈希、相关同意不等于证明。"
        ),
        "failure routing": (
            f"信号={failures}；保留工件重规划；局部错误做 closure，"
            "改变方法/假设报告 global_method_failure。"
        ),
        "output contract": (
            "只输出公开语义；不生成 Host ID/预算/参数/ACK；停止前写未决义务。"
        ),
    }


def render_method_card(
    definition: Any,
    role: str,
    selected_sections: Sequence[str] = (),
) -> str:
    """Render one role-scoped, artifact-oriented Skill card.

    ``selected_sections`` contains the mathematical sections selected by the
    existing MathForge role projection.  Common method-card sections are
    always shown first so a downstream model sees the lifecycle protocol even
    when it receives a small role-specific slice.
    """

    raw_sections = _value(definition, "sections", {})
    sections: Mapping[str, Any] = raw_sections if isinstance(raw_sections, Mapping) else {}
    common = _fallback_common_sections(definition, role)
    blocks = [
        f"# Skill: {str(_value(definition, 'name', 'unnamed'))} "
        f"({str(_value(definition, 'version', ''))})",
        "格式：mmat-method-card-v1；先执行适用性与前提门，再执行方法、验证和工件交接。",
        f"当前角色 owner：{role}。主机仍拥有所有 ID、版本、预算、工具参数和状态。",
    ]
    for name in COMMON_METHOD_CARD_SECTIONS:
        # Source files keep the full protocol prose for review and provenance,
        # but model-facing projections use the deterministic compact card.
        # This preserves the problem-share/context budget while retaining the
        # method-specific sections below.
        content = common[name]
        blocks.append(f"## {name.title()}\n{content}")
    seen: set[str] = set(COMMON_METHOD_CARD_SECTIONS)
    # V2 domain cards are broad compatibility taxonomies.  Keep their
    # complete source body available through the legacy registry, but project
    # only a compact method slice into each bounded runtime prompt so several
    # route-selected cards can coexist.  V3 method cards retain their full
    # audited sections and can disclose references progressively.
    legacy = str(_value(definition, "version", "")).strip() == "2.0"
    selected_values = [
        (str(name), str(sections.get(str(name).casefold(), "")).strip())
        for name in selected_sections
        if str(sections.get(str(name).casefold(), "")).strip()
    ]
    legacy_budget = 420 if legacy else None
    per_section = (
        max(64, legacy_budget // max(1, len(selected_values)))
        if legacy_budget is not None
        else None
    )
    for name, content in selected_values:
        normalized = name.casefold()
        if normalized in seen:
            continue
        if per_section is not None and len(content) > per_section:
            content = content[:per_section].rstrip() + "…"
        blocks.append(f"## {str(name).title()}\n{content}")
        seen.add(normalized)
    return "\n\n".join(blocks).strip()


__all__ = [
    "COMMON_METHOD_CARD_SECTIONS",
    "MECHMATH_SKILL_FORMAT",
    "render_method_card",
]
