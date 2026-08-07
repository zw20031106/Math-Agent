from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Barrier, Lock

from mathforge.agents.router_planner import RouterRuleEngine
from mathforge.agents.solver import PrimarySolver, SolverExecutor, SolverRequest
from mathforge.harness.budget import CallBudget
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.harness.trace import TraceBuilder
from mathforge.harness.trace_journal import TraceJournalFactory
from mathforge.output.judge_trace import _proof_summary
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.parsing.solution_parser import SolutionParser
from mathforge.agents.verifier import SkepticFinding
from mathforge.verification.repair_scope import (
    actionable_verifier_failures,
)
from mathforge.verification.proof_obligations import ProofObligationEngine
from scripts.run_case_outputs import (
    CaseRunManifest,
    FastRetryClient,
    build_argument_parser,
)
from mathforge.benchmark import BenchmarkCase


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "phase0_0729_live_regressions.json"
)


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _candidate_replay(case_id: str) -> dict:
    return next(
        item
        for item in _fixture()["candidate_replays"]
        if item["case_id"] == case_id
    )


def test_sanitized_live_fixture_preserves_regression_evidence_without_secrets():
    payload = _fixture()
    serialized = json.dumps(payload, ensure_ascii=False)

    assert payload["contains_raw_private_reasoning"] is False
    assert payload["contains_credentials"] is False
    assert [case["status"] for case in payload["cases"][:4]] == [
        "success",
        "failed",
        "success",
        "failed",
    ]
    assert payload["cases"][1]["root_failure"] == "network_connect_failure"
    assert payload["cases"][2]["proof_obligation_count"] == 0
    assert "sk-" not in serialized
    assert "Authorization" not in serialized
    assert "D:\\" not in serialized


def test_captured_candidate_replays_remain_strictly_parseable():
    parser = SolutionParser()
    for replay in _fixture()["candidate_replays"]:
        candidate = parser.parse(
            json.dumps(replay["response"], ensure_ascii=False),
            candidate_id=f"replay-{replay['case_id']}",
            role="PrimarySolver",
            answer_type=replay["answer_type"],
        )
        assert candidate.parse_status == "strict_json"
        assert candidate.final_answer.strip()
        assert candidate.public_solution_steps


def test_primary_transport_failure_uses_the_reserved_recovery_call():
    replay = _candidate_replay("0")

    class FailThenSucceedClient:
        def __init__(self):
            self.calls = 0

        def chat(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("503 server error")
            return json.dumps(replay["response"], ensure_ascii=False)

    client = FailThenSucceedClient()
    provider = OfficialClientProvider(client, ModelCallGate(1))
    executor = SolverExecutor(provider, SolutionParser())
    problem = ProblemParser().parse(replay["problem"])
    route = RouterRuleEngine().plan(problem)
    request = SolverRequest(
        candidate_id="primary-1",
        problem=problem,
        route=route,
        skill_context="",
        method_family=replay["response"]["method"],
    )

    candidate = executor.execute(
        PrimarySolver(),
        request,
        CallBudget(max_calls=2),
        temperature=0.0,
        max_tokens=8192,
    )

    assert client.calls == 2
    assert candidate.final_answer == "-1/4"


def test_case_runner_accepts_and_defaults_to_concurrency_three():
    parser = build_argument_parser()
    default_args = parser.parse_args(
        ["--input", "cases.jsonl", "--output-dir", "out"]
    )
    explicit_args = parser.parse_args(
        [
            "--input",
            "cases.jsonl",
            "--output-dir",
            "out",
            "--concurrency",
            "3",
        ]
    )

    assert default_args.concurrency == 3
    assert explicit_args.concurrency == 3


def test_local_retry_wrapper_does_not_serialize_independent_model_calls():
    barrier = Barrier(2)

    class ConcurrentProbeClient:
        def __init__(self):
            self.active = 0
            self.peak = 0
            self.lock = Lock()

        def chat(self, **_kwargs):
            with self.lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
            try:
                barrier.wait(timeout=1.0)
                return "ok"
            finally:
                with self.lock:
                    self.active -= 1

    base = ConcurrentProbeClient()
    client = FastRetryClient(base, max_attempts=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                client.chat,
                messages=[],
                temperature=0.0,
                max_tokens=1,
            )
            for _ in range(2)
        ]
        assert [future.result() for future in futures] == ["ok", "ok"]

    assert base.peak == 2


