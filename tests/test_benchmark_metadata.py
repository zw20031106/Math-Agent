from hashlib import sha256
import json

from scripts.run_benchmark import BENCHMARK_SCHEMA_VERSION, build_benchmark_metadata


def test_benchmark_metadata_hashes_exact_inputs(tmp_path):
    dataset = tmp_path / "cases.jsonl"
    config = tmp_path / "config.json"
    dataset.write_text('{"problem":"1+1"}\n', encoding="utf-8")
    config.write_text(json.dumps({"status": "candidate-unvalidated"}), encoding="utf-8")

    metadata = build_benchmark_metadata(dataset, config)

    assert metadata["benchmark_schema_version"] == BENCHMARK_SCHEMA_VERSION
    assert metadata["dataset_sha256"] == sha256(dataset.read_bytes()).hexdigest()
    assert metadata["config_sha256"] == sha256(config.read_bytes()).hexdigest()
    assert metadata["config_status"] == "candidate-unvalidated"
    assert metadata["git_commit"]
