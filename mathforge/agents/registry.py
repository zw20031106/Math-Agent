from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable

from mathforge.context.errors import ContextBudgetExceeded
from mathforge.harness.fingerprints import content_tree_fingerprint


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
    body: str


class SkillRegistry:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path(__file__).resolve().parents[2] / "skills"
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
            name = fields.get("name", path.stem)
            if name in loaded:
                raise ValueError(f"duplicate skill: {name}")
            loaded[name] = SkillDefinition(
                name=name,
                subject=fields.get("subject", "general-math"),
                kind=fields.get("kind", "domain"),
                version=fields.get("version", "1"),
                body=body,
            )
        return loaded

    def names(self) -> list[str]:
        return sorted(self._skills)

    def compose(self, names: Iterable[str], max_chars: int) -> str:
        blocks: list[str] = []
        seen: set[str] = set()
        used = 0
        for name in names:
            if name in seen or name not in self._skills:
                continue
            seen.add(name)
            block = f"## Skill: {name}\n{self._skills[name].body}".strip()
            if used + len(block) > max_chars:
                remaining = max_chars - used
                if remaining > 0:
                    blocks.append(block[:remaining])
                break
            blocks.append(block)
            used += len(block)
        return "\n\n".join(blocks)


@dataclass(frozen=True)
class PromptContract:
    fields: dict[str, str]
    body: str

    @property
    def max_context_chars(self) -> int:
        return int(self.fields["max_context_chars"])

    def render_system(self, runtime_instructions: str = "") -> str:
        role = self.fields["role"]
        contract_lines = [
            f"You are {role}. Follow prompt contract version {self.fields['version']}.",
            f"Objective: {self.fields['objective']}.",
            f"Visible context only: {self.fields['visible_memory']}.",
            f"Forbidden context: {self.fields['forbidden_context']}.",
            f"Allowed tools: {self.fields['allowed_tools']}.",
            f"Failure policy: {self.fields['failure_policy']}.",
            f"Stop condition: {self.fields['stop_condition']}.",
            self.body,
        ]
        if runtime_instructions.strip():
            contract_lines.append(runtime_instructions.strip())
        return "\n".join(contract_lines)


class PromptContractLoader:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path(__file__).resolve().parents[2] / "prompts"

    @property
    def fingerprint(self) -> str:
        return content_tree_fingerprint(self._root)

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
        return items

    def load(self, role_directory: str) -> PromptContract:
        path = self._root / role_directory / "contract.md"
        fields, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        missing = [name for name in REQUIRED_CONTRACT_FIELDS if not fields.get(name)]
        if missing:
            raise ValueError(f"prompt contract missing: {', '.join(missing)}")
        int(fields["max_context_chars"])
        return PromptContract(fields=fields, body=body)

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
