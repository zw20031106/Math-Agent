from hashlib import sha256
import json

from mathforge.config import HarnessConfig
from scripts.run_benchmark import BENCHMARK_SCHEMA_VERSION, build_benchmark_metadata


def test_benchmark_metadata_hashes_exact_inputs(tmp_path):
    dataset = tmp_path / "cases.jsonl"
    config = tmp_path / "config.json"
    dataset.write_text('{"problem":"1+1"}\n', encoding="utf-8")
    configured = HarnessConfig(profile="test", status="candidate-unvalidated")
    config.write_text(json.dumps(configured.to_dict()), encoding="utf-8")

    metadata = build_benchmark_metadata(dataset, config)

    assert metadata["benchmark_schema_version"] == BENCHMARK_SCHEMA_VERSION
    assert metadata["dataset_sha256"] == sha256(dataset.read_bytes()).hexdigest()
    assert metadata["config_sha256"] == configured.fingerprint
    assert metadata["config_schema_version"] == HarnessConfig.SCHEMA_VERSION
    assert metadata["config_status"] == "candidate-unvalidated"
    assert len(metadata["prompt_sha256"]) == 64
    assert len(metadata["skill_sha256"]) == 64
    assert len(metadata["rag_sha256"]) == 64
    assert len(metadata["tool_sha256"]) == 64
    assert metadata["git_commit"]
