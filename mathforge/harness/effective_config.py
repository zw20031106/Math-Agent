from __future__ import annotations

from typing import Any

from mathforge.agents.registry import PromptContractLoader
from mathforge.config import HarnessConfig
from mathforge.harness.model_policy import (
    stage_call_timeout,
    stage_output_cap,
    stage_p95_seconds,
)
from mathforge.harness.reasoning_state import REASONING_STATE_MAX_TOKENS


_ROLE_DIRECTORIES = {
    "RouterPlanner": "router_planner",
    "PrimarySolver": "primary_solver",
    "AlternativeSolver": "alternative_solver",
    "LemmaCurator": "lemma_curator",
    "VerifierSkeptic": "verifier_skeptic",
    "RepairAgent": "repair",
    "LLMFinalizer": "finalizer",
}
_STAGES = (
    "router",
    "primary",
    "alternative",
    "lemma",
    "verifier",
    "repair",
    "finalizer",
)


def build_effective_config_snapshot(
    config: HarnessConfig,
    contracts: PromptContractLoader,
    *,
    frozen_lemma_store_requested: bool,
    frozen_lemma_store_count: int,
    frozen_lemma_store_disabled_reason: str,
) -> dict[str, Any]:
    """Build the safe final runtime limits after deterministic overrides."""

    return {
        "schema_version": "1.1",
        "profile": config.profile,
        "prompt": {
            "configured_primary_max_tokens": config.primary_max_tokens,
            "role_context_max_chars": {
                role: contracts.load(directory).max_context_chars
                for role, directory in _ROLE_DIRECTORIES.items()
            },
            "skill_char_budget": config.skill_char_budget,
            "raw_context_max_chars": config.raw_context_max_chars,
            "max_prompt_chars_total": config.max_prompt_chars_total,
            "stage_output_cap_tokens": {
                stage: stage_output_cap(stage) for stage in _STAGES
            },
        },
        "provider": {
            "interface": "injected_client.chat",
            "max_physical_concurrency": config.model_max_concurrency,
            "max_background_tails": config.max_background_model_tails,
            "queue_budget_cap_seconds": config.model_queue_budget_seconds,
            "context_window_tokens": config.model_context_window_tokens,
            "context_safety_margin_tokens": (
                config.context_safety_margin_tokens
            ),
            "stage_p95_seconds": {
                stage: stage_p95_seconds(stage) for stage in _STAGES
            },
            "stage_timeout_seconds": {
                stage: stage_call_timeout(stage) for stage in _STAGES
            },
        },
        "deadline": {
            "outer_platform_limit_seconds": (
                config.outer_platform_limit_seconds
            ),
            "soft_deadline_seconds": config.soft_deadline_seconds,
            "exploration_deadline_seconds": (
                config.exploration_deadline_seconds
            ),
            "hard_deadline_seconds": config.hard_deadline_seconds,
            "deterministic_finalize_reserve_seconds": (
                config.deterministic_finalize_reserve_seconds
            ),
            "model_call_start_margin_seconds": (
                config.model_call_start_margin_seconds
            ),
        },
        "features": {
            "long_horizon_reasoning": {
                "enabled": config.enable_long_horizon,
                "protocols": ["explore", "continue", "synthesize"],
                "max_rounds": 3,
                "state_max_tokens": REASONING_STATE_MAX_TOKENS,
                "stores_public_state_only": True,
            },
            "skill_tool_feedback": {
                "dynamic_skill_fragments": config.enable_skills,
                "selection_inputs": [
                    "ProblemIR",
                    "SubgoalLedger",
                    "FailureCode",
                ],
                "host_owned_check_spec": config.enable_tools,
                "tool_feedback_protocol": (
                    "work_item/local_tool/ToolResult/continue"
                ),
            },
            "reviewed_method_cards": {
                "read_only": True,
                "runtime_rag_enabled": config.enable_rag,
                "ab_validation_required": True,
            },
            "frozen_lemma_store": {
                "requested": bool(frozen_lemma_store_requested),
                "effective": bool(frozen_lemma_store_count),
                "record_count": max(0, int(frozen_lemma_store_count)),
                "disabled_reason": str(
                    frozen_lemma_store_disabled_reason
                ),
            }
        },
    }
