from scripts.validate_submission import validate


def test_submission_validator_passes_repository():
    assert validate() == []
