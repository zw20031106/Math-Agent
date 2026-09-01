from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable

from mathforge.context.errors import ContextBudgetExceeded
from mathforge.harness.fingerprints import content_tree_fingerprint
from mathforge.harness.fingerprints import semantic_fingerprint
from mathforge.resources import resource_path


FIXED_ROLES = (
    "RouterPlanner",
    "PrimarySolver",
    "AlternativeSolver",
    "LemmaCurator",
    "VerifierSkeptic",
    "RepairAgent",
    "LLMFinalizer",
)
REQUIRED_CONTRACT_FIELDS = (
    "role",
    "objective",
    "input_schema",
    "output_schema",
    "visible_memory",
    "forbidden_context",
    "allowed_tools",
    "failure_policy",
    "stop_condition",
    "max_context_chars",
    "version",
)
SKILL_REQUIRED_FIELDS = (
    "name",
    "subject",
    "kind",
    "version",
    "triggers",
    "roles",
)
SKILL_REQUIRED_SECTIONS = (
    "triggers",
    "roles",
    "method decision tree",
    "theorem preconditions",
    "common errors",
    "counterexample checklist",
    "compatible check types",
    "answer normalization",
    "trace step guidance",
)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        raise ValueError("missing frontmatter")
    marker = text.find("\n---\n", 4)
    if marker < 0:
        raise ValueError("unterminated frontmatter")
    fields: dict[str, str] = {}
    for line in text[4:marker].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if not separator or not key.strip():
            raise ValueError(f"invalid frontmatter line: {line}")
        fields[key.strip()] = value.strip()
    return fields, text[marker + 5 :].strip()


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    subject: str
    kind: str
    version: str
    triggers: tuple[str, ...]
    roles: tuple[str, ...]
    sections: tuple[str, ...]
    body: str


@dataclass(frozen=True)
class SkillComposition:
    text: str
    included: tuple[str, ...]
    omitted: tuple[str, ...]
    unknown: tuple[str, ...]


class SkillRegistry:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root or resource_path("skills")
        self._skills = self._load()

    @property
    def fingerprint(self) -> str:
        return content_tree_fingerprint(self._root)

    @property
    def manifest(self) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        for path in sorted(self._root.rglob("*.md")):
            fields, _ = _parse_frontmatter(path.read_text(encoding="utf-8"))
            items.append(
                {
                    "name": fields.get("name", path.stem),
                    "version": fields.get("version", "1"),
                    "roles": fields.get("roles", ""),
                    "sha256": _normalized_file_hash(path),
                }
            )
        return items

    def _load(self) -> dict[str, SkillDefinition]:
        loaded: dict[str, SkillDefinition] = {}
        if not self._root.exists():
            return loaded
        for path in sorted(self._root.rglob("*.md")):
            fields, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
            missing_fields = [
                field for field in SKILL_REQUIRED_FIELDS if not fields.get(field)
            ]
            if missing_fields:
                raise ValueError(
                    f"{path.name} skill fields missing: {', '.join(missing_fields)}"
                )
            name = fields["name"]
            if name in loaded:
                raise ValueError(f"duplicate skill: {name}")
            if fields["version"] != "2.0":
                raise ValueError(f"{name} must use Skill version 2.0")
            if fields["kind"] not in {"domain", "general"}:
                raise ValueError(f"{name} has invalid skill kind")
            triggers = _split_frontmatter_list(fields["triggers"])
            roles = _split_frontmatter_list(fields["roles"])
            if not triggers:
                raise ValueError(f"{name} must declare triggers")
            invalid_roles = sorted(set(roles) - set(FIXED_ROLES))
            if not roles or invalid_roles:
                raise ValueError(f"{name} has invalid roles: {invalid_roles}")
            sections = tuple(
                line[3:].strip().lower()
                for line in body.splitlines()
                if line.startswith("## ")
            )
            missing_sections = [
                section
                for section in SKILL_REQUIRED_SECTIONS
                if section not in sections
            ]
            if missing_sections:
                raise ValueError(
                    f"{name} skill sections missing: {', '.join(missing_sections)}"
                )
            loaded[name] = SkillDefinition(
                name=name,
                subject=fields["subject"],
                kind=fields["kind"],
                version=fields["version"],
                triggers=triggers,
                roles=roles,
                sections=sections,
                body=body,
            )
        return loaded

    def names(self) -> list[str]:
        return sorted(self._skills)

    def definition(self, name: str) -> SkillDefinition:
        return self._skills[name]

    def names_for_role(
        self,
        names: Iterable[str],
        role: str,
    ) -> list[str]:
        return [
            name
            for name in dict.fromkeys(names)
            if name in self._skills and role in self._skills[name].roles
        ]

    def compose(self, names: Iterable[str], max_chars: int) -> str:
        return self.compose_for_role(names, max_chars=max_chars).text

    def compose_for_role(
        self,
        names: Iterable[str],
        *,
        max_chars: int,
        role: str | None = None,
    ) -> SkillComposition:
        if max_chars < 0:
            raise ValueError("skill composition budget must be nonnegative")
        blocks: list[str] = []
        seen: set[str] = set()
        used = 0
        included: list[str] = []
        omitted: list[str] = []
        unknown: list[str] = []
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            definition = self._skills.get(name)
            if definition is None:
                unknown.append(name)
                continue
            if role is not None and role not in definition.roles:
                continue
            block = f"# Skill: {name}\n{definition.body}".strip()
            separator_chars = 2 if blocks else 0
            if used + separator_chars + len(block) > max_chars:
                omitted.append(name)
                continue
            blocks.append(block)
            included.append(name)
            used += separator_chars + len(block)
        return SkillComposition(
            text="\n\n".join(blocks),
            included=tuple(included),
            omitted=tuple(omitted),
            unknown=tuple(unknown),
        )


