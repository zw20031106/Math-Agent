from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class HarnessConfig:
    model_max_concurrency: int = 4
    primary_temperature: float = 0.2
    primary_max_tokens: int = 4096
    max_model_calls: int = 4
    skill_char_budget: int = 6000
    raw_context_max_chars: int = 48000
    use_mcp: bool = False

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
