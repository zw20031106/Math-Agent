from __future__ import annotations

import pytest

from mathforge.harness.schemas import ProblemIR, SchemaValidationError
from mathforge.parsing.problem_parser import ProblemParser


@pytest.mark.parametrize(
    "problem",
    [
        "计算 $1+1$。",
        r"填空：$1+1=\_\_\_\_$。",
        "判断命题 $1<2$ 是否正确。",
        "Which of the following is correct?\n(A) 1\n(B) 2",
        r"简答：$\sqrt{4}$ 等于多少？",
    ],
)
def test_direct_answer_questions_use_answer_only(problem):
    assert ProblemParser().parse(problem).response_mode == "answer_only"


@pytest.mark.parametrize(
    "problem",
    [
        r"证明：对任意实数 $x$，都有 $x^2\ge 0$。",
        "Prove that there are infinitely many primes.",
        "Show that $n^2+n$ is even for every integer $n$.",
    ],
)
def test_proof_requests_use_full_proof(problem):
    parsed = ProblemParser().parse(problem)
    assert parsed.problem_type == "proof"
    assert parsed.response_mode == "proof_full"


@pytest.mark.parametrize(
    "problem",
    [
        "计算该积分并写出过程。",
        "推导二次方程的求根公式。",
        "Explain why the sequence converges.",
        "Calculate $1+1$ and show your work.",
    ],
)
def test_explicit_exposition_requests_use_worked_solution(problem):
    assert ProblemParser().parse(problem).response_mode == "worked_solution"


def test_valid_metadata_takes_precedence_without_an_extra_model_call():
    parsed = ProblemParser().parse(
        "Compute $1+1$.",
        metadata={
            "problem_type": "proof",
            "answer_type": "text",
            "response_mode": "proof_full",
        },
    )
    assert parsed.problem_type == "proof"
    assert parsed.answer_type == "text"
    assert parsed.response_mode == "proof_full"
    assert parsed.answer_type_confidence == 1.0


def test_problem_ir_response_mode_round_trips_and_rejects_unknown_modes():
    problem = ProblemParser().parse("Compute $1+1$.")
    restored = ProblemIR.from_dict(problem.to_dict())
    assert restored.response_mode == "answer_only"
    assert restored.schema_version == "2.1"

    payload = problem.to_dict()
    payload["response_mode"] = "verbose"
    with pytest.raises(SchemaValidationError, match="invalid response mode"):
        ProblemIR.from_dict(payload)