@dataclass(frozen=True)
class PromptContract:
    fields: dict[str, str]
    body: str
    source_sha256: str = ""

    @property
    def max_context_chars(self) -> int:
        return int(self.fields["max_context_chars"])

    def render_system(self, runtime_instructions: str = "") -> str:
        role = self.fields["role"]
        contract_lines = [
            # Keep the stable role preamble for existing injected clients that
            # identify the role from the first bytes; all substantive guidance
            # below is Chinese.
            f"You are {role}. 你是 {role}，请遵循提示合同版本 {self.fields['version']}。",
            f"目标：{self.fields['objective']}。",
            f"仅可见上下文：{self.fields['visible_memory']}。",
            f"禁止使用的上下文：{self.fields['forbidden_context']}。",
            f"允许的工具：{self.fields['allowed_tools']}。",
            f"失败策略：{self.fields['failure_policy']}。",
            f"停止条件：{self.fields['stop_condition']}。",
            "语言要求：所有自然语言解释、步骤、理由和结论必须使用中文；数学公式、JSON 字段名、协议标识和技能名称保持原样。",
            self.body,
        ]
        if runtime_instructions.strip():
            contract_lines.append(runtime_instructions.strip())
        return "\n".join(contract_lines)

    def render_compact_system(self, runtime_instructions: str = "") -> str:
        """Render only contract fields and essential format constraints."""

        role = self.fields["role"]
        lines = [
            f"You are {role}. 你是 {role}，合同版本 {self.fields['version']}。",
            f"目标：{self.fields['objective']}。",
            f"输入字段：{self.fields['input_schema']}；输出字段：{self.fields['output_schema']}。",
            f"可见状态：{self.fields['visible_memory']}。",
            f"禁止状态：{self.fields['forbidden_context']}。",
            f"工具：{self.fields['allowed_tools']}；失败：{self.fields['failure_policy']}；停止：{self.fields['stop_condition']}。",
            "自然语言必须中文；公式、JSON 字段名、协议标识和技能名保持原样。使用 standard LaTeX，JSON 反斜杠按 JSON 转义。",
            # The contract body remains part of the authoritative system
            # message.  Compact rendering removes duplicated field prose but
            # must not silently discard role-specific mathematical rules.
            self.body,
        ]
        if runtime_instructions.strip():
            lines.append(runtime_instructions.strip())
        return "\n".join(lines)


class PromptContractLoader:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root or resource_path("prompts")

    @property
    def fingerprint(self) -> str:
        compiler_path = Path(__file__).with_name("prompt_compiler.py")
        examples_path = Path(__file__).resolve().parents[1] / (
            "tool_prompt_examples.py"
        )
        return semantic_fingerprint(
            {
                "contracts": content_tree_fingerprint(self._root),
                "compiler": _normalized_file_hash(compiler_path),
                "tool_claim_examples": _normalized_file_hash(examples_path),
            }
        )

    @property
    def manifest(self) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        for path in sorted(self._root.glob("*/contract.md")):
            fields, _ = _parse_frontmatter(path.read_text(encoding="utf-8"))
            items.append(
                {
                    "name": path.parent.name,
                    "role": fields.get("role", ""),
                    "version": fields.get("version", "1"),
                    "sha256": _normalized_file_hash(path),
                }
            )
        compiler_path = Path(__file__).with_name("prompt_compiler.py")
        examples_path = Path(__file__).resolve().parents[1] / (
            "tool_prompt_examples.py"
        )
        items.append(
            {
                "name": "host_prompt_compiler",
                "role": "Host",
                "version": "4",
                "sha256": semantic_fingerprint(
                    {
                        "compiler": _normalized_file_hash(compiler_path),
                        "tool_claim_examples": _normalized_file_hash(
                            examples_path
                        ),
                    }
                ),
            }
        )
        return items

    def load(self, role_directory: str) -> PromptContract:
        path = self._root / role_directory / "contract.md"
        fields, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        missing = [name for name in REQUIRED_CONTRACT_FIELDS if not fields.get(name)]
        if missing:
            raise ValueError(f"prompt contract missing: {', '.join(missing)}")
        int(fields["max_context_chars"])
        return PromptContract(
            fields=fields,
            body=body,
            source_sha256=_normalized_file_hash(path),
        )

    def system_prompt(self, role_directory: str, runtime_instructions: str = "") -> str:
        return self.load(role_directory).render_system(runtime_instructions)

    def messages(
        self,
        role_directory: str,
        user_content: str,
        runtime_instructions: str = "",
    ) -> list[dict[str, str]]:
        contract = self.load(role_directory)
        system = contract.render_system(runtime_instructions)
        total = len(system) + len(user_content)
        if total > contract.max_context_chars:
            raise ContextBudgetExceeded(
                f"{contract.fields['role']} messages require {total} chars, "
                f"budget is {contract.max_context_chars}"
            )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]


def _normalized_file_hash(path: Path) -> str:
    return sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _split_frontmatter_list(value: str) -> tuple[str, ...]:
    return tuple(
        item.strip()
        for item in value.replace("|", ",").split(",")
        if item.strip()
    )
