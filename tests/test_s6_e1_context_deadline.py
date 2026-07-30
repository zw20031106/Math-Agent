from __future__ import annotations

from dataclasses import replace
import json
from threading import Event
from time import perf_counter

import pytest

from mathforge.benchmark import BenchmarkCase, run_benchmark
from mathforge.config import HarnessConfig, load_competition_config
from mathforge.context.errors import ContextBudgetExceeded
from mathforge.harness.budget import CallBudget
from mathforge.harness.context_budget import (
    INTERN_S2_TOKENIZER_JSON_SHA256,
    INTERN_S2_TOKENIZER_REVISION,
    InternS2TokenCounter,
    ModelContextBudget,
)
from mathforge.harness.deadline import DeadlineController
from mathforge.harness.errors import BudgetExceeded
from mathforge.harness.provider import ModelCallGate, OfficialClientProvider
from mathforge.harness.trace import TraceBuilder
from mathforge.runtime import MathForgeHarness
from scripts.run_case_outputs import PerCaseWallClockRunner, write_case_output


class FixedTokenizer:
    def __init__(self, prompt_tokens: int = 17) -> None:
        self.prompt_tokens = prompt_tokens

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        assert messages
        assert tokenize is True
        assert add_generation_prompt is True
        return list(range(self.prompt_tokens))

    def encode(self, text, *, add_special_tokens):
        assert add_special_tokens is False
        return list(range(len(text)))


class BrokenTokenizer:
    def apply_chat_template(self, *args, **kwargs):
        raise RuntimeError("unavailable")

    def encode(self, *args, **kwargs):
        raise RuntimeError("unavailable")


class RecordingClient:
    def __init__(self, response: str = "ok") -> None:
        self.response = response
        self.calls: list[dict] = []

    def chat(self, *, messages, temperature, max_tokens):
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return self.response


def _messages(content: str = "solve") -> list[dict[str, str]]:
    return [{"role": "user", "content": content}]


def _minimal_config(**changes) -> HarnessConfig:
    return replace(
        HarnessConfig(
            max_model_calls=1,
            enable_router=False,
            enable_skills=False,
            enable_alternatives=False,
            enable_tools=False,
            enable_evidence=False,
            enable_proof_obligations=False,
            enable_verifier=False,
            enable_memory=False,
            enable_lemma_loop=False,
            enable_rag=False,
            enable_repair=False,
            enable_finalizer=False,
        ),
        **changes,
    )


def test_competition_config_uses_reliable_completion_cap_and_e1_deadlines():
    config = load_competition_config()

    assert config.schema_version == "1.5"
    assert config.final_response_max_chars == 20000
    assert config.primary_max_tokens == 65536
    assert config.max_model_tokens == 0
    assert config.model_context_window_tokens == 262144
    assert config.context_safety_margin_tokens == 8192
    assert config.trace_max_chars == 0
    assert config.trace_max_events == 0
    assert (
        config.soft_deadline_seconds,
        config.exploration_deadline_seconds,
        config.hard_deadline_seconds,
        config.deterministic_finalize_reserve_seconds,
        config.model_call_start_margin_seconds,
    ) == (600.0, 720.0, 850.0, 50.0, 100.0)


def test_zero_token_quota_records_without_enforcement_and_positive_quota_remains_hard():
    unlimited = CallBudget(1, max_tokens=0)
    unlimited.record_tokens(1_000_000)
    assert unlimited.used_tokens == 1_000_000

    limited = CallBudget(1, max_tokens=3)
    limited.record_tokens(3)
    with pytest.raises(BudgetExceeded, match="token"):
        limited.record_tokens(1)


