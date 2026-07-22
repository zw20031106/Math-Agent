from __future__ import annotations

import os
from dataclasses import dataclass
from dataclasses import fields
import json
from pathlib import Path


@dataclass(frozen=True)
class HarnessConfig:
    model_max_concurrency: int = 4
    primary_temperature: float = 0.2
    primary_max_tokens: int = 4096
    max_model_calls: int = 4
    skill_char_budget: int = 6000
    raw_context_max_chars: int = 48000
    use_mcp: bool = False
    max_model_tokens: int = 24000
    soft_deadline_seconds: float = 720.0
    exploration_deadline_seconds: float = 780.0
    hard_deadline_seconds: float = 870.0
    trace_max_chars: int = 12000
    enable_router: bool = True
    enable_skills: bool = True
    enable_alternatives: bool = True
    enable_tools: bool = True
    enable_evidence: bool = True
    enable_proof_obligations: bool = True
    enable_memory: bool = True
    enable_lemma_loop: bool = True
    enable_rag: bool = True
    enable_repair: bool = True
    enable_finalizer: bool = True

    @classmethod
    def from_environment(cls) -> "HarnessConfig":
        raw_concurrency = os.environ.get("MATHFORGE_MODEL_MAX_CONCURRENCY", "4")
        try:
            concurrency = max(1, int(raw_concurrency))
        except ValueError:
            concurrency = 4
        use_mcp = os.environ.get("MATHFORGE_USE_MCP", "0").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        return cls(model_max_concurrency=concurrency, use_mcp=use_mcp)

    @classmethod
    def from_json(cls, path: Path) -> "HarnessConfig":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("configuration must be a JSON object")
        allowed = {field.name for field in fields(cls)}
        values = {key: value for key, value in payload.items() if key in allowed}
        return cls(**values)
