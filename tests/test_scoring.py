from mathforge.evaluation.scoring import score_response


def test_expression_scorer_uses_symbolic_equivalence():
    result = score_response(
        "x^2+2*x+1",
        "Final answer: (x+1)^2",
        answer_type="expression",
    )
    assert result.scored is True
    assert result.correct is True
    assert result.reason == "symbolic_equivalent"


def test_set_scorer_is_order_independent_but_not_substring_based():
    equivalent = score_response("{1,2}", "Answer: {2,1}", answer_type="set")
    unequal = score_response("{1,2}", "Answer: {12}", answer_type="set")
    assert equivalent.correct is True
    assert unequal.correct is False


def test_proof_text_requires_an_explicit_scorer():
    manual = score_response("QED", "Final answer: QED", answer_type="text")
    exact = score_response("QED", "Final answer: QED", answer_type="text", scorer="exact")
    assert manual.scored is False
    assert manual.correct is None
    assert exact.correct is True


def test_invalid_reference_answer_is_a_scoring_failure_not_model_error():
    result = score_response("not-an-integer", "Answer: 2", answer_type="integer")
    assert result.scored is False
    assert result.error is True
