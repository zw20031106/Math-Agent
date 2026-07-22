# Math-Agent

A competition-grade mathematical reasoning harness built around the official Intern-S client.

The official `main.py` and `llm_client.py` files are frozen and verified byte-for-byte. Participant code is exposed through `user_agent.ReasoningAgent`.

## Architecture

`user_agent.ReasoningAgent` is a thin, thread-safe entry point. Each solve creates
an isolated session, parses and routes the problem, runs risk-sized method-orthogonal
candidates, checks claim evidence, applies proof obligations and lexicographic
arbitration, and returns a compact judge-safe trace. High-risk problems can use a
verified-lemma loop and evidence-scoped repair. Reviewed knowledge retrieval and
the optional MCP adapter are offline.

The injected official client is the only model interface. No API keys, alternate
model clients, native function calling, or network retrieval are used.

## Verification

```bash
python -m compileall .
python scripts/verify_baseline_files.py
pytest -q
python scripts/validate_submission.py
```

Rebuild the reviewed offline FTS5 database with `python scripts/build_rag.py`.

## Runtime configuration

- `MATHFORGE_MODEL_MAX_CONCURRENCY`: bounded shared client concurrency (default `4`).
- `MATHFORGE_USE_MCP=1`: opt into the local StdIO adapter; Direct is the default.

Per-problem defaults are four model calls, 24,000 estimated output tokens, a
12-minute soft deadline, a 13-minute exploration cutoff, and a 14.5-minute hard
finalization deadline. Every failure path returns a non-empty deterministic fallback.
