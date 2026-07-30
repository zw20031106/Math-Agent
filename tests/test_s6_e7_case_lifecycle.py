from __future__ import annotations

from hashlib import sha256
import json
import signal
from types import SimpleNamespace

import pytest

from mathforge.benchmark import BenchmarkCase, run_benchmark
from mathforge.harness.errors import ModelTransportError
from mathforge.output.judge_trace import minimal_judge_trace
from mathforge.runtime import MathForgeHarness
from tests.fake_client import FakeClient
from scripts.run_case_outputs import (
    CaseRunManifest,
    ConsecutiveProviderFailureCircuitBreaker,
    MODEL_PREFLIGHT_L1_MAX_TOKENS,
    MODEL_PREFLIGHT_MAX_TOKENS,
    PerCaseWallClockRunner,
    RUN_MANIFEST_FILENAME,
    RunStopController,
    FastRetryClient,
    _planned_stop_reason,
    build_argument_parser,
    main as runner_main,
    model_http_timeout_seconds,
    validate_case_output,
    verify_model_availability,
    write_case_output,
)


def _paths(tmp_path):
    input_path = tmp_path / "cases.jsonl"
    config_path = tmp_path / "competition.json"
    input_path.write_text(
        '{"idx":"1","problem":"1+1","expected_answer":"2"}\n',
        encoding="utf-8",
    )
    config_path.write_text('{"profile":"test"}\n', encoding="utf-8")
    return input_path, config_path, tmp_path / "outputs"


def _success_record(case: BenchmarkCase):
    harness = MathForgeHarness(FakeClient())
    records, _ = run_benchmark(
        [case],
        harness.solve,
    )
    return records[0]


def test_duplicate_ids_fail_before_any_case_starts():
    calls = []
    cases = [
        BenchmarkCase("duplicate", "1+1"),
        BenchmarkCase("duplicate", "2+2"),
    ]

    with pytest.raises(ValueError, match="duplicate benchmark case IDs"):
        run_benchmark(cases, lambda *_: calls.append(True))

    assert calls == []


def test_manifest_resume_validates_schema_and_bound_output_hash(tmp_path):
    input_path, config_path, output_dir = _paths(tmp_path)
    case = BenchmarkCase("1", "1+1", expected_answer="2")
    remaining, manifest = CaseRunManifest.prepare(
        cases=[case],
        input_path=input_path,
        config_path=config_path,
        output_dir=output_dir,
        seed=7,
        concurrency=1,
        resume=False,
    )
    assert remaining == [case]

    record = _success_record(case)
    output_path = write_case_output(record, output_dir)
    manifest.record(record, output_path)
    summary = manifest.finalize({"case_count": 1})
    public = validate_case_output(output_path, "1")
    internal = json.loads(
        (output_dir / RUN_MANIFEST_FILENAME).read_text(encoding="utf-8")
    )

    assert set(public) == {"id", "status", "final_response", "trace"}
    assert public["status"] == "success"
    assert internal["status"] == "completed"
    assert internal["cases"]["1"]["run_metrics"]["schema_version"] == "1.5"
    assert internal["cases"]["1"]["output_sha256"] == sha256(
        output_path.read_bytes()
    ).hexdigest()
    assert summary["terminal_status_counts"] == {"success": 1}

    remaining, resumed = CaseRunManifest.prepare(
        cases=[case],
        input_path=input_path,
        config_path=config_path,
        output_dir=output_dir,
        seed=7,
        concurrency=1,
        resume=True,
    )
    assert remaining == []
    assert resumed.resumed_case_ids == ["1"]

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    payload["final_response"] = "tampered"
    output_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(
        ValueError,
        match="digest is inconsistent|hash mismatch",
    ):
        CaseRunManifest.prepare(
            cases=[case],
            input_path=input_path,
            config_path=config_path,
            output_dir=output_dir,
            seed=7,
            concurrency=1,
            resume=True,
        )


