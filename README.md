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

The frozen official entry defaults to eight submitted cases. `ReasoningAgent`
owns the effective case-admission boundary and permits at most three active
solves; the Competition model-call gate permits six physical calls under a
weighted global 200 RPM admission controller. Candidate generation
dispatches Primary before optional alternatives, so outer-runner settings are
not required for first-call fairness.

A Host-side Prompt Compiler selects a concise `minimal`, `standard`, `tool`,
or `proof` contract from the parsed problem and deterministic route. Durable
Candidate fields (`method`, `final_answer`, public steps, and Claims) are
requested first, followed by the remaining complete Candidate fields.
Tool-intensive prompts include bounded, executable input-shape examples while
still forbidding model-emitted tool calls or arguments. The representative
simple prompt, including production Skill context, is about 4.0K conservative
fallback tokens instead of the audited roughly 9.5K. Natural-language-only,
truncated, malformed, empty, compatibility-wrapped, or Schema-invalid model
responses are classified separately and rejected as Candidates.

Claim checks are compiled by the Host into typed tool requests and validated
against the same input Schema used by the tool registry before execution.
Only a hard failure from a semantic capability applicable to that Claim, with
complete inputs and condition context, is fatal. Answer-shape and notation
checks remain non-mathematical evidence. Equivalent answer wrappers and common
fraction, set, vector, interval, and matrix representations are normalized
before shape and equivalence decisions. If the optional Verifier is genuinely
unavailable, proof completion may retain an incomplete candidate only when it
already carries deterministic semantic evidence and has no fatal failure.
Benchmark metrics expose tool argument/Schema success, unknown/error rates,
and Repair success/rollback rates.

Symbolic verification first builds a restricted, source-preserving Expression
IR. Denominator, logarithm, square-root, fractional-power, negative-exponent,
and tangent constraints are compared before an equality can become hard
evidence; unresolved natural-number conventions and complex branches fail
closed. Numerical residuals use deterministic independent domain-aware samples
and remain medium evidence. Every SymPy-backed formal tool executes in a
bounded worker process with expression complexity, wall/CPU/address-space, and
request/response limits.

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
`timeout` for the competition profile's 900-second per-case boundary.

For one atomic JSON file per input case, written immediately when that case
finishes, use:

```bash
python scripts/run_case_outputs.py --input cases.jsonl --output-dir case-outputs --config config/competition.json --model intern-s2-preview-397b --concurrency 3
```

Files are named `<id>.json` and contain exactly `id`, `status`,
`final_response`, and `trace`, without a `result` wrapper. An L0-L5
production preflight must succeed before any case starts: exact client/model
identity, raw JSON, AgentTurn, authoritative Router, Solver Candidate, and
optional Verifier readiness are checked as separate levels. A non-empty but
malformed response cannot pass, and a later component cannot hide an earlier
protocol failure. Each level and its safe failure code are stored in
`run_manifest.json`. Each terminal
success, failure, or timeout is atomically persisted before `CASE_COMPLETED`
is printed.

The runner derives a 150-second HTTP delivery window from the competition
deadline profile. It permits one retry only for an explicitly
classified, quickly returned rate-limit, 5xx, or connection failure; empty,
invalid, incomplete, and timed-out responses are not replayed. The runner
constructs the official client with one internal attempt, so all outer
transport attempts remain observable. The Competition model-call gate permits
six concurrent physical requests and reserves retry weight against 200 RPM.

The custom runner uses a rolling case window with default and maximum
concurrency three; a queued case does not consume its 900-second deadline before
dispatch. Each result is atomically written as soon as it finishes.
`run_manifest.json`
moves through `created`,
`preflight_passed`, and `running`, then ends as `completed`, `degraded`,
`aborted`, or `failed`. SIGINT/SIGTERM lets the active case finish its atomic
write, prevents another case from starting, and records `aborted`.

To continue an interrupted or degraded run, repeat the command with
`--resume`. The runner validates the input/config hashes, rejects duplicate or
unknown case IDs, checks model policy, concurrency, code identity, Schema and
output-contract versions, and validates every existing four-field JSON file
and its manifest-bound hash. Manifest 1.3 retains an `attempts` array; a
superseded running attempt becomes `interrupted`, and reruns use a new
`.trace-journal/attempt-000N/` directory. It skips only `success` by default and reruns
`failed,timeout`; use `--rerun-status` to override that set. `--max-cases N`
and `--stop-after-case ID` provide deterministic, resumable stopping points.

The formal platform entry is `user_agent.py`; the resumable local batch entry is
`scripts/run_case_outputs.py`. The official `main.py` and `llm_client.py` are
immutable legacy baseline fixtures, not the participant output contract.
`main.py` still emits `idx`,
forces normal agent returns to `success`, emits a fifth `error` field on
exceptions, and defaults to eight local tasks. The exact four-field/status
lifecycle contract therefore belongs to `scripts/run_case_outputs.py` unless
written permission is granted to change the official baseline.

Public Trace is an ordered audit narrative rather than a framework event dump.
The returned Judge Trace V3.1 keeps configuration/routing/Skill summaries,
selected-Candidate public steps, evidence and proof-completion conclusions,
arbitration, one closed-loop health summary, terminal category, and budget.
Viable non-selected Candidates may expose bounded public answers and public
steps for comparison; hard-rejected/failed Candidates never expose those
fields. Claims, full model responses, and private reasoning remain excluded.
Frozen-cache, deterministic-Shadow, adaptive-fanout, and cross-review decisions
enter a safe aggregate event. Local JSONL journals use a separate sanitized
Debug Trace Schema under `.trace-journal/attempt-000N/` and are never returned
by `ReasoningAgent`.

