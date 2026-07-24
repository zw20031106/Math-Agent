from mathforge.config import HarnessConfig, load_competition_config
from mathforge.model_identity import require_exact_intern_model
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
            model_identity=require_exact_intern_model(),
        )

    def solve(self, problem: str, metadata: dict) -> dict:
        result = self._harness.solve(problem, metadata)
        return build_public_result(identifier_from_metadata(metadata), result)