def test_resume_rejects_invalid_existing_public_schema(tmp_path):
    input_path, config_path, output_dir = _paths(tmp_path)
    output_dir.mkdir()
    (output_dir / "1.json").write_text(
        json.dumps(
            {
                "result": {
                    "id": 1,
                    "status": "success",
                    "final_response": "2",
                    "trace": [],
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="exactly id"):
        CaseRunManifest.prepare(
            cases=[BenchmarkCase("1", "1+1")],
            input_path=input_path,
            config_path=config_path,
            output_dir=output_dir,
            seed=0,
            concurrency=1,
            resume=True,
        )


def test_failed_case_is_a_terminal_atomic_four_field_output(tmp_path):
    output_dir = tmp_path / "outputs"
    runner = PerCaseWallClockRunner(
        lambda *_: (_ for _ in ()).throw(RuntimeError("private failure"))
    )
    records, _ = run_benchmark(
        [BenchmarkCase("failed", "1+1")],
        runner.solve,
        on_record_completed=lambda record: write_case_output(
            record,
            output_dir,
        ),
    )
    path = output_dir / "failed.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert set(payload) == {"id", "status", "final_response", "trace"}
    assert payload["status"] == "failed"
    assert payload["final_response"].strip()
    assert payload["trace"][-1] == {
        **payload["trace"][-1],
        "event": "run_completed",
        "outcome": "error",
        "final_phase": "case_execution_failed",
        "error_code": "case_execution_failed",
    }
    assert records[0].run_metrics.outcome == "error"
    assert not list(output_dir.glob(".*.tmp"))


def _preflight_candidate() -> str:
    return json.dumps(
        {
            "method": "direct-deduction",
            "method_steps": [
                {
                    "step_id": "s1",
                    "kind": "conclusion",
                    "claim_ids": ["c1"],
                    "theorem": "",
                }
            ],
            "solution_text": "Adding one and one gives two.",
            "public_solution_steps": ["Add 1 and 1 to obtain 2."],
            "final_answer": "2",
            "assumptions": [],
            "theorems": [],
            "claims": [
                {
                    "claim_id": "c1",
                    "statement": "1+1=2.",
                    "depends_on": [],
                    "check_type": "reasoning",
                    "importance": "critical",
                }
            ],
            "unresolved_obligations": [],
        }
    )


def test_model_availability_preflight_requires_all_three_levels():
    class EmptyClient:
        def chat(self, **_):
            return ""

    with pytest.raises(RuntimeError, match="preflight"):
        verify_model_availability(EmptyClient())

    class AvailableClient:
        def __init__(self):
            self.calls = []

        def chat(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return '{"status":"ok"}'
            return _preflight_candidate()

    client = AvailableClient()
    report = verify_model_availability(client)
    assert report["status"] == "passed"
    assert [level["level"] for level in report["levels"]] == ["L0", "L1", "L2"]
    assert client.calls[0]["max_tokens"] == MODEL_PREFLIGHT_L1_MAX_TOKENS == 4096
    assert client.calls[1]["max_tokens"] == MODEL_PREFLIGHT_MAX_TOKENS == 8192


def test_model_http_timeout_uses_the_transport_delivery_window():
    config = SimpleNamespace(
        outer_platform_limit_seconds=1200.0,
        hard_deadline_seconds=870.0,
        deterministic_finalize_reserve_seconds=30.0,
    )

    assert model_http_timeout_seconds(config) == 150


def test_local_model_client_does_not_add_a_second_transport_retry(
    monkeypatch,
):
    monkeypatch.setattr(
        "scripts.run_case_outputs.sleep",
        lambda _: None,
    )
    ticks = iter([0.0, 1.0])
    monkeypatch.setattr(
        "scripts.run_case_outputs.perf_counter",
        lambda: next(ticks),
    )

    class FlakyClient:
        def __init__(self):
            self.calls = 0

        def chat(self, **_):
            self.calls += 1
            if self.calls < 2:
                raise RuntimeError("503 server error")
            return "candidate content"

    base = FlakyClient()
    client = FastRetryClient(base)

    with pytest.raises(ModelTransportError) as captured:
        client.chat(messages=[], temperature=0.0, max_tokens=1)
    assert captured.value.code == "provider_5xx"
    assert captured.value.attempts == 1
    assert base.calls == 1


def test_model_client_does_not_retry_a_failure_beyond_the_fast_window(monkeypatch):
    ticks = iter([0.0, 11.0])
    monkeypatch.setattr(
        "scripts.run_case_outputs.perf_counter",
        lambda: next(ticks),
    )

    class FailingClient:
        def __init__(self):
            self.calls = 0

        def chat(self, **_):
            self.calls += 1
            raise RuntimeError("503 server error")

    base = FailingClient()
    client = FastRetryClient(base)

    with pytest.raises(ModelTransportError) as captured:
        client.chat(messages=[], temperature=0.0, max_tokens=1)
    assert captured.value.code == "provider_5xx"
    assert captured.value.attempts == 1
    assert base.calls == 1


def test_model_client_does_not_retry_unknown_failures(monkeypatch):
    ticks = iter([0.0, 0.01])
    monkeypatch.setattr(
        "scripts.run_case_outputs.perf_counter",
        lambda: next(ticks),
    )

    class FailingClient:
        def __init__(self):
            self.calls = 0

        def chat(self, **_):
            self.calls += 1
            raise RuntimeError("private opaque failure")

    base = FailingClient()
    with pytest.raises(ModelTransportError) as captured:
        FastRetryClient(base).chat(
            messages=[],
            temperature=0.0,
            max_tokens=1,
        )
    assert captured.value.code == "unknown_provider_failure"
    assert base.calls == 1


def _failure_record(reason: str):
    records, _ = run_benchmark(
        [BenchmarkCase(f"failure-{reason}", "1+1")],
        lambda *_: {
            "final_response": "Unable to complete.",
            "trace": [
                {
                    "event": "candidate_generation_failed",
                    "candidate_id": "primary-1",
                    "reason": reason,
                },
                {"event": "run_completed", "outcome": "fallback"},
            ],
        },
    )
    return records[0]


def test_provider_circuit_opens_after_threshold_and_success_resets_it():
    breaker = ConsecutiveProviderFailureCircuitBreaker(3)
    assert not breaker.observe(_failure_record("provider_5xx"))
    assert not breaker.observe(_failure_record("network_read_timeout"))
    assert breaker.observe(_failure_record("empty_response"))
    assert breaker.to_dict()["opened"] is True

    assert not breaker.observe(_success_record(BenchmarkCase("ok", "1+1")))
    assert breaker.to_dict()["consecutive_failures"] == 0


def test_manifest_persists_preflight_and_provider_circuit_state(tmp_path):
    input_path, config_path, output_dir = _paths(tmp_path)
    _, manifest = CaseRunManifest.prepare(
        cases=[BenchmarkCase("1", "1+1")],
        input_path=input_path,
        config_path=config_path,
        output_dir=output_dir,
        seed=0,
        concurrency=1,
        resume=False,
    )
    preflight = {
        "schema_version": "1.0",
        "status": "passed",
        "failed_level": "",
        "levels": [
            {"level": "L0", "status": "passed"},
            {"level": "L1", "status": "passed"},
            {"level": "L2", "status": "passed"},
        ],
    }
    circuit = {
        "max_consecutive_failures": 3,
        "consecutive_failures": 3,
        "opened": True,
        "last_failure_reasons": ["provider_5xx"],
    }

    manifest.record_preflight(preflight)
    manifest.mark_provider_circuit_open(circuit)
    manifest.finalize({})
    payload = json.loads(
        (output_dir / RUN_MANIFEST_FILENAME).read_text(encoding="utf-8")
    )

    assert payload["preflight"] == preflight
    assert payload["status"] == "degraded"
    assert payload["stop_reason"] == "provider_circuit_open"
    assert payload["circuit_breaker"] == circuit


def test_resume_skips_only_success_and_reruns_failed_and_timeout(tmp_path):
    input_path = tmp_path / "cases.jsonl"
    config_path = tmp_path / "competition.json"
    output_dir = tmp_path / "outputs"
    cases = [
        BenchmarkCase("success", "1+1", expected_answer="2"),
        BenchmarkCase("failed", "1+1", expected_answer="2"),
        BenchmarkCase("timeout", "1+1", expected_answer="2"),
    ]
    input_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "idx": case.idx,
                    "problem": case.problem,
                    "expected_answer": case.expected_answer,
                }
            )
            for case in cases
        )
        + "\n",
        encoding="utf-8",
    )
    config_path.write_text('{"profile":"test"}\n', encoding="utf-8")
    _, manifest = CaseRunManifest.prepare(
        cases=cases,
        input_path=input_path,
        config_path=config_path,
        output_dir=output_dir,
        seed=0,
        concurrency=1,
        resume=False,
    )
    records = [
        _success_record(cases[0]),
        run_benchmark(
            [cases[1]],
                lambda *_: {
                    "final_response": "Unable to complete.",
                    "trace": minimal_judge_trace(
                        outcome="fallback",
                        error_code="provider_5xx",
                    ),
                },
        )[0][0],
        run_benchmark(
            [cases[2]],
                lambda *_: {
                    "final_response": "Timed out safely.",
                    "trace": minimal_judge_trace(
                        outcome="timeout",
                        error_code="per_case_wall_clock_exceeded",
                    ),
                },
        )[0][0],
    ]
    for record in records:
        output_path = write_case_output(record, output_dir)
        manifest.record(record, output_path)
    manifest.finalize({})

    remaining, resumed = CaseRunManifest.prepare(
        cases=cases,
        input_path=input_path,
        config_path=config_path,
        output_dir=output_dir,
        seed=0,
        concurrency=1,
        resume=True,
    )

    assert [case.idx for case in remaining] == ["failed", "timeout"]
    assert resumed.resumed_case_ids == ["success"]
    assert resumed.rerun_case_ids == ["failed", "timeout"]
    assert set(resumed.payload["cases"]) == {"success"}
    assert (output_dir / "failed.json").exists()
    assert (output_dir / "timeout.json").exists()


