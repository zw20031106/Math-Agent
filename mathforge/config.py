from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from hashlib import sha256
import json
from pathlib import Path
from typing import ClassVar

from mathforge.resources import resource_path


CONFIG_SCHEMA_VERSION = "1.5"
COMPETITION_CONFIG_PATH = resource_path("config", "competition.json")
_METADATA_FIELDS = frozenset({"schema_version", "profile", "status"})


@dataclass(frozen=True)
class HarnessConfig:
    SCHEMA_VERSION: ClassVar[str] = CONFIG_SCHEMA_VERSION

    schema_version: str = CONFIG_SCHEMA_VERSION
    profile: str = "custom"
    status: str = "custom"
    model_max_concurrency: int = 16
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
    outer_platform_limit_seconds: float = 1200.0
    model_queue_budget_seconds: float = 15.0
    max_background_model_tails: int = 16
    late_result_registry_max_entries: int = 64
    trace_max_chars: int = 0
    trace_max_events: int = 0
    final_response_max_chars: int = 20000
    public_result_max_bytes: int = 4000000
    judge_trace_max_events: int = 64
    judge_trace_max_chars: int = 196608
    judge_trace_event_max_chars: int = 16384
    candidate_summary_max_count: int = 8
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
    enable_shadow: bool = False
    enable_frozen_lemma_store: bool = False
    enable_long_horizon: bool = False

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
            "enable_shadow",
            "enable_frozen_lemma_store",
            "enable_long_horizon",
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
            "final_response_max_chars": (4096, 200000),
            "public_result_max_bytes": (4096, 8000000),
            "judge_trace_max_events": (8, 256),
            "judge_trace_max_chars": (4096, 1000000),
            "judge_trace_event_max_chars": (1024, 65536),
            "candidate_summary_max_count": (1, 64),
            "max_claims": (1, 64),
            "max_tool_calls": (1, 10000),
            "max_isolated_tool_calls": (1, 10000),
            "max_evidence_records": (1, 100000),
            "max_prompt_chars_total": (256, 5000000),
            "max_background_model_tails": (1, 64),
            "late_result_registry_max_entries": (1, 10000),
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
            "outer_platform_limit_seconds",
            "model_queue_budget_seconds",
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
        if self.hard_deadline_seconds >= self.outer_platform_limit_seconds:
            raise ValueError(
                "hard_deadline_seconds must be below outer_platform_limit_seconds"
            )
        if self.max_background_model_tails < self.model_max_concurrency:
            raise ValueError(
                "max_background_model_tails must cover model_max_concurrency"
            )
        if self.judge_trace_event_max_chars >= self.judge_trace_max_chars:
            raise ValueError(
                "judge_trace_event_max_chars must be below judge_trace_max_chars"
            )
        if self.public_result_max_bytes <= self.judge_trace_max_chars:
            raise ValueError(
                "public_result_max_bytes must exceed judge_trace_max_chars"
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

def load_competition_config() -> HarnessConfig:
    return HarnessConfig.from_json(COMPETITION_CONFIG_PATH)
