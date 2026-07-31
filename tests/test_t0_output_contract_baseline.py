from __future__ import annotations

import json
from pathlib import Path

from scripts.profile_public_output_contract import profile_public_output_contract


def _write_case(path: Path, identifier: int, *, success: bool) -> None:
    payload = {
        "id": identifier,
        "status": "success" if success else "failed",
        "final_response": "Work.\n\nFinal answer: $2$",
        "trace": [
            {"event": "session_started"},
            {
                "event": "candidate_summaries",
                "candidates": [
                    {
                        "public_solution_steps": ["Compute $1+1$."],
                        "public_final_answer": "2",
                    }
                ],
            },
            {"event": "run_completed"},
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_output_contract_profile_is_deterministic_and_path_safe(tmp_path):
    run_dir = tmp_path / "live-run"
    run_dir.mkdir()
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text('{"problem":"1+1","answer":"2"}\n', encoding="utf-8")
    _write_case(run_dir / "0.json", 0, success=True)
    _write_case(run_dir / "1.json", 1, success=False)

    first = profile_public_output_contract(
        run_dir,
        dataset_path=dataset,
        expected_cases=2,
    )
    second = profile_public_output_contract(
        run_dir,
        dataset_path=dataset,
        expected_cases=2,
    )

    assert first == second
    assert first["source"]["run"] == "<external>/live-run"
    assert str(tmp_path) not in json.dumps(first)
    assert first["coverage"]["public_contract_valid_cases"] == 2
    assert first["coverage"]["status_counts"] == {"failed": 1, "success": 1}
    assert first["trace"]["candidate_content_cases"] == 2
    assert first["trace"]["first_event_counts"] == {"session_started": 2}