Judge output is bounded by the final indented UTF-8 serialization, total Trace
characters/events, per-event characters, and rejected-Candidate count. Overflow
becomes a typed summary with a digest; terminal, selection, arbitration,
evidence, and proof-completion events are protected. Provider failures expose
only stable safe reason codes such as `auth_or_permission_failure`,
`provider_5xx`, `network_read_timeout`, `candidate_json_incomplete`, and
`candidate_schema_invalid`; credentials, raw exceptions, absolute local paths,
and private reasoning remain outside the Judge Trace.

The formal injected-client entry does not read or require `INTERN_MODEL` and
records its model identity as unreported because the documented chat surface
does not expose it.
Local benchmark runners use an explicit `--model` argument whose default is the exact
`intern-s2-preview-397b` version ID and reject aliases, case variants, and
caller-supplied display labels. The official chat surface returns assistant
content but no response model or thinking-mode metadata, so provenance records
the locally validated requested model only in benchmark runs and marks formal
response-side identity fields as unobservable instead of inferring them.

Every role call uses one context-budget service and a server-clock-aware role
policy. Configured limits are upper bounds; effective caps are Router/Finalizer
4,096, Verifier 8,192, Repair 12,288, Lemma 16,384, Alternative 24,576, and
Primary 32,768 tokens. Solver profiles further reduce simple Primary and
Alternative calls to 8,192 tokens and standard/tool calls to their compiled
role limits. Router and Finalizer wait at most 60 seconds, Verifier
90, Repair/Lemma 110, and Primary/Alternative 125, always further bounded by
the remaining case deadline. This retains the
`prompt + output + 8,192 <= 262,144` context invariant while prioritizing a
complete response inside the provider clock. The preferred counter is the pinned tokenizer snapshot for
`internlm/Intern-S2-Preview-397B@35eba5f142353d180472cdad2d70b09d0a383113`;
set `MATHFORGE_INTERN_S2_TOKENIZER_DIR` to a local snapshot containing the
hash-verified tokenizer config, tokenizer JSON, and chat template. If it is
absent or mismatched, the harness uses a recorded multilingual character
estimator instead of counting every UTF-8 byte as one token. The configured
context safety margin remains in force.

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

`validate_submission.py` checks the package/public contract and permits the
truthful `candidate-unvalidated` development state. A release is a different
contract: `python scripts/validate_release.py --strict --results-root <root>`
also requires one active fingerprint-verified baseline that is an ancestor-
compatible release input, a passing full test attestation bound to the
release source fingerprint, valid
Prompt/Skill/config/content hashes, completed human review, and a frozen
Competition profile. The strict command intentionally fails before Phase 11
and Phase 12 evidence exists.

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

- `--model intern-s2-preview-397b`: explicit local-runner model selection;
  aliases fail closed. This is not an environment-variable requirement.
- `--concurrency 3`: local runner case concurrency; three is the default and
  maximum.
- `MATHFORGE_INTERN_S2_TOKENIZER_DIR`: optional pinned local tokenizer snapshot;
  a mismatch activates the recorded multilingual estimator instead of loading it.

The formal entry loads exactly `config/competition.json`. Harness feature and
concurrency settings have no environment-variable override. Programmatic
`HarnessConfig(...)` values are for tests/custom embedding, and benchmark
runners load only their explicit `--config` path. The tested source hierarchy
and intentional custom/default differences are recorded in
`docs/CONFIGURATION_SOURCES.md`.

The Competition profile uses a 48-logical-call adaptive bounded budget, soft
checkpoints at 16/28/40, and an eight-call closure reserve, with no artificial
aggregate model-token quota. Optional work closes at 600 seconds, exploration
closes at 720 seconds, the Harness hard deadline is 850 seconds, and the runner
retains the rest of the 900-second outer limit for terminal output and
persistence. Each admission has a separate 15-second queue budget. Queue wait
counts against the problem deadline but not the admitted Turn's execution timeout. A timed
out provider thread is not described as cancelled: it becomes a bounded
background tail, opens the provider circuit at the configured limit, and can
write only a small provider-level late-result record. It cannot retain or
mutate the returned Session. Every failure path returns a non-empty
deterministic fallback.
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

### True multi-Agent remediation status

Phase F0 froze governance and the pre-remediation baseline. Phase F1 now
implements the resource layer: case concurrency 3, weighted global 200 RPM
admission, the 48-call adaptive budget, Turn-specific execution policy,
CallLedger observability, and background-tail/same-Agent in-flight control. The
authoritative phased design is
`docs/MATH_AGENT_TRUE_MULTI_AGENT_FINAL_ARCHITECTURE_AND_IMPLEMENTATION_PLAN_2026-08-02.md`.
Subsequent phases still must implement mandatory LLM routing, independent
Agent calls and communication, multiple Candidates with cross-review, bounded
long-horizon reasoning, and the remaining completion gates. F1 completion must
not be represented as completion of the full true multi-Agent architecture.

Evaluation evidence uses an explicit-allow registry at
`data/evaluation_evidence_registry.json`. Historical case directories and
diagnostic provider failures are ineligible unless a completed, exact-model,
current-commit artifact is explicitly activated. Validate the registry alone
with `python scripts/verify_evidence_registry.py`; add `--results-root PATH` to
also re-hash the locally registered evidence directories.
