from __future__ import annotations

from pathlib import Path

from mathforge.agents.registry import SkillDefinition
from mathforge.skills.schema import SkillPackage, V3_REQUIRED_FIELDS


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        raise ValueError("missing frontmatter")
    marker = normalized.find("\n---\n", 4)
    if marker < 0:
        raise ValueError("unterminated frontmatter")
    fields: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        if current_key is not None:
            fields[current_key] = "\n".join(current_lines).strip()

    for line in normalized[4:marker].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1].isspace():
            if current_key is None:
                raise ValueError(f"invalid indented frontmatter line: {line}")
            current_lines.append(line.strip())
            continue
        key, separator, value = line.partition(":")
        if not separator or not key.strip():
            raise ValueError(f"invalid frontmatter line: {line}")
        flush()
        current_key = key.strip()
        current_lines = [value.strip()]
    flush()
    return fields, normalized[marker + 5 :].strip()


def _list(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    value = str(value).strip()
    if value in {"", "[]", "null", "~"}:
        return ()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    # Also accept the small YAML subset used for optional block lists.
    value = value.replace("\n", ",")
    return tuple(
        item.strip().lstrip("-").strip().strip("\"'")
        for item in value.split(",")
        if item.strip().lstrip("-").strip().strip("\"'")
    )


def _description(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text[:1] in {">", "|"}:
        text = text[1:].strip()
    return " ".join(text.strip("\"'").split())


def _float_field(fields: dict[str, str], key: str, default: float) -> float:
    value = fields.get(key)
    if value is None or not str(value).strip():
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid Skill numeric field {key}: {value!r}") from error


def _int_field(fields: dict[str, str], key: str, default: int) -> int:
    value = fields.get(key)
    if value is None or not str(value).strip():
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid Skill integer field {key}: {value!r}") from error


def _sections(body: str) -> dict[str, str]:
    result: dict[str, list[str]] = {}
    current = ""
    for line in body.splitlines():
        if line.startswith("## "):
            current = line[3:].strip().casefold()
            if current in result:
                raise ValueError(f"duplicate Skill section: {current}")
            result[current] = []
        elif current:
            result[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in result.items()}


def load_v3_package(package_root: Path) -> SkillPackage:
    source = package_root / "SKILL.md" if package_root.is_dir() else package_root
    fields, body = _frontmatter(source.read_text(encoding="utf-8"))
    missing = [field for field in V3_REQUIRED_FIELDS if not fields.get(field)]
    if missing:
        raise ValueError(f"{source.name} Skill fields missing: {', '.join(missing)}")
    package = SkillPackage(
        name=fields["name"],
        version=fields["version"],
        domain=fields["domain"],
        subdomain=fields["subdomain"],
        kind=fields["kind"],
        roles=_list(fields["roles"]),
        triggers=_list(fields["triggers"]),
        problem_patterns=_list(fields["problem_patterns"]),
        method_family=fields["method_family"],
        alternative_skills=_list(fields["alternative_skills"]),
        requires=_list(fields["requires"]),
        failure_signals=_list(fields["failure_signals"]),
        verification_hooks=_list(fields["verification_hooks"]),
        sections=_sections(body),
        package_root=source.parent,
        source_path=source,
        description=_description(fields.get("description")),
        negative_triggers=_list(fields.get("negative_triggers")),
        required_observables=_list(fields.get("required_observables")),
        expected_gain=_float_field(fields, "expected_gain", 0.0),
        historical_precision=_float_field(fields, "historical_precision", 1.0),
        token_cost=_int_field(fields, "token_cost", 0),
    )
    package.validate()
    return package


def load_legacy_v2_skill(definition: SkillDefinition, source_path: Path) -> SkillPackage:
    """Adapt an already validated V2 Skill without weakening its old contract."""

    sections = _sections(definition.body)
    return SkillPackage(
        name=definition.name,
        version=definition.version,
        domain=definition.subject,
        subdomain=definition.subject,
        kind=definition.kind,
        roles=definition.roles,
        triggers=definition.triggers,
        problem_patterns=definition.triggers,
        method_family=definition.name,
        alternative_skills=(),
        requires=(),
        failure_signals=(),
        verification_hooks=(),
        sections=sections,
        package_root=source_path.parent,
        source_path=source_path,
        legacy=True,
    )
