from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from functools import lru_cache
import json
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING, Any

from mathforge.agents.registry import PromptContractLoader
from mathforge.config import HarnessConfig
from mathforge.harness.context_budget import tokenizer_provenance
from mathforge.harness.fingerprints import semantic_fingerprint
from mathforge.model_identity import ModelIdentity, unreported_model_identity
from mathforge.retrieval.schemas import RAG_SCHEMA_VERSION
from mathforge.resources import resource_path
from mathforge.skills.registry import SkillRegistry
from mathforge.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from mathforge.retrieval.retriever import Retriever


PROVENANCE_SCHEMA_VERSION = "1.2"
ROOT = Path(__file__).resolve().parents[1]
BUILD_PROVENANCE_MANIFEST = resource_path(
    "data",
    "build_provenance_manifest.json",
)


@dataclass(frozen=True)
class RunProvenance:
    schema_version: str
    code_commit: str
    code_dirty: bool | None
    model_identity: dict[str, Any]
    tokenizer: dict[str, str]
    config: dict[str, str]
    prompts: list[dict[str, str]]
    skills: list[dict[str, str]]
    rag: dict[str, str]
    tools: list[dict[str, str]]
    content_reviews: dict[str, str]
    component_decisions: dict[str, str]

    def __post_init__(self) -> None:
        self.validate()

    @property
    def fingerprint(self) -> str:
        return semantic_fingerprint(self.to_dict())

    def validate(self) -> None:
        if self.schema_version != PROVENANCE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported provenance schema version: {self.schema_version!r}"
            )
        if not self.code_commit:
            raise ValueError("provenance commit is required")
        if self.code_dirty is not None and not isinstance(self.code_dirty, bool):
            raise ValueError("provenance dirty state is invalid")
        ModelIdentity.from_dict(self.model_identity)
        if not self.tokenizer.get("repository") or not self.tokenizer.get("revision"):
            raise ValueError("tokenizer provenance identity is incomplete")
        _require_sha256(
            self.tokenizer.get("tokenizer_json_sha256"),
            "tokenizer JSON",
        )
        _require_sha256(
            self.tokenizer.get("tokenizer_config_sha256"),
            "tokenizer config",
        )
        _require_sha256(
            self.tokenizer.get("chat_template_sha256"),
            "tokenizer chat template",
        )
        _require_sha256(
            self.tokenizer.get("fallback_sha256"),
            "tokenizer fallback",
        )
        if not self.config.get("schema_version"):
            raise ValueError("provenance config schema version is required")
        _require_sha256(self.config.get("sha256"), "config")
        if not self.prompts or not self.skills or not self.tools:
            raise ValueError("provenance content manifests must be non-empty")
        for group_name, items in (
            ("prompts", self.prompts),
            ("skills", self.skills),
        ):
            for item in items:
                if not item.get("name") or not item.get("version"):
                    raise ValueError(f"{group_name} provenance entry is incomplete")
                _require_sha256(item.get("sha256"), group_name)
        for item in self.tools:
            if not item.get("name") or not item.get("version"):
                raise ValueError("tool provenance entry is incomplete")
            _require_sha256(item.get("limitations_sha256"), "tool limitations")
        if self.rag.get("schema_version") != RAG_SCHEMA_VERSION:
            raise ValueError("RAG provenance schema version is invalid")
        _require_sha256(self.rag.get("knowledge_db_sha256"), "knowledge DB")
        _require_sha256(
            self.content_reviews.get("manifest_sha256"),
            "content review manifest",
        )
        _require_sha256(
            self.component_decisions.get("manifest_sha256"),
            "component decisions",
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RunProvenance:
        expected = {
            "schema_version",
            "code_commit",
            "code_dirty",
            "model_identity",
            "tokenizer",
            "config",
            "prompts",
            "skills",
            "rag",
            "tools",
            "content_reviews",
            "component_decisions",
        }
        if set(payload) != expected:
            raise ValueError("provenance fields are invalid")
        return cls(**payload)


def build_run_provenance(
    config: HarnessConfig,
    *,
    contracts: PromptContractLoader | None = None,
    skills: SkillRegistry | None = None,
    retriever: Retriever | None = None,
    tools: ToolRegistry | None = None,
    tool_manifest: list[dict[str, str]] | None = None,
    model_identity: ModelIdentity | None = None,
    inspect_worktree: bool = False,
) -> RunProvenance:
    static = _default_static_provenance(inspect_worktree)
    prompt_manifest = (
        contracts.manifest
        if contracts is not None
        else PromptContractLoader().manifest
    )
    skill_manifest = (
        skills.manifest
        if skills is not None
        else SkillRegistry().manifest
    )
    rag_hash = (
        retriever.fingerprint
        if retriever is not None
        else str(static["knowledge_db_sha256"])
    )
    tool_manifest = (
        tool_manifest
        if tool_manifest is not None
        else tools.manifest
        if tools is not None
        else ToolRegistry().manifest
    )
    return RunProvenance(
        schema_version=PROVENANCE_SCHEMA_VERSION,
        code_commit=str(static["code_commit"]),
        code_dirty=static["code_dirty"],
        model_identity=(model_identity or unreported_model_identity()).to_dict(),
        tokenizer=tokenizer_provenance(),
        config={
            "schema_version": config.schema_version,
            "profile": config.profile,
            "status": config.status,
            "sha256": config.fingerprint,
        },
        prompts=prompt_manifest,
        skills=skill_manifest,
        rag={
            "schema_version": RAG_SCHEMA_VERSION,
            "knowledge_db_sha256": rag_hash,
        },
        tools=tool_manifest,
        content_reviews=deepcopy(static["content_reviews"]),
        component_decisions=deepcopy(static["component_decisions"]),
    )


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _git_dirty() -> bool | None:
    try:
        output = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return bool(output.strip())


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _require_sha256(value: str | None, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} provenance hash is invalid")


@lru_cache(maxsize=2)
def _default_static_provenance(inspect_worktree: bool) -> dict[str, Any]:
    build_manifest = _read_json(BUILD_PROVENANCE_MANIFEST)
    return {
        "code_commit": _git_commit() if inspect_worktree else "uninspected-runtime",
        "code_dirty": _git_dirty() if inspect_worktree else None,
        "knowledge_db_sha256": str(
            build_manifest.get("knowledge_db_sha256", "")
        ),
        "content_reviews": dict(
            build_manifest.get("content_reviews", {})
        ),
        "component_decisions": dict(
            build_manifest.get("component_decisions", {})
        ),
    }
