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
deterministic; the LLM finalizer is disabled by default. Reviewed knowledge
retrieval is offline and remains disabled until a repeated ablation demonstrates
a stable benefit. Direct tool execution is the default; the optional one-shot
StdIO MCP adapter is also disabled.

The injected official client is the only model interface. No API keys, alternate
model clients, native function calling, or network retrieval are used.

## Public output

`ReasoningAgent.solve(problem, metadata)` returns exactly one flat public
mapping:

```json
{
  "id": 7,
  "status": "success",
  "final_response": "Final answer: ...",
  "trace": []
}
```

`id` is read from `metadata.id`, falling back to `metadata.idx`. Internal
`MathForgeHarness` results retain metrics and provenance for evaluation, but
those fields are not exposed by the public agent. `status` is `success` only
for a primary solution, `failed` for fallback or execution failure, and
`timeout` for the 900-second per-case deadline.

For one atomic JSON file per input case, written immediately when that case
finishes, use:

```bash
export INTERN_MODEL=intern-s2-preview-397b
python scripts/run_case_outputs.py --input cases.jsonl --output-dir case-outputs --config config/competition.json --concurrency 1
```

Files are named `<id>.json` and contain exactly `id`, `status`,
`final_response`, and `trace`, without a `result` wrapper. A real model-response
preflight must succeed before any case starts. Each terminal success, failure,
or timeout is flushed through a temporary file and atomically replaced before
`CASE_COMPLETED` is printed. Internal metrics and output hashes live only in
`case-outputs/run_manifest.json`.

The per-case runner serializes official-client calls and retries only provider
failures that return within 20 seconds. Each underlying HTTP request gets up
to 735 seconds under the competition configuration; the reserved fast-failure
backoff plus that request still fits inside the Harness model-call window.
This avoids both the sample client's default 120-second cutoff for a long
Intern-S2 reasoning call and concurrent bursts against an unstable endpoint.
The competition model-call gate is therefore fixed at one concurrent request;
candidate branches still exist, but enter the provider in deadline-aware
sequence.

To continue an interrupted run, repeat the command with `--resume`. The runner
validates the input/config hashes, rejects duplicate or unknown case IDs,
validates every existing four-field JSON file and its manifest-bound hash,
then executes only missing cases. The official `main.py` remains byte-frozen
and retains the competition sample's `idx/status` wrapper.

Public Trace is an ordered audit narrative rather than a framework event dump.
It keeps complete candidate public steps, final answers, claims, evidence,
repair/lemma records, arbitration, and terminal cause without a character
limit. Repeated phase transitions, context-view bookkeeping, and duplicate
completion telemetry are omitted. Provider failures are exposed only through
safe reason codes such as `model_call_failed`; credentials and raw exceptions
remain private.

`INTERN_MODEL` is mandatory and must be the exact version ID shown above.
The legacy `intern-s2-preview` field currently targets a 35B model; aliases,
case variants, and caller-supplied display labels are rejected. The official
chat surface returns assistant content but no response model or thinking-mode
metadata, so provenance records the requested model and marks those
response-side fields as unobservable instead of inferring them.

Every role call uses one context-budget service. The competition profile caps
each completion at 65,536 tokens, and the provider passes the positive value
`min(65536, 262144 - prompt_tokens - 8192)` to the client. This retains the
256K total-context invariant while avoiding unstable near-window completion
requests. The preferred counter is the pinned tokenizer snapshot for
`internlm/Intern-S2-Preview-397B@35eba5f142353d180472cdad2d70b09d0a383113`;
set `MATHFORGE_INTERN_S2_TOKENIZER_DIR` to a local snapshot containing the
hash-verified tokenizer config, tokenizer JSON, and chat template. If it is
absent or mismatched, the harness fails over to a conservative UTF-8 byte
upper-bound and records the actual counting mode.

## Verification

```bash
python -m compileall .
ruff check .
mypy mathforge user_agent.py
pytest -q
pytest --cov=mathforge --cov-branch --cov-report=term-missing
python scripts/check_coverage_gates.py
python scripts/scan_secrets.py
python scripts/verify_content_reviews.py
python scripts/verify_baseline_files.py
python scripts/validate_submission.py
pip check
git diff --check
```

Rebuild the reviewed offline FTS5 database atomically with
`python scripts/build_rag.py`. Retrieval distinguishes matched, no-match,
missing-database, unavailable-FTS, and query-error outcomes. A `verified`
knowledge card additionally requires two distinct verification reviewers.

Run any A0–A10 overlay after exporting the exact competition model:

```bash
python scripts/run_benchmark.py --input cases.jsonl --config config/ablation/A4.json --output benchmark-results/A4.json --repetitions 5 --seed 23
python scripts/verify_benchmark_artifact.py benchmark-results/A4.json
```

Create a wheelhouse and prove a clean no-index installation with
`python scripts/verify_offline_install.py --prepare-wheelhouse`, or verify a
pre-existing wheelhouse with
`python scripts/verify_offline_install.py --wheelhouse /path/to/wheelhouse`.
The first form needs network access only while preparing the temporary
wheelhouse; installation and the smoke test are offline.

## Runtime configuration

- `INTERN_MODEL=intern-s2-preview-397b`: required exact 397B model request; aliases fail closed.
- `MATHFORGE_MODEL_MAX_CONCURRENCY`: bounded shared client concurrency (default `4`).
- `MATHFORGE_INTERN_S2_TOKENIZER_DIR`: optional pinned local tokenizer snapshot;
  a mismatch activates the recorded UTF-8 fallback instead of loading it.
- `MATHFORGE_USE_MCP=1`: explicitly opt into the one-shot local StdIO adapter;
  Direct remains the production default.

The competition profile allows six model calls and has no artificial aggregate
model-token quota. It stops low-value optional work at 600 seconds, closes all
new model calls at 705 seconds, enters deterministic finalization at 840
seconds, and requires Harness return by 870 seconds. The per-case runner
reserves the remaining 30 seconds of the 900-second wall clock for a terminal
result and atomic JSON persistence. A late background result has no persistence
callback and cannot overwrite the terminal file. Every failure path returns a
non-empty deterministic fallback.
Each internal Harness result also carries structured call/token/outcome metrics
independently of the judge trace, plus versioned
code/config/prompt/skill/RAG/tool/model provenance. Runtime failures expose only
stable safe error codes in the judge response. Local diagnostics are opt-in
through an injected
`InMemoryDebugSink` or `JsonlDebugSink`; neither is enabled by the public entry
point.

The competition profile intentionally remains `candidate-unvalidated`. Content
hashes have engineering review, but human signatures and representative
repeated A0–A10 evidence are still required before S6 can freeze the profile.
