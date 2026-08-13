from concurrent.futures import ThreadPoolExecutor

from mathforge.config import HarnessConfig
from mathforge.runtime import MathForgeHarness
from tests.fake_client import FakeClient


def test_ten_concurrent_solves_do_not_cross_contaminate() -> None:
    client = FakeClient(delay=0.01)
    harness = MathForgeHarness(client, HarnessConfig(model_max_concurrency=3))
    problems = [f"problem-{index}" for index in range(10)]

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(lambda problem: harness.solve(problem, {}), problems))

    for problem, result in zip(problems, results, strict=True):
        assert result["final_response"] == problem
    session_ids = [result["trace"][0]["session_id"] for result in results]
    assert len(set(session_ids)) == 10
    assert client.max_active_calls <= 3
