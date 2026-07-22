from __future__ import annotations

from typing import Any

from mathforge.config import HarnessConfig
from mathforge.harness.budget import CallBudget
from mathforge.harness.fallback import FallbackSolver
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.harness.session import create_session
from mathforge.harness.trace import TraceBuilder


PRIMARY_SYSTEM_PROMPT = """You are PrimarySolver, a rigorous mathematical reasoner.
Solve the problem using explicit assumptions and verifiable steps. End with a clear
final answer. Do not claim to have used tools or evidence that were not provided.
"""


class MathForgeHarness:
    """Thread-safe facade over the injected official model client."""

    def __init__(self, client: Any, config: HarnessConfig | None = None) -> None:
        self._config = config or HarnessConfig.from_environment()
        gate = ModelCallGate(self._config.model_max_concurrency)
        self._provider = OfficialClientProvider(client, gate)
        self._fallback = FallbackSolver()

    def solve(self, problem: str, metadata: dict) -> dict:
        normalized_problem = problem if isinstance(problem, str) else str(problem)
        safe_metadata = dict(metadata) if isinstance(metadata, dict) else {}
        session = create_session(
            normalized_problem,
            safe_metadata,
            CallBudget(max_calls=self._config.max_model_calls),
        )
        trace = TraceBuilder(session.trace_events)
        trace.add("session_started", session_id=session.session_id)

        try:
            session.budget.consume()
            response = self._provider.chat(
                messages=[
                    {"role": "system", "content": PRIMARY_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Problem:\n{normalized_problem}\n\nProvide a complete solution.",
                    },
                ],
                temperature=self._config.primary_temperature,
                max_tokens=self._config.primary_max_tokens,
            )
            if not response.strip():
                raise ValueError("empty model response")
            trace.add("primary_completed", model_calls=session.budget.used_calls)
            final_response = response
        except Exception:  # The public contract requires a result on every path.
            final_response = self._fallback.solve(normalized_problem)
            trace.add("fallback_used", reason="primary_unavailable")

        return {
            "final_response": final_response,
            "trace": trace.build(),
        }
