# Math-Agent

A competition-grade mathematical reasoning harness built around the official Intern-S client.

The official `main.py` and `llm_client.py` files are frozen and verified byte-for-byte. Participant code is exposed through `user_agent.ReasoningAgent`.

## Architecture

`user_agent.ReasoningAgent` is a thin, thread-safe entry point. Each solve creates
an isolated session, parses and routes the problem, runs risk-sized method-orthogonal
candidates under mutually exclusive method-family contracts, checks actual
method duplicates from structured steps and capability-scoped claim evidence,
batches unresolved proof
claims through a soft-evidence VerifierSkeptic, and requires every completed
proof obligation to cite an explicitly mapped Claim and Evidence record before
lexicographic arbitration. High-risk problems can use a verified-lemma loop and
evidence-scoped repair. Lemma curation is a deterministic host service; its
inactive Prompt Contract is retained only for content review and is not used for
a production model call. Every lemma-expanded candidate is included in the same
batch Skeptic and proof-completion gates before arbitration. Final output is
deterministic; the LLM finalizer is
disabled by default. Reviewed knowledge retrieval and the optional MCP adapter
are offline.

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
Run an ablation with
`python scripts/run_benchmark.py --input cases.jsonl --config config/ablation/A4.json --output benchmark-results/A4.json`.

## Runtime configuration

- `MATHFORGE_MODEL_MAX_CONCURRENCY`: bounded shared client concurrency (default `4`).
- `MATHFORGE_USE_MCP=1`: opt into the local StdIO adapter; Direct is the default.

Per-problem defaults are four model calls, 24,000 estimated output tokens, a
12-minute soft deadline, a 13-minute exploration cutoff, and a 14.5-minute hard
finalization deadline. Every failure path returns a non-empty deterministic fallback.
Each result also carries structured call/token/outcome metrics independently of
the bounded judge trace.