def test_exact_tokenizer_allocation_is_pinned_and_dynamic():
    context = ModelContextBudget(
        context_window_tokens=64,
        safety_margin_tokens=8,
        token_counter=InternS2TokenCounter(FixedTokenizer(prompt_tokens=17)),
    )

    allocation = context.allocate(_messages())

    assert allocation.prompt_tokens == 17
    assert allocation.max_output_tokens == 39
    assert allocation.counting_mode == "official_tokenizer"
    assert allocation.tokenizer_revision == INTERN_S2_TOKENIZER_REVISION
    assert allocation.tokenizer_sha256 == INTERN_S2_TOKENIZER_JSON_SHA256
    assert (
        allocation.prompt_tokens
        + allocation.safety_margin_tokens
        + allocation.max_output_tokens
        == allocation.context_window_tokens
    )


def test_near_window_prompt_shrinks_output_and_oversized_prompt_never_calls_client():
    near = ModelContextBudget(
        context_window_tokens=64,
        safety_margin_tokens=8,
        token_counter=InternS2TokenCounter(FixedTokenizer(prompt_tokens=55)),
    )
    assert near.max_output_tokens(_messages()) == 1

    client = RecordingClient()
    oversized = ModelContextBudget(
        context_window_tokens=64,
        safety_margin_tokens=8,
        token_counter=InternS2TokenCounter(FixedTokenizer(prompt_tokens=56)),
    )
    provider = OfficialClientProvider(client, ModelCallGate(1), oversized)
    with pytest.raises(ContextBudgetExceeded):
        provider.chat(
            messages=_messages(),
            temperature=0.0,
            max_tokens=0,
        )
    assert client.calls == []


def test_completed_response_over_role_cap_is_retained_when_context_still_fits():
    client = RecordingClient(response="1234567890")
    context = ModelContextBudget(
        context_window_tokens=64,
        safety_margin_tokens=8,
        token_counter=InternS2TokenCounter(FixedTokenizer(prompt_tokens=10)),
    )
    budget = CallBudget(1)
    budget.consume(stage="primary")

    response = OfficialClientProvider(
        client,
        ModelCallGate(1),
        context,
    ).chat(
        messages=_messages(),
        temperature=0.0,
        max_tokens=4,
        budget=budget,
        stage="primary",
    )

    assert response == "1234567890"
    assert response.output_budget_exceeded is True
    assert budget.model_call_records[0]["output_budget_exceeded"] is True


def test_multilingual_fallback_avoids_three_times_cjk_overcount():
    counter = InternS2TokenCounter(BrokenTokenizer())
    content = "数学推理需要验证"

    text_count = counter.count_text(content)
    message_count = counter.count_messages(_messages(content))

    assert text_count.counting_mode == "multilingual_estimate"
    assert text_count.tokens == len(content)
    assert text_count.tokens < len(content.encode("utf-8"))
    assert message_count.counting_mode == "multilingual_estimate"
    assert message_count.tokens > text_count.tokens


def test_all_llm_roles_receive_the_same_positive_context_budget_contract():
    client = RecordingClient()
    context = ModelContextBudget(
        context_window_tokens=64,
        safety_margin_tokens=8,
        token_counter=InternS2TokenCounter(FixedTokenizer(prompt_tokens=17)),
    )
    provider = OfficialClientProvider(client, ModelCallGate(1), context)
    stages = (
        "router",
        "primary",
        "alternative",
        "lemma",
        "verifier",
        "repair",
        "finalizer",
    )

    for stage in stages:
        budget = CallBudget(
            1,
            model_context_window_tokens=64,
            context_safety_margin_tokens=8,
        )
        budget.consume(stage=stage)
        assert (
            provider.chat(
                messages=_messages(stage),
                temperature=0.0,
                max_tokens=0,
                budget=budget,
                stage=stage,
            )
            == "ok"
        )
        record = budget.model_call_records[0]
        assert client.calls[-1]["max_tokens"] == record["max_output_tokens"] == 39
        assert client.calls[-1]["max_tokens"] > 0
        assert (
            record["prompt_tokens"]
            + record["safety_margin_tokens"]
            + record["max_output_tokens"]
            <= record["context_window_tokens"]
        )


