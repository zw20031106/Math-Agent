from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, ClassVar


CONFIG_SCHEMA_VERSION = "1.2"
REPO_ROOT = Path(__file__).resolve().parents[1]
COMPETITION_CONFIG_PATH = REPO_ROOT / "config" / "competition.json"
_METADATA_FIELDS = frozenset({"schema_version", "profile", "status"})


@dataclass(frozen=True)
class HarnessConfig:
    SCHEMA_VERSION: ClassVar[str] = CONFIG_SCHEMA_VERSION

    schema_version: str = CONFIG_SCHEMA_VERSION
    profile: str = "custom"
    status: str = "custom"
    model_max_concurrency: int = 4
    primary_temperature: float = 0.2
    primary_max_tokens: int = 0
    max_model_calls: int = 6
    skill_char_budget: int = 6000
    raw_context_max_chars: int = 48000
    use_mcp: bool = False
    max_model_tokens: int = 0
    model_context_window_tokens: int = 262144
    context_safety_margin_tokens: int = 8192
    soft_deadline_seconds: float = 600.0
    exploration_deadline_seconds: float = 705.0
    hard_deadline_seconds: float = 870.0
    deterministic_finalize_reserve_seconds: float = 30.0
    model_call_start_margin_seconds: float = 135.0
    trace_max_chars: int = 0
    trace_max_events: int = 0
    max_claims: int = 64
    max_tool_calls: int = 32
    max_isolated_tool_calls: int = 16
    max_tool_seconds: float = 30.0
    max_evidence_records: int = 256
    max_prompt_chars_total: int = 5000000
    enable_router: bool = True
    enable_skills: bool = True
    enable_alternatives: bool = True
    enable_tools: bool = True
    enable_evidence: bool = True
    enable_proof_obligations: bool = True
    enable_verifier: bool = True
    enable_memory: bool = True
    enable_lemma_loop: bool = True
    enable_rag: bool = True
    enable_repair: bool = True
    enable_finalizer: bool = False

    def __post_init__(self) -> None:
        self.validate()

    @classmethod
    def setting_names(cls) -> set[str]:
        return {item.name for item in fields(cls)} - _METADATA_FIELDS

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(canonical).hexdigest()

    def validate(self) -> None:
        if self.schema_version != self.SCHEMA_VERSION:
            raise ValueError(
                f"unsupported configuration schema version: {self.schema_version!r}"
            )
        if (
            not isinstance(self.profile, str)
            or not self.profile.strip()
            or not isinstance(self.status, str)
            or not self.status.strip()
        ):
            raise ValueError("configuration profile and status must be non-empty strings")

        bool_fields = {
            "use_mcp",
            "enable_router",
            "enable_skills",
            "enable_alternatives",
            "enable_tools",
            "enable_evidence",
            "enable_proof_obligations",
            "enable_verifier",
            "enable_memory",
            "enable_lemma_loop",
            "enable_rag",
            "enable_repair",
            "enable_finalizer",
        }
        for name in bool_fields:
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")

        integer_ranges = {
            "model_max_concurrency": (1, 64),
            "primary_max_tokens": (0, 262144),
            "max_model_calls": (1, 64),
            "skill_char_budget": (1, 200000),
            "raw_context_max_chars": (256, 1000000),
            "max_model_tokens": (0, 10000000),
            "model_context_window_tokens": (262144, 262144),
            "context_safety_margin_tokens": (1, 131072),
            "trace_max_chars": (0, 1000000),
            "trace_max_events": (0, 100000),
            "max_claims": (1, 64),
            "max_tool_calls": (1, 10000),
            "max_isolated_tool_calls": (1, 10000),
            "max_evidence_records": (1, 100000),
            "max_prompt_chars_total": (256, 5000000),
        }
        for name, (minimum, maximum) in integer_ranges.items():
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(
                    f"{name} must be an integer in [{minimum}, {maximum}]"
                )

        if (
            type(self.primary_temperature) not in {int, float}
            or isinstance(self.primary_temperature, bool)
            or not 0.0 <= float(self.primary_temperature) <= 2.0
        ):
            raise ValueError("primary_temperature must be a number in [0, 2]")

        deadline_names = (
            "soft_deadline_seconds",
            "exploration_deadline_seconds",
            "hard_deadline_seconds",
            "deterministic_finalize_reserve_seconds",
            "max_tool_seconds",
        )
        for name in deadline_names:
            value = getattr(self, name)
            if type(value) not in {int, float} or float(value) <= 0:
                raise ValueError(f"{name} must be a positive number")
        if not (
            self.soft_deadline_seconds
            <= self.exploration_deadline_seconds
            <= self.hard_deadline_seconds
        ):
            raise ValueError(
                "deadlines must satisfy soft <= exploration <= hard"
            )
        if self.deterministic_finalize_reserve_seconds >= self.hard_deadline_seconds:
            raise ValueError(
                "deterministic_finalize_reserve_seconds must be below hard deadline"
            )
        if (
            type(self.model_call_start_margin_seconds) not in {int, float}
            or float(self.model_call_start_margin_seconds) < 0
        ):
            raise ValueError(
                "model_call_start_margin_seconds must be a nonnegative number"
            )
        if (
            self.deterministic_finalize_reserve_seconds
            + self.model_call_start_margin_seconds
            >= self.hard_deadline_seconds
        ):
            raise ValueError(
                "model call start and finalize reserves must be below hard deadline"
            )
        if self.context_safety_margin_tokens >= self.model_context_window_tokens:
            raise ValueError(
                "context_safety_margin_tokens must be below the context window"
            )
        if (
            self.primary_max_tokens > 0
            and self.max_model_tokens > 0
            and self.primary_max_tokens > self.max_model_tokens
        ):
            raise ValueError("primary_max_tokens must not exceed max_model_tokens")
        if (
            self.primary_max_tokens > 0
            and self.primary_max_tokens
            + self.context_safety_margin_tokens
            >= self.model_context_window_tokens
        ):
            raise ValueError(
                "primary_max_tokens and safety margin must leave prompt capacity"
            )
        if self.skill_char_budget > self.raw_context_max_chars:
            raise ValueError("skill_char_budget must not exceed raw_context_max_chars")
        if self.raw_context_max_chars > self.max_prompt_chars_total:
            raise ValueError(
                "raw_context_max_chars must not exceed max_prompt_chars_total"
            )
        if self.max_isolated_tool_calls > self.max_tool_calls:
            raise ValueError(
                "max_isolated_tool_calls must not exceed max_tool_calls"
            )
        if self.enable_verifier and self.max_model_calls < 2:
            raise ValueError("enable_verifier requires at least two model calls")

        dependencies = (
            (
                self.enable_verifier,
                self.enable_evidence and self.enable_proof_obligations,
                "enable_verifier requires enable_evidence and enable_proof_obligations",
            ),
            (
                self.enable_repair,
                self.enable_evidence and self.enable_tools,
                "enable_repair requires enable_evidence and enable_tools",
            ),
            (
                self.enable_lemma_loop,
                self.enable_memory and self.enable_proof_obligations,
                "enable_lemma_loop requires enable_memory and enable_proof_obligations",
            ),
            (
                self.enable_rag,
                self.enable_skills,
                "enable_rag requires enable_skills",
            ),
            (
                self.use_mcp,
                self.enable_tools,
                "use_mcp requires enable_tools",
            ),
        )
        for enabled, satisfied, message in dependencies:
            if enabled and not satisfied:
                raise ValueError(message)

    @classmethod
    def from_dict(cls, payload: dict) -> "HarnessConfig":
        if not isinstance(payload, dict):
            raise ValueError("configuration must be a JSON object")
        allowed = {item.name for item in fields(cls)}
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"unknown configuration keys: {sorted(unknown)}")
        for required in _METADATA_FIELDS:
            if required not in payload:
                raise ValueError(f"configuration is missing {required}")
        return cls(**payload)

    @classmethod
    def from_json(cls, path: Path) -> "HarnessConfig":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(payload)

    @classmethod
    def from_environment(
        cls,
        base: "HarnessConfig | None" = None,
    ) -> "HarnessConfig":
        configured = base or load_competition_config()
        values: dict[str, Any] = {}
        if "MATHFORGE_MODEL_MAX_CONCURRENCY" in os.environ:
            raw = os.environ["MATHFORGE_MODEL_MAX_CONCURRENCY"]
            try:
                values["model_max_concurrency"] = int(raw)
            except ValueError as error:
                raise ValueError(
                    "MATHFORGE_MODEL_MAX_CONCURRENCY must be an integer"
                ) from error
        if "MATHFORGE_USE_MCP" in os.environ:
            raw = os.environ["MATHFORGE_USE_MCP"].strip().lower()
            if raw not in {"0", "1", "false", "true"}:
                raise ValueError("MATHFORGE_USE_MCP must be true or false")
            values["use_mcp"] = raw in {"1", "true"}
        return replace(configured, **values)


def load_competition_config() -> HarnessConfig:
    return HarnessConfig.from_json(COMPETITION_CONFIG_PATH)
