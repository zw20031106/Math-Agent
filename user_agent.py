from mathforge.config import HarnessConfig, load_competition_config
from mathforge.model_identity import official_client_model_identity
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
        result = self._harness.solve(problem, metadata)
        return build_public_result(identifier_from_metadata(metadata), result)
