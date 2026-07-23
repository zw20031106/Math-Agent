from scripts.validate_submission import validate, validation_warnings


def test_submission_validator_passes_repository():
    assert validate() == []


def test_submission_validator_does_not_report_candidate_config_as_frozen():
    assert validation_warnings() == [
        "WARNING: competition config is candidate-unvalidated; "
        "benchmark evidence has not frozen it.",
        "WARNING: mathematical content has engineering review only; "
        "human signatures are still required before freezing.",
    ]
