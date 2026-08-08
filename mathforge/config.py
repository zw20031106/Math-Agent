from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from hashlib import sha256
import json
from pathlib import Path
from typing import ClassVar

from mathforge.resources import resource_path


CONFIG_SCHEMA_VERSION = "2.0"
COMPETITION_CONFIG_PATH = resource_path("config", "competition.json")
_METADATA_FIELDS = frozenset({"schema_version", "profile", "status"})


def _default_stage_execution_policy() -> dict[str, dict[str, int | float]]:
    return {
        "router": {"max_tokens": 4096, "timeout_seconds": 120.0, "minimum_start_window_seconds": 60.0},
        "replan": {"max_tokens": 4096, "timeout_seconds": 120.0, "minimum_start_window_seconds": 60.0},
        "solver_progress": {"max_tokens": 4096, "timeout_seconds": 180.0, "minimum_start_window_seconds": 90.0},
        "solver_candidate_standard": {
            "max_tokens": 8192,
            "timeout_seconds": 240.0,
            "minimum_start_window_seconds": 120.0,
        },
        "solver_compact_synthesis": {
            "max_tokens": 8192,
            "timeout_seconds": 240.0,
            "minimum_start_window_seconds": 120.0,
        },
        "solver_candidate_proof": {
            "max_tokens": 12288,
            "timeout_seconds": 270.0,
            "minimum_start_window_seconds": 180.0,
        },
        "lemma_curator": {"max_tokens": 8192, "timeout_seconds": 225.0, "minimum_start_window_seconds": 120.0},
        "peer_review": {"max_tokens": 6144, "timeout_seconds": 180.0, "minimum_start_window_seconds": 90.0},
        "verifier": {"max_tokens": 6144, "timeout_seconds": 180.0, "minimum_start_window_seconds": 90.0},
        "repair": {"max_tokens": 8192, "timeout_seconds": 225.0, "minimum_start_window_seconds": 120.0},
        "finalizer": {"max_tokens": 4096, "timeout_seconds": 120.0, "minimum_start_window_seconds": 60.0},
    }


