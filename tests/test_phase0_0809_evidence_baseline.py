from __future__ import annotations

import json
from pathlib import Path

from mathforge.evaluation.evidence_baseline import (
    aggregate_local_final_corpus,
    parse_official_evaluation_log,
    sha256_file,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "data" / "evidence"


def test_final_corpus_reproduces_local_88_gate() -> None:
    payload = json.loads(
        (EVIDENCE / "local88" / "final_corpus.json").read_text(encoding="utf-8")
    )
    metrics = aggregate_local_final_corpus(payload["corpus_records"])

    assert metrics == payload["corpus_metrics"]
    assert metrics["case_count"] == 88
    assert metrics["correct_count"] == 49
    assert metrics["status_counts"] == {"failed": 38, "success": 50}
    assert metrics["error_code_counts"]["all_candidates_failed"] == 38
    assert metrics["router_llm_accepted_count"] == 0
    assert metrics["dual_candidate_count"] == 10
    assert [item["case_count"] for item in payload["attempt_metrics"]] != [88]


def test_official_log_reproduces_112_gate() -> None:
    summary = json.loads(
        (EVIDENCE / "official112" / "summary.json").read_text(encoding="utf-8")
    )
    log_path = EVIDENCE / "official112" / summary["source_log"]
    metrics = parse_official_evaluation_log(log_path.read_text(encoding="utf-8"))

    assert metrics == summary["metrics"]
    assert metrics["case_count"] == 112
    assert metrics["invalid"] == 92
    assert metrics["request_count"] == 657
    assert metrics["truncated_count"] == 444
    assert sha256_file(log_path) == summary["source_log_sha256"]


def test_baseline_manifest_hashes_every_frozen_artifact() -> None:
    manifest = json.loads(
        (EVIDENCE / "baseline_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["metric_authority"] == {
        "attempt_metrics": "diagnostic_only",
        "corpus_metrics": "one_final_record_per_case",
    }
    assert manifest["privacy"] == {
        "contains_credentials": False,
        "contains_absolute_paths": False,
        "contains_private_reasoning_transcripts": False,
    }
    for artifact in manifest["artifacts"]:
        path = ROOT / artifact["path"]
        assert path.stat().st_size == artifact["bytes"]
        assert sha256_file(path) == artifact["sha256"]


def test_id_7_and_id_77_regressions_are_redacted_and_frozen() -> None:
    payload = json.loads(
        (EVIDENCE / "local88" / "regression_cases.json").read_text(
            encoding="utf-8"
        )
    )
    cases = {item["id"]: item for item in payload["cases"]}
    assert set(cases) == {7, 77}
    assert cases[7]["status"] == "failed"
    assert cases[7]["error_code"] == "all_candidates_failed"
    assert cases[77]["status"] == "success"
    assert all(
        item["privacy"] == "redacted_public_diagnostics_only"
        for item in cases.values()
    )
    assert "trace" not in cases[7]
