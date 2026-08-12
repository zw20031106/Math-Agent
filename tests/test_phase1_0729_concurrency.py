from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Event, Lock

import pytest

import user_agent as user_agent_module
from mathforge.benchmark import BenchmarkCase, run_benchmark
from mathforge.harness.provider import ModelCallGate
from scripts.run_case_outputs import CaseRunManifest
from user_agent import CASE_MAX_CONCURRENCY, ReasoningAgent


def test_reasoning_agent_admits_at_most_three_active_cases(monkeypatch):
    release = Event()
    four_started = Event()

    class ProbeHarness:
        def __init__(self):
            self.active = 0
            self.peak = 0
            self.started = 0
            self.lock = Lock()

        def solve(self, _problem, metadata, **_kwargs):
            with self.lock:
                self.active += 1
                self.started += 1
                self.peak = max(self.peak, self.active)
                if self.started == CASE_MAX_CONCURRENCY:
                    four_started.set()
            try:
                assert release.wait(timeout=2.0)
                return {"idx": metadata["idx"]}
            finally:
                with self.lock:
                    self.active -= 1

        def release_raw_responses(self, _identifier):
            return None

    harness = ProbeHarness()
    agent = ReasoningAgent.__new__(ReasoningAgent)
    agent._harness = harness
    agent._case_gate = BoundedSemaphore(CASE_MAX_CONCURRENCY)
    monkeypatch.setattr(
        user_agent_module,
        "build_public_result",
        lambda _identifier, result: result,
    )

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(agent.solve, "1+1", {"idx": str(index)})
            for index in range(8)
        ]
        assert four_started.wait(timeout=1.0)
        assert harness.active == CASE_MAX_CONCURRENCY
        release.set()
        assert [future.result()["idx"] for future in futures] == [
            str(index) for index in range(8)
        ]

    assert harness.peak == CASE_MAX_CONCURRENCY == 3


def test_model_gate_allows_four_but_never_more_physical_calls():
    release = Event()
    four_started = Event()
    lock = Lock()
    active = 0
    peak = 0
    started = 0

    def model_call():
        nonlocal active, peak, started
        with lock:
            active += 1
            started += 1
            peak = max(peak, active)
            if started == 4:
                four_started.set()
        try:
            assert release.wait(timeout=2.0)
            return "ok"
        finally:
            with lock:
                active -= 1

    gate = ModelCallGate(4)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(gate.call, model_call) for _ in range(8)]
        assert four_started.wait(timeout=1.0)
        assert active == 4
        release.set()
        assert [future.result() for future in futures] == ["ok"] * 8

    assert peak == 4


def test_benchmark_uses_a_rolling_window_and_stops_new_scheduling():
    release = Event()
    four_started = Event()
    stop = Event()
    started: list[str] = []
    lock = Lock()

    def solve(_problem, metadata):
        with lock:
            started.append(metadata["idx"])
            if len(started) == 4:
                four_started.set()
        assert release.wait(timeout=2.0)
        return {
            "final_response": "2",
            "trace": [{"event": "run_completed", "outcome": "primary"}],
        }

    cases = [BenchmarkCase(str(index), "1+1") for index in range(12)]
    with ThreadPoolExecutor(max_workers=1) as controller:
        future = controller.submit(
            run_benchmark,
            cases,
            solve,
            concurrency=4,
            on_record_completed=lambda _record: stop.set(),
            should_stop_scheduling=stop.is_set,
        )
        assert four_started.wait(timeout=1.0)
        assert len(started) == 4
        assert set(started) == {"0", "1", "2", "3"}
        release.set()
        records, _ = future.result()

    assert len(records) == 4
    assert len(started) == 4
    assert set(started) == {"0", "1", "2", "3"}


def test_resume_rejects_a_changed_case_concurrency(tmp_path):
    input_path = tmp_path / "cases.jsonl"
    config_path = tmp_path / "config.json"
    output_dir = tmp_path / "outputs"
    input_path.write_text('{"idx":"1","problem":"1+1"}\n', encoding="utf-8")
    config_path.write_text("{}\n", encoding="utf-8")
    cases = [BenchmarkCase("1", "1+1")]

    CaseRunManifest.prepare(
        cases=cases,
        input_path=input_path,
        config_path=config_path,
        output_dir=output_dir,
        seed=0,
        concurrency=4,
        resume=False,
    )

    with pytest.raises(ValueError, match="concurrency"):
        CaseRunManifest.prepare(
            cases=cases,
            input_path=input_path,
            config_path=config_path,
            output_dir=output_dir,
            seed=0,
            concurrency=1,
            resume=True,
        )