def test_positive_output_cap_is_preserved_but_cannot_exceed_context():
    context = ModelContextBudget(
        context_window_tokens=64,
        safety_margin_tokens=8,
        token_counter=InternS2TokenCounter(FixedTokenizer(prompt_tokens=17)),
    )

    assert (
        context.allocate(
            _messages(),
            configured_max_output_tokens=12,
        ).max_output_tokens
        == 12
    )
    assert (
        context.allocate(
            _messages(),
            configured_max_output_tokens=60,
        ).max_output_tokens
        == 39
    )


def test_deadline_boundaries_match_600_705_840_870_contract():
    now = [0.0]
    deadline = DeadlineController(
        soft_deadline_seconds=600.0,
        exploration_deadline_seconds=705.0,
        hard_deadline_seconds=870.0,
        deterministic_finalize_reserve_seconds=30.0,
        model_call_start_margin_seconds=135.0,
        clock=lambda: now[0],
    )

    now[0] = 599.999
    assert deadline.can_start_model_call(optional=True)
    assert deadline.phase() == "normal"
    now[0] = 600.0
    assert not deadline.can_start_model_call(optional=True)
    assert deadline.can_start_model_call()
    assert deadline.phase() == "evidence_driven_exploration"
    now[0] = 704.999
    assert deadline.can_start_model_call()
    now[0] = 705.0
    assert not deadline.can_start_model_call()
    assert deadline.can_start_stage()
    assert deadline.phase() == "local_validation_only"
    now[0] = 839.999
    assert not deadline.must_finalize()
    now[0] = 840.0
    assert deadline.must_finalize()
    assert deadline.phase() == "deterministic_finalize"
    now[0] = 870.0
    assert deadline.hard_expired()
    assert deadline.phase() == "hard_expired"


def test_zero_trace_limits_preserve_all_allowed_events():
    events: list[dict] = []
    trace = TraceBuilder(events, max_chars=0, max_events=0)
    for index in range(100):
        trace.add(
            "retrieval_completed",
            card_ids=[f"card-{index}-" + "x" * 1000],
        )

    built = trace.build()
    assert len(built) == 100
    assert len(json.dumps(built)) > 12000


def test_runner_timeout_is_terminal_atomic_and_late_result_cannot_overwrite(tmp_path):
    release = Event()

    def slow_solve(_problem, _metadata):
        assert release.wait(1)
        return {
            "final_response": "late result",
            "trace": [{"event": "run_completed", "outcome": "primary"}],
        }

    runner = PerCaseWallClockRunner(
        slow_solve,
        wall_clock_seconds=0.08,
        serialization_reserve_seconds=0.03,
    )

    def persist(record) -> None:
        write_case_output(record, tmp_path)

    started = perf_counter()
    records, summary = run_benchmark(
        [BenchmarkCase("1", "slow")],
        runner.solve,
        on_record_completed=persist,
    )
    elapsed = perf_counter() - started
    path = tmp_path / "1.json"
    before = path.read_bytes()
    payload = json.loads(before)

    assert elapsed < 0.08
    assert set(payload) == {"id", "status", "final_response", "trace"}
    assert payload["status"] == "timeout"
    assert payload["trace"][-1]["event"] == "run_completed"
    assert payload["trace"][-1]["outcome"] == "timeout"
    assert payload["trace"][-1]["final_phase"] == "timeout_completed"
    assert (
        payload["trace"][-1]["error_code"]
        == "per_case_wall_clock_exceeded"
    )
    assert all(
        event["schema_version"] == "3.1"
        for event in payload["trace"]
    )
    assert records[0].run_metrics.per_case_wall_clock_timeout_count == 1
    assert summary["per_case_wall_clock_timeout_count"] == 1
    assert summary["timeout_rate"] == 1.0
    release.set()
    assert path.read_bytes() == before


def test_oversized_model_response_falls_back_to_context_safe_final_response():
    client = RecordingClient("x" * 270_000)
    result = MathForgeHarness(client, _minimal_config()).solve("1 + 1", {})

    assert result["run_metrics"]["outcome"] == "fallback"
    assert result["run_metrics"]["error_code"] == "all_candidates_failed"
    assert result["run_metrics"]["final_response_tokens"] <= 262144
    assert result["final_response"].strip()