def test_manifest_lifecycle_never_leaves_interruption_as_running(tmp_path):
    input_path, config_path, output_dir = _paths(tmp_path)
    _, manifest = CaseRunManifest.prepare(
        cases=[BenchmarkCase("1", "1+1")],
        input_path=input_path,
        config_path=config_path,
        output_dir=output_dir,
        seed=0,
        concurrency=1,
        resume=False,
    )
    assert manifest.payload["status"] == "created"

    manifest.record_preflight({"status": "passed", "levels": []})
    assert manifest.payload["status"] == "preflight_passed"
    manifest.mark_running()
    assert manifest.payload["status"] == "running"
    manifest.mark_aborted("sigint")
    summary = manifest.finalize({})

    payload = json.loads(manifest.path.read_text(encoding="utf-8"))
    assert payload["status"] == "aborted"
    assert payload["stop_reason"] == "sigint"
    assert payload["ended_at"]
    assert summary["pending_case_count"] == 1


def test_runner_defaults_to_four_and_bounds_case_concurrency():
    parser = build_argument_parser()
    args = parser.parse_args(["--input", "cases.jsonl", "--output-dir", "out"])
    assert args.concurrency == 4
    assert args.rerun_status == frozenset({"failed", "timeout"})
    assert parser.parse_args(
        [
            "--input",
            "cases.jsonl",
            "--output-dir",
            "out",
            "--concurrency",
            "1",
        ]
    ).concurrency == 1

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--input",
                "cases.jsonl",
                "--output-dir",
                "out",
                "--concurrency",
                "5",
            ]
        )


