from mathforge.config import HarnessConfig, load_competition_config
from mathforge.model_identity import official_client_model_identity
from mathforge.harness.terminalizer import minimal_fallback_result
from mathforge.output.public_result import (
    build_public_result,
    identifier_from_metadata,
)
from mathforge.runtime import MathForgeHarness


class ReasoningAgent:
    def __init__(self, client, *args, **kwargs):
        config = kwargs.pop("config", None)
        del args, kwargs
        if config is not None and not isinstance(config, HarnessConfig):
            raise TypeError("config must be a HarnessConfig")
        self._harness = MathForgeHarness(
            client,
            config or load_competition_config(),
            model_identity=official_client_model_identity(),
        )

    def solve(self, problem: str, metadata: dict) -> dict:
        identifier = None
        try:
            identifier = identifier_from_metadata(metadata)
            result = self._harness.solve(problem, metadata)
            return build_public_result(identifier, result)
        except Exception:
            fallback = minimal_fallback_result()
            return {
                "id": identifier,
                "status": "failed",
                "final_response": fallback["final_response"],
                "trace": fallback["trace"],
            }
