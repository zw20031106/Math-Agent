from __future__ import annotations

from mathforge.harness.schemas import CandidateSolution
from mathforge.output.deterministic_formatter import DeterministicFormatter
from mathforge.output.official_trace import validate_official_trace
from mathforge.parsing.problem_parser import ProblemParser
from tests.fake_client import FakeClient
from user_agent import ReasoningAgent


def _candidate(answer: str, solution: str) -> CandidateSolution:
    return CandidateSolution(
        "candidate",
        "PrimarySolver",
        "direct-deduction",
        answer,
        "expression",
        public_solution_steps=[solution],
        solution_text=solution,
    )


def test_non_proof_final_response_is_only_the_exact_answer() -> None:
    problem = ProblemParser().parse(
        "\u8ba1\u7b97 $1+1$ \u5e76\u5199\u51fa\u8fc7\u7a0b\u3002"
    )

    rendered = DeterministicFormatter().format(
        _candidate(
            "2",
            "\u7531 $1+1=2$ \u53ef\u5f97\u7ed3\u679c\u3002",
        ),
        problem,
    )

    assert problem.response_mode == "worked_solution"
    assert rendered == "2"


def test_proof_final_response_keeps_public_proof_and_exact_conclusion() -> None:
    problem = ProblemParser().parse(
        "\u8bc1\u660e\uff1a\u5bf9\u4efb\u610f\u5b9e\u6570 x\uff0c\u90fd\u6709 x^2 >= 0\u3002"
    )
    proof = (
        "\u8bbe x \u4e3a\u4efb\u610f\u5b9e\u6570\u3002"
        "\u5b9e\u6570\u5e73\u65b9\u975e\u8d1f\uff0c\u56e0\u6b64 x^2 >= 0\u3002"
    )

    rendered = DeterministicFormatter().format(
        _candidate("\u547d\u9898\u6210\u7acb", proof),
        problem,
    )

    assert problem.response_mode == "proof_full"
    assert rendered == f"{proof}\n\n\u547d\u9898\u6210\u7acb"


def test_public_trace_is_a_compact_public_reasoning_chain() -> None:
    result = ReasoningAgent(FakeClient()).solve("Compute 1+1.", {"idx": 1})

    validate_official_trace(result["trace"])
    assert all(set(item) == {"step", "content"} for item in result["trace"])
    steps = [item["step"] for item in result["trace"]]
    assert steps[0] == "plan"
    assert "reasoning" in steps
    assert "verification" in steps
    assert "arbitration" in steps
    assert "model_call" in steps
    assert steps[-1] == "finalize"
    assert all(item["content"].strip() for item in result["trace"])
