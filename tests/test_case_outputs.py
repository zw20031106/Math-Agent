from __future__ import annotations

import json
from threading import Event, Thread

from mathforge.benchmark import BenchmarkCase, run_benchmark
from scripts.run_case_outputs import write_case_output


def test_case_output_has_exact_flat_contract_and_atomic_filename(tmp_path):
    records, _ = run_benchmark(
        [BenchmarkCase("7", "1 + 1")],
        lambda *_: {
            "final_response": "Final answer: 2",
            "trace": [{"event": "run_completed", "outcome": "success"}],
        },
    )

    path = write_case_output(records[0], tmp_path)

    assert path == tmp_path / "7.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "id": 7,
        "status": "success",
        "final_response": "Final answer: 2",
        "trace": [{"event": "run_completed", "outcome": "success"}],
    }
    assert not list(tmp_path.glob(".*.tmp"))


def test_completed_case_is_written_before_a_slow_peer_finishes(tmp_path):
    release_slow_case = Event()
    fast_case_written = Event()
    run_finished = Event()

    def solve(problem, _metadata):
        if problem == "slow":
            assert release_slow_case.wait(2)
        return {
            "final_response": f"Final answer: {problem}",
            "trace": [{"event": "run_completed", "outcome": "success"}],
        }

    def on_record_completed(record):
        write_case_output(record, tmp_path)
        if record.case.idx == "2":
            fast_case_written.set()

    def run():
        try:
            run_benchmark(
                [
                    BenchmarkCase("1", "slow"),
                    BenchmarkCase("2", "fast"),
                ],
                solve,
                concurrency=2,
                on_record_completed=on_record_completed,
            )
        finally:
            run_finished.set()

    worker = Thread(target=run)
    worker.start()
    try:
        assert fast_case_written.wait(1)
        assert (tmp_path / "2.json").exists()
        assert not run_finished.is_set()
    finally:
        release_slow_case.set()
        worker.join(timeout=3)
    assert run_finished.is_set()
    assert (tmp_path / "1.json").exists()
