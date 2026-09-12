from __future__ import annotations

import pytest

from mathforge.skills.evaluation import skill_benchmark_coverage
from mathforge.skills.s5_benchmark import (
    S5_CASE_TYPES,
    S5_SKILL_NAMES,
    evaluate_s5_ablation,
    load_s5_cases,
    run_selection_benchmark,
)


def test_s5_corpus_covers_every_modified_skill_and_case_type():
    cases = load_s5_cases()
    assert len(cases) == len(S5_SKILL_NAMES) * len(S5_CASE_TYPES)
    assert {case.skill_name for case in cases} == set(S5_SKILL_NAMES)
    coverage = skill_benchmark_coverage(cases, skill_names=S5_SKILL_NAMES)
    assert len(coverage) == len(S5_SKILL_NAMES)
    assert all(item.complete for item in coverage)
    assert all(
        item.case_counts[case_type] == 1
        for item in coverage
        for case_type in S5_CASE_TYPES
    )


def test_s5_selection_audit_is_deterministic_and_exposes_top_k_gaps():
    cases = load_s5_cases()
    first = run_selection_benchmark(cases).to_dict()
    second = run_selection_benchmark(cases).to_dict()

    assert first == second
    assert first["case_count"] == 110
    assert 0.0 < first["selection_pass_rate"] <= 1.0
    assert first["negative_deprioritization_rate"] == 1.0
    assert all(
        set(value) == {"total", "passed"}
        for value in first["skill_counts"].values()
    )


def test_s5_ablation_is_blocked_without_real_rows_and_accepts_observed_pairs():
    cases = load_s5_cases()
    pending = evaluate_s5_ablation(cases)
    assert pending["status"] == "pending_real_runs"
    assert pending["accuracy_claim"] == "blocked"
    assert pending["required_row_count"] == 220

    rows = []
    for case in cases:
        rows.extend(
            [
                {
                    "case_id": case.case_id,
                    "skill_enabled": True,
                    "actual": "1",
                    "expected_answer": "1",
                    "answer_type": "integer",
                    "tokens": 10,
                },
                {
                    "case_id": case.case_id,
                    "skill_enabled": False,
                    "actual": "1",
                    "expected_answer": "1",
                    "answer_type": "integer",
                    "tokens": 0,
                },
            ]
        )
    observed = evaluate_s5_ablation(cases, rows)
    assert observed["status"] == "observed_paired_runs"
    assert observed["report"]["ablation"]["pair_count"] == 110
    assert observed["report"]["ablation"]["accuracy_delta"] == 0.0


def test_s5_ablation_rejects_manual_correctness_and_case_id_drift():
    cases = load_s5_cases()
    rows = [
        {
            "case_id": cases[0].case_id,
            "skill_enabled": True,
            "skill_on_correct": True,
        }
    ]
    with pytest.raises(ValueError, match="case IDs mismatch"):
        evaluate_s5_ablation(cases, rows)

    complete_rows = []
    for case in cases:
        complete_rows.extend(
            [
                {
                    "case_id": case.case_id,
                    "skill_enabled": True,
                    "actual": "1",
                    "expected_answer": "1",
                    "answer_type": "integer",
                    "skill_on_correct": True,
                },
                {
                    "case_id": case.case_id,
                    "skill_enabled": False,
                    "actual": "1",
                    "expected_answer": "1",
                    "answer_type": "integer",
                },
            ]
        )
    with pytest.raises(ValueError, match="manual skill_on_correct"):
        evaluate_s5_ablation(cases, complete_rows)
