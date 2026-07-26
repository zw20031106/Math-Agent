from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from mathforge.evaluation.evidence_registry import (
    evidence_tree_fingerprint,
    load_evidence_registry,
    validate_evidence_registry,
    validate_registered_trees,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "data" / "evaluation_evidence_registry.json"


def test_phase0_registry_explicitly_rejects_all_historical_evidence():
    registry = load_evidence_registry(REGISTRY_PATH)

    assert validate_evidence_registry(registry) == []
    assert registry["policy"] == "explicit-allow"
    assert registry["active_baseline_id"] is None
    assert registry["entries"]
    assert all(not entry["eligible_for_baseline"] for entry in registry["entries"])
    assert all(entry["reasons"] for entry in registry["entries"])


def test_registry_cannot_activate_ineligible_or_wrong_model_evidence():
    registry = load_evidence_registry(REGISTRY_PATH)
    rejected = deepcopy(registry)
    rejected["active_baseline_id"] = rejected["entries"][0]["id"]
    assert "active_baseline_id must reference eligible evidence" in validate_evidence_registry(
        rejected
    )

    wrong_model = deepcopy(registry)
    entry = wrong_model["entries"][2]
    entry["classification"] = "eligible-baseline"
    entry["eligible_for_baseline"] = True
    entry["reasons"] = []
    entry["manifest_status"] = "completed"
    entry["requested_model"] = "intern-s2-preview"
    wrong_model["active_baseline_id"] = entry["id"]
    errors = validate_evidence_registry(wrong_model)
    assert "evidence registry entry 2 eligible evidence uses the wrong model" in errors


def test_registered_tree_fingerprint_detects_content_changes(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "0.json").write_text('{"id":0}\n', encoding="utf-8")
    file_count, fingerprint = evidence_tree_fingerprint(evidence)
    registry = {
        "entries": [
            {
                "id": "fixture",
                "relative_path": "evidence",
                "file_count": file_count,
                "tree_sha256": fingerprint,
            }
        ]
    }

    assert validate_registered_trees(registry, tmp_path) == []
    (evidence / "0.json").write_text('{"id":1}\n', encoding="utf-8")
    assert validate_registered_trees(registry, tmp_path) == [
        "registered evidence fingerprint mismatch: fixture"
    ]


def test_registry_rejects_absolute_or_parent_relative_evidence_paths():
    registry = load_evidence_registry(REGISTRY_PATH)
    for unsafe in ("../outside", "C:/outside", "folder\\outside"):
        changed = deepcopy(registry)
        changed["entries"][0]["relative_path"] = unsafe
        assert "evidence registry entry 0 relative_path is invalid" in (
            validate_evidence_registry(changed)
        )
