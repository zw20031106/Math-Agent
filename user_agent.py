from threading import BoundedSemaphore

from mathforge.config import HarnessConfig, load_competition_config
from mathforge.model_identity import official_client_model_identity
from mathforge.harness.terminalizer import minimal_fallback_result
from mathforge.output.public_result import (
    build_public_result,
    identifier_from_metadata,
)
from mathforge.output.judge_trace import minimal_judge_trace
from mathforge.runtime import MathForgeHarness


CASE_MAX_CONCURRENCY = load_competition_config().case_max_concurrency


class ReasoningAgent:
    def __init__(self, client, *args, **kwargs):
        config = kwargs.pop("config", None)
        del args, kwargs
        if config is not None and not isinstance(config, HarnessConfig):
            raise TypeError("config must be a HarnessConfig")
        active_config = config or load_competition_config()
        self._harness = MathForgeHarness(
            client,
            active_config,
            model_identity=official_client_model_identity(),
        )
        self._case_gate = BoundedSemaphore(active_config.case_max_concurrency)

    def solve(self, problem: str, metadata: dict) -> dict:
        identifier = None
        try:
            with self._case_gate:
                identifier = identifier_from_metadata(metadata)
                result = self._harness.solve(problem, metadata)
                return build_public_result(identifier, result)
        except Exception:
            fallback = minimal_fallback_result()
            return {
                "id": identifier,
                "status": "failed",
                "final_response": fallback["final_response"],
                "trace": minimal_judge_trace(),
            }