def test_no_selected_candidate_cannot_be_reported_as_proof_complete():
    summary = _proof_summary(None, None, selected_candidate_id="")
    assert summary["status"] == "not_available"


def test_trace_redaction_preserves_latex_commands_after_matched_prefix():
    trace = TraceBuilder([], max_chars=0, max_events=0)
    reasons = [
        r"advanced-real-analysis:matched:\int",
        r"set-membership:matched:\in",
        r"limit-analysis:matched:\lim",
    ]
    trace.add("route_planned", routing_reasons=reasons)

    event = trace.internal_events[-1]
    assert event["routing_reasons"] == reasons


def test_trace_redaction_still_removes_real_windows_absolute_paths():
    trace = TraceBuilder([], max_chars=0, max_events=0)
    trace.add("route_planned", source_path=r"D:\private\answer.txt")
    assert trace.internal_events[-1]["source_path"] == "[local-path]"


def test_proof_obligations_are_inferred_from_candidate_operations():
    replay = _candidate_replay("2")
    problem = ProblemParser().parse(replay["problem"])
    candidate = SolutionParser().parse(
        json.dumps(replay["response"], ensure_ascii=False),
        candidate_id="primary-1",
        role="PrimarySolver",
        answer_type=replay["answer_type"],
    )

    obligations = ProofObligationEngine().generate(problem, candidate)
    kinds = {item.kind for item in obligations}
    assert {"interchange", "theorem_preconditions"} <= kinds


def test_only_actionable_verifier_failures_trigger_repair():
    findings = [
        SkepticFinding("c", "claim-1", [], "unknown", "uncertain"),
        SkepticFinding("c", "claim-2", [], "fail", ""),
        SkepticFinding(
            "c",
            "claim-3",
            [],
            "fail",
            "counterexample found",
        ),
    ]
    assert actionable_verifier_failures(findings) == {
        "c": ["claim-3"]
    }


def test_trace_journal_factory_preserves_previous_attempt(tmp_path):
    first_factory = TraceJournalFactory(
        tmp_path,
        attempt_id="attempt-0001",
    )
    first = first_factory("session-1", {"idx": "case-1"})
    first({"event": "first-attempt"})
    second_factory = TraceJournalFactory(
        tmp_path,
        attempt_id="attempt-0002",
    )
    second = second_factory("session-2", {"idx": "case-1"})
    second({"event": "second-attempt"})

    journals = [
        tmp_path / "attempt-0001" / "case-1.trace.jsonl",
        tmp_path / "attempt-0002" / "case-1.trace.jsonl",
    ]
    events = [
        json.loads(journal.read_text(encoding="utf-8"))["trace_event"][
            "event"
        ]
        for journal in journals
    ]
    assert events == ["first-attempt", "second-attempt"]


def test_resume_marks_a_stale_running_attempt_as_interrupted(tmp_path):
    input_path = tmp_path / "cases.jsonl"
    config_path = tmp_path / "competition.json"
    output_dir = tmp_path / "outputs"
    input_path.write_text(
        '{"idx":"1","problem":"1+1","expected_answer":"2"}\n',
        encoding="utf-8",
    )
    config_path.write_text('{"profile":"test"}\n', encoding="utf-8")
    case = BenchmarkCase("1", "1+1", expected_answer="2")
    _, manifest = CaseRunManifest.prepare(
        cases=[case],
        input_path=input_path,
        config_path=config_path,
        output_dir=output_dir,
        seed=0,
        concurrency=1,
        resume=False,
    )
    manifest.record_preflight({"status": "passed", "levels": []})
    manifest.mark_running()

    _, resumed = CaseRunManifest.prepare(
        cases=[case],
        input_path=input_path,
        config_path=config_path,
        output_dir=output_dir,
        seed=0,
        concurrency=1,
        resume=True,
    )

    assert resumed.payload["attempts"][-2]["status"] == "interrupted"
