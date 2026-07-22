from mathforge.runtime import MathForgeHarness


class ReasoningAgent:
    def __init__(self, client, *args, **kwargs):
        del args, kwargs
        self._harness = MathForgeHarness(client)

    def solve(self, problem: str, metadata: dict) -> dict:
        return self._harness.solve(problem, metadata)
