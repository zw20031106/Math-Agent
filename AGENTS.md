# AGENTS.md

## Repository Mission

Build a competition-grade mathematical reasoning harness around the official Intern-S client.

## Immutable Files

Never modify:

```text
main.py
llm_client.py
```

Run before every commit:

```bash
python scripts/verify_baseline_files.py
```

## Public Contract

The root `user_agent.py` must expose `ReasoningAgent`, whose `solve(problem, metadata)` method returns a JSON-serializable mapping with a non-empty `final_response` and a list-valued `trace`.

## Model Access

All model calls must use only the injected `client.chat(messages=..., temperature=..., max_tokens=...)` interface. Never create another online model client, read API keys, access client private fields, or assume native function calling.

## Thread Safety

The official runner shares one `ReasoningAgent` instance across concurrent calls. Create a new session inside every `solve()`, keep per-problem state local, keep registries and prompts read-only, and guard model concurrency with a bounded semaphore.

## Architecture Boundary

Use fixed LLM roles (`RouterPlanner`, `PrimarySolver`, `AlternativeSolver`, `LemmaCurator`, `VerifierSkeptic`, `RepairAgent`, and optional `LLMFinalizer`) with dynamic domain skills. Parsing, orchestration, budgets, context, memory, retrieval, tools, evidence, proof obligations, arbitration, formatting, trace, and fallback are deterministic services rather than agents.

## Verification and Repair

Hard evidence gates candidates before lexicographic arbitration; weighted scores are only final tie-breakers. Repair is evidence-triggered, claim-local, versioned, reverified, and rolled back when evidence quality decreases.

## Memory, Context, and Trace

Long-term stores are read-only during evaluation. Per-problem state is isolated and released after `solve()`. Compression must preserve the original conditions, hard evidence, proof obligations, final answer, and claim dependencies. Returned trace must not expose secrets, local absolute paths, raw exceptions, full failed candidates, or private reasoning transcripts.

## Tests Required Before Commit

```bash
python -m compileall .
pytest -q
python scripts/verify_baseline_files.py
```

Implement phases in order, add tests for each phase's invariants, update `CHANGELOG.md`, and use one commit per phase.
