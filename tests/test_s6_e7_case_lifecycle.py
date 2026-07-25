from __future__ import annotations

from hashlib import sha256
import json

import pytest

from mathforge.benchmark import BenchmarkCase, run_benchmark
from scripts.run_case_outputs import (
    CaseRunManifest,
    PerCaseWallClockRunner,
    RUN_MANIFEST_FILENAME,
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
    records, _ = run_benchmark(
        [case],
        lambda *_: {
            "final_response": "Final answer: 2",
            "trace": [{"event": "run_completed", "outcome": "primary"}],
        },
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
    assert internal["cases"]["1"]["run_metrics"]["schema_version"] == "1.2"
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
        concurrency=4,
        resume=True,
    )
    assert remaining == []
    assert resumed.resumed_case_ids == ["1"]

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    payload["final_response"] = "tampered"
    output_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
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


def test_model_availability_preflight_requires_non_empty_content():
    class EmptyClient:
        def chat(self, **_):
            return ""

    with pytest.raises(RuntimeError, match="preflight"):
        verify_model_availability(EmptyClient())

    client = type(
        "AvailableClient",
        (),
        {"chat": lambda self, **_: "OK"},
    )()
    verify_model_availability(client)