@dataclass(frozen=True)
class HarnessConfig:
    SCHEMA_VERSION: ClassVar[str] = CONFIG_SCHEMA_VERSION

    schema_version: str = CONFIG_SCHEMA_VERSION
    profile: str = "custom"
    status: str = "custom"
    case_max_concurrency: int = 3
    model_max_concurrency: int = 16
    model_requests_per_minute: int = 200
    rate_limit_window_seconds: float = 60.0
    transport_attempt_reservation: int = 3
    max_inflight_calls_per_agent: int = 1
    primary_temperature: float = 0.2
    primary_max_tokens: int = 0
    max_model_calls: int = 48
    model_call_policy: str = "adaptive_bounded"
    max_logical_model_calls_per_problem: int = 48
    soft_call_checkpoints: tuple[int, ...] = (16, 28, 40)
    speculative_exploration_cutoff: int = 40
    closure_reserve_calls: int = 8
    stage_execution_policy: dict[str, dict[str, int | float]] = field(
        default_factory=_default_stage_execution_policy
    )
    finish_reason_length_policy: str = "partial_needs_compaction"
    timeout_retry_policy: str = "wait_tail_or_replan"
    experimental_proof_max_tokens: int = 16384
    experimental_proof_timeout_seconds: float = 300.0
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
    enable_peer_cross_review: bool = False
    enable_verification_closure: bool = False
    enable_rebuttal: bool = True
    enable_verifier: bool = True
    enable_memory: bool = True
    enable_lemma_loop: bool = True
    enable_rag: bool = True
    enable_repair: bool = True
    enable_finalizer: bool = False
    enable_final_audit: bool = True
    enable_shadow: bool = False
    enable_frozen_lemma_store: bool = False
    enable_long_horizon: bool = False

    def __post_init__(self) -> None:
        incoming_logical_limit = self.max_logical_model_calls_per_problem
        if self.max_model_calls != incoming_logical_limit:
            object.__setattr__(
                self,
                "max_logical_model_calls_per_problem",
                self.max_model_calls,
            )
            if (
                self.closure_reserve_calls == 0
                and self.speculative_exploration_cutoff
                == incoming_logical_limit
            ):
                object.__setattr__(
                    self,
                    "speculative_exploration_cutoff",
                    self.max_model_calls,
                )
                if tuple(self.soft_call_checkpoints) == (
                    incoming_logical_limit,
                ):
                    object.__setattr__(
                        self,
                        "soft_call_checkpoints",
                        (self.max_model_calls,),
                    )
        if (
            self.max_model_calls != 48
            and tuple(self.soft_call_checkpoints) == (16, 28, 40)
            and self.speculative_exploration_cutoff == 40
            and self.closure_reserve_calls == 8
        ):
            object.__setattr__(self, "soft_call_checkpoints", (self.max_model_calls,))
            object.__setattr__(
                self,
                "speculative_exploration_cutoff",
                self.max_model_calls,
            )
            object.__setattr__(self, "closure_reserve_calls", 0)
        object.__setattr__(
            self,
            "soft_call_checkpoints",
            tuple(self.soft_call_checkpoints),
        )
        object.__setattr__(
            self,
            "stage_execution_policy",
            json.loads(json.dumps(self.stage_execution_policy)),
        )
        self.validate()

    @classmethod
    def setting_names(cls) -> set[str]:
        return {item.name for item in fields(cls)} - _METADATA_FIELDS

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["soft_call_checkpoints"] = list(self.soft_call_checkpoints)
        return payload

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
            "enable_peer_cross_review",
            "enable_verification_closure",
            "enable_rebuttal",
            "enable_verifier",
            "enable_memory",
            "enable_lemma_loop",
            "enable_rag",
            "enable_repair",
            "enable_finalizer",
            "enable_final_audit",
            "enable_shadow",
            "enable_frozen_lemma_store",
            "enable_long_horizon",
        }
        for name in bool_fields:
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        integer_ranges = {
            "case_max_concurrency": (1, 3),
            "model_max_concurrency": (1, 64),
            "model_requests_per_minute": (1, 200),
            "transport_attempt_reservation": (1, 200),
            "max_inflight_calls_per_agent": (1, 1),
            "primary_max_tokens": (0, 262144),
            "max_model_calls": (1, 64),
            "max_logical_model_calls_per_problem": (1, 64),
            "speculative_exploration_cutoff": (1, 64),
            "closure_reserve_calls": (0, 63),
            "experimental_proof_max_tokens": (1, 262144),
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
            self.profile in {"competition", "balanced", "safe"}
            and self.status != "test"
        ):
            if not self.enable_router:
                raise ValueError(
                    "production profiles require the authoritative Router"
                )
            if self.max_model_calls < 2:
                raise ValueError(
                    "production profiles require Router and Solver capacity"
                )

        if (
            type(self.primary_temperature) not in {int, float}
            or isinstance(self.primary_temperature, bool)
            or not 0.0 <= float(self.primary_temperature) <= 2.0
        ):
            raise ValueError("primary_temperature must be a number in [0, 2]")

        deadline_names = (
            "rate_limit_window_seconds",
            "soft_deadline_seconds",
            "exploration_deadline_seconds",
            "hard_deadline_seconds",
            "deterministic_finalize_reserve_seconds",
            "outer_platform_limit_seconds",
            "model_queue_budget_seconds",
            "max_tool_seconds",
            "experimental_proof_timeout_seconds",
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
        if self.transport_attempt_reservation > self.model_requests_per_minute:
            raise ValueError(
                "transport_attempt_reservation must not exceed the RPM limit"
            )
        if self.model_call_policy != "adaptive_bounded":
            raise ValueError("model_call_policy is invalid")
        if self.finish_reason_length_policy != "partial_needs_compaction":
            raise ValueError("finish_reason_length_policy is invalid")
        if self.timeout_retry_policy != "wait_tail_or_replan":
            raise ValueError("timeout_retry_policy is invalid")
        self._validate_stage_execution_policy()
        if self.max_model_calls != self.max_logical_model_calls_per_problem:
            raise ValueError(
                "max_model_calls must equal max_logical_model_calls_per_problem"
            )
        if (
            self.speculative_exploration_cutoff
            != self.max_logical_model_calls_per_problem
            - self.closure_reserve_calls
        ):
            raise ValueError(
                "speculative cutoff must preserve closure_reserve_calls"
            )
        if (
            tuple(sorted(set(self.soft_call_checkpoints)))
            != self.soft_call_checkpoints
            or any(
                type(item) is not int
                or not 0 < item <= self.speculative_exploration_cutoff
                for item in self.soft_call_checkpoints
            )
        ):
            raise ValueError(
                "soft_call_checkpoints must be increasing exploration indices"
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
        if self.enable_peer_cross_review and (
            not self.enable_alternatives
            or self.model_call_policy != "adaptive_bounded"
            or self.max_model_calls < 7
        ):
            raise ValueError(
                "enable_peer_cross_review requires alternatives, adaptive "
                "policy, and at least seven model calls"
            )
        if self.enable_verification_closure and (
            not self.enable_peer_cross_review
            or not self.enable_verifier
            or not self.enable_repair
            or self.model_call_policy != "adaptive_bounded"
            or self.max_model_calls < 9
        ):
            raise ValueError(
                "enable_verification_closure requires F5 peer review, verifier, "
                "adaptive policy, and at least nine calls"
            )

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

    def _validate_stage_execution_policy(self) -> None:
        expected = set(_default_stage_execution_policy())
        policy = self.stage_execution_policy
        if not isinstance(policy, dict) or set(policy) != expected:
            raise ValueError("stage_execution_policy has invalid turn kinds")
        for turn_kind, payload in policy.items():
            if not isinstance(payload, dict) or set(payload) != {
                "max_tokens",
                "timeout_seconds",
                "minimum_start_window_seconds",
            }:
                raise ValueError(
                    f"stage_execution_policy.{turn_kind} has invalid fields"
                )
            max_tokens = payload["max_tokens"]
            timeout = payload["timeout_seconds"]
            minimum_window = payload["minimum_start_window_seconds"]
            if type(max_tokens) is not int or not 1 <= max_tokens <= 262144:
                raise ValueError(
                    f"stage_execution_policy.{turn_kind}.max_tokens is invalid"
                )
            if type(timeout) not in {int, float} or timeout <= 0:
                raise ValueError(
                    f"stage_execution_policy.{turn_kind}.timeout_seconds is invalid"
                )
            if (
                type(minimum_window) not in {int, float}
                or isinstance(minimum_window, bool)
                or not 0 < float(minimum_window) <= float(timeout)
            ):
                raise ValueError(
                    "stage_execution_policy."
                    f"{turn_kind}.minimum_start_window_seconds is invalid"
                )

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
        if payload.get("profile") == "competition":
            missing_settings = cls.setting_names() - set(payload)
            if missing_settings:
                raise ValueError(
                    "competition configuration is missing settings: "
                    f"{sorted(missing_settings)}"
                )
        return cls(**payload)

    @classmethod
    def from_json(cls, path: Path) -> "HarnessConfig":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(payload)

def load_competition_config() -> HarnessConfig:
    return HarnessConfig.from_json(COMPETITION_CONFIG_PATH)