def test_signal_controller_converts_sigint_to_a_safe_stop_request():
    controller = RunStopController()
    previous = signal.getsignal(signal.SIGINT)
    controller.install()
    try:
        installed = signal.getsignal(signal.SIGINT)
        assert callable(installed)
        installed(signal.SIGINT, None)
        assert controller.requested
        assert controller.reason == "sigint"
        assert controller.exit_code == 130
    finally:
        controller.restore()
    assert signal.getsignal(signal.SIGINT) == previous


@pytest.mark.parametrize(
    ("case_id", "executed", "stop_after", "max_cases", "expected"),
    [
        ("2", 2, "2", None, "stop_after_case"),
        ("2", 2, None, 2, "max_cases_reached"),
        ("2", 1, "3", 2, ""),
    ],
)
def test_controlled_stop_is_evaluated_only_after_a_persisted_case(
    case_id,
    executed,
    stop_after,
    max_cases,
    expected,
):
    assert (
        _planned_stop_reason(
            case_id=case_id,
            executed_case_count=executed,
            stop_after_case=stop_after,
            max_cases=max_cases,
        )
        == expected
    )


def test_max_cases_stops_after_atomic_case_write_and_marks_degraded(
    tmp_path,
    monkeypatch,
):
    input_path = tmp_path / "cases.jsonl"
    config_path = tmp_path / "competition.json"
    output_dir = tmp_path / "outputs"
    input_path.write_text(
        '{"idx":"1","problem":"1+1","expected_answer":"2"}\n'
        '{"idx":"2","problem":"1+1","expected_answer":"2"}\n',
        encoding="utf-8",
    )
    config_path.write_text('{"profile":"test"}\n', encoding="utf-8")
    identity = SimpleNamespace(
        requested_model="intern-s2-preview-397b",
        to_dict=lambda: {"requested_model": "intern-s2-preview-397b"},
    )
    config = SimpleNamespace(
        outer_platform_limit_seconds=1200.0,
        hard_deadline_seconds=870.0,
        deterministic_finalize_reserve_seconds=30.0,
    )

    class FakeHarness:
        def __init__(self, *_args, **_kwargs):
            pass

        def solve(self, *_args, **_kwargs):
            return {
                "final_response": "Final answer: 2",
                "trace": [{"event": "run_completed", "outcome": "primary"}],
            }

    base_clients = []

    def build_client(**_kwargs):
        client = SimpleNamespace(chat=lambda **_call: "unused")
        base_clients.append(client)
        return client

    monkeypatch.setattr(
        "scripts.run_case_outputs.exact_model_identity",
        lambda *_args, **_kwargs: identity,
    )
    monkeypatch.setattr(
        "scripts.run_case_outputs.load_benchmark_config",
        lambda _path: config,
    )
    monkeypatch.setattr(
        "scripts.run_case_outputs.InternChatClient",
        build_client,
    )
    monkeypatch.setattr(
        "scripts.run_case_outputs.run_model_preflight",
        lambda *_args, **_kwargs: {
            "schema_version": "1.0",
            "status": "passed",
            "failed_level": "",
            "levels": [],
        },
    )
    monkeypatch.setattr(
        "scripts.run_case_outputs.MathForgeHarness",
        FakeHarness,
    )

    assert (
        runner_main(
            [
                "--input",
                str(input_path),
                "--output-dir",
                str(output_dir),
                "--config",
                str(config_path),
                "--max-cases",
                "1",
            ]
        )
        == 0
    )

    assert (output_dir / "1.json").exists()
    assert not (output_dir / "2.json").exists()
    assert base_clients[0].model == "intern-s2-preview-397b"
    assert set(
        json.loads((output_dir / "1.json").read_text(encoding="utf-8"))
    ) == {"id", "status", "final_response", "trace"}
    manifest = json.loads(
        (output_dir / RUN_MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    assert manifest["status"] == "degraded"
    assert manifest["stop_reason"] == "max_cases_reached"
    assert manifest["summary"]["pending_case_count"] == 1
