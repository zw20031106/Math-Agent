from concurrent.futures import ThreadPoolExecutor

from mathforge.config import HarnessConfig
from mathforge.runtime import MathForgeHarness
from tests.fake_client import FakeClient


def test_eight_runner_threads_have_unique_sessions_and_bounded_calls():
    client = FakeClient(delay=0.01)
    harness = MathForgeHarness(client, HarnessConfig(model_max_concurrency=2))
    problems = [f"equation-{index}" for index in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda problem: harness.solve(problem, {}), problems))
    assert len({result["trace"][0]["session_id"] for result in results}) == 8
    assert client.max_active_calls <= 2
    for problem, result in zip(problems, results, strict=True):
        assert problem in result["final_response"]
