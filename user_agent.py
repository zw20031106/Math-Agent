from mathforge.config import HarnessConfig, load_competition_config
from mathforge.runtime import MathForgeHarness


class ReasoningAgent:
    def __init__(self, client, *args, **kwargs):
        config = kwargs.pop("config", None)
        del args, kwargs
        if config is not None and not isinstance(config, HarnessConfig):
            raise TypeError("config must be a HarnessConfig")
        self._harness = MathForgeHarness(client, config or load_competition_config())

    def solve(self, problem: str, metadata: dict) -> dict:
        return self._harness.solve(problem, metadata)
