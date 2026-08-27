from __future__ import annotations

from mathforge.evaluation.failure_attribution import (
    PRIMARY_FAILURE_CAUSES,
    FailureAttribution,
    aggregate_failure_attribution,
    attribute_failure,
    validate_failure_attributions,
)


def test_primary_failure_taxonomy_is_unique_and_stable():
    assert len(PRIMARY_FAILURE_CAUSES) == 18
    assert len(set(PRIMARY_FAILURE_CAUSES)) == len(PRIMARY_FAILURE_CAUSES)
    assert all(cause.isupper() for cause in PRIMARY_FAILURE_CAUSES)


def test_failed_case_gets_one_primary_and_optional_secondary_causes():
    attribution = attribute_failure(
        {
            "status": "failed",
            "trace": [
                {"event": "problem_parse_failed"},
                {"event": "trace_invalid"},
            ],
        }
    )
    assert attribution.primary_cause == "PARSER_ERROR"
    assert attribution.secondary_causes == ("TRACE_CONTRACT_ERROR",)


def test_incorrect_answer_defaults_to_reasoning_error_and_timeout_is_explicit():
    incorrect = attribute_failure(
        {
            "score": {"scored": True, "correct": False, "reason": "mismatch"},
            "result": {"final_response": "3", "trace": []},
        }
    )
    assert incorrect.primary_cause == "REASONING_ERROR"

    timeout = attribute_failure(
        {
            "run_metrics": {
                "outcome": "timeout",
                "error_code": "per_case_wall_clock_exceeded",
            },
            "result": {"trace": [{"event": "per_case_wall_clock_timeout"}]},
        }
    )
    assert timeout.primary_cause == "TIMEOUT"


def test_aggregate_preserves_primary_totals_and_validates_expected_count():
    items = [
        FailureAttribution("PARSER_ERROR"),
        FailureAttribution("REASONING_ERROR", ("ARBITRATION_ERROR",)),
        FailureAttribution(None),
    ]
    summary = aggregate_failure_attribution(items)
    assert summary["case_count"] == 3
    assert summary["failed_or_incorrect_count"] == 2
    assert summary["primary_total"] == 2
    assert summary["primary_counts"] == {
        "PARSER_ERROR": 1,
        "REASONING_ERROR": 1,
    }
    assert summary["secondary_counts"] == {"ARBITRATION_ERROR": 1}
    assert validate_failure_attributions(items, expected_failed_count=2) == []
