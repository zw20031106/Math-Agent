# Changelog

## Unreleased

### Public output and rerun hardening

- Switched the enforced API request field to `intern-s2-preview`, matching the
  official injected client's callable model name. A full PrimarySolver prompt
  succeeded at 16K and 64K output limits with this field, while the suffixed
  `intern-s2-preview-397b` field failed the same formal request despite passing
  a trivial probe.
- Capped competition completions and the batch preflight at 65,536 tokens while
  retaining the 262,144-token context window, 8,192-token safety margin, and
  unlimited public Trace.
- Upgraded the flat public result to exactly
  `id`/`status`/`final_response`/`trace`; only primary completion maps to
  `success`, while fallback/error maps to `failed` and the watchdog maps to
  `timeout`.
- Added a public Trace projection that preserves complete candidate solution
  content, evidence, lemma/repair history, arbitration, and terminal causes
  while removing repeated phase/context telemetry and compacting provenance,
  skill, and budget summaries.
- Classified provider-side branch exceptions as the safe
  `model_call_failed` reason without exposing raw exception text.
- Added a real content preflight through the injected official client before
  any batch case starts, preventing provider outages from producing a batch
  of fallback files.
- Aligned the per-case runner's official-client HTTP timeout with the Harness
  model-call window and disabled client-internal retries that could cross the
  15-minute case deadline.
- Serialized real model calls and added bounded exponential retries only for
  failures returned within 20 seconds. The competition profile reserves 100
  seconds for those quick failures and permits a 735-second long request.
- Set the competition model-call gate to one concurrent call so alternative
  branches wait at the deadline-aware semaphore instead of starting parallel
  requests against the unstable provider.

### S6-H

- Added pre-online duplicate-ID and input validation to the per-case runner and
  benchmark entry point.
- Added an atomic `run_manifest.json` with input/config hashes, exact model
  identity, per-case output hashes, terminal states, latency, scoring, and
  internal RunMetrics. Public case JSON contains exactly
  `id`/`status`/`final_response`/`trace`.
- Added `--resume` with manifest compatibility checks, strict validation of
  existing public files, hash-bound reuse, orphan-output recovery, unknown-file
  rejection, and execution of missing cases only.
- Hardened the 900-second watchdog so every success, internal failure, and
  timeout produces a non-empty terminal result. Timed-out worker threads are
  closed out of the shared result slot and cannot overwrite a persisted file.
- Synced and atomically replaced both case files and the manifest, then emitted
  a flushed `CASE_COMPLETED` line immediately after each case was durable.

### S6-G

- Made `RoutePlan.selected_tools` an enforced evidence gate and added
  domain-aware symbolic, numerical, matrix, density-normalization, and
  finite-case capability selection. Unsupported route choices and arguments
  that the Host cannot safely reconstruct now produce explicit unknown
  Evidence instead of silent skips.
- Rebalanced the six-call model budget after initial hard Evidence. Repair and
  Lemma calls are now reserved only when their evidence, problem-type, risk,
  dependency-depth, and semantic-verification triggers are present; exhausted
  stages carry a public unreachable reason.
- Expanded public Trace coverage for proof obligations, candidate final
  states, complete Lemma cards and round states, downstream Lemma use,
  Repair claim-graph diffs, expanded-candidate re-verification, and
  background provider tails.
- Restricted Lemma expansion to high-risk proof/derivation problems with a
  deep Claim dependency chain and a semantically verified local claim.
  Expanded candidates pass the full validation, Evidence, obligation,
  skeptic, completion, and arbitration path.
- Added timeout-tail accounting to the provider, budget, Trace, and RunMetrics
  schema 1.2. Late model returns cannot mutate the returned result or its
  metrics snapshot.

### S6-F

- Upgraded all 29 domain and six general skills to a validated Skill 2.0
  contract with triggers, fixed-role compatibility, method decision trees,
  theorem preconditions, common-error and counterexample gates, compatible
  checks, answer normalization, and public Trace guidance.
- Added dedicated skills and deterministic routing for advanced algebra,
  analysis, ODE/PDE, stochastic processes, operations research, regression,
  and differential geometry while retaining all legacy mathematical domains.
- Added atomic, role-specific runtime skill composition for Solver, Lemma,
  Verifier, Repair, and Finalizer stages. Oversized skills and RAG cards are
  omitted whole and recorded rather than character-sliced.
- Added route trigger reasons, parser-confidence and missing-domain risk
  escalation, and role/version/omission details to public Trace events.
- Added an 88-case reviewed router evaluator and frozen pre-E5 baseline.
  Deterministic routing now reaches 87/88 Top-1 and 88/88 Top-2 with no
  unexplained `general-math` Top-1 fallback.

### S6-E

- Upgraded all seven role contracts to Prompt Contract v2. Solver roles now
  require exactly one complete JSON object, exact assigned MethodFamily,
  complete public solution text and steps, structured Claims and MethodSteps,
  explicit controlled enums, no Host-owned output fields, and no native tool
  calls or private scratchpad fields.
- Removed the model-owned `answer_type` request and all soft "when possible"
  wording. Alternative solving now requires a visibly independent public
  method, while Repair and Finalizer contracts preserve local-patch and
  verified-content boundaries.
- Gave VerifierSkeptic only problem conditions, structured Claims,
  MethodSteps, public steps, Evidence, and Proof Obligations. Findings now
  preserve public rationale, missing conditions, and counterexample summaries
  without exposing full Solver solution text.
- Classified strict, fenced, outer, repaired, truncated, malformed, and
  contract-incomplete JSON separately. Added conflict-safe normalization for a
  small approved alias set while retaining auditable deviations.
- Added a fixed 20-case injected-client Prompt Contract probe covering scalar,
  matrix/vector-input scalar, interval-input numeric, polynomial, set/group,
  proof/derivation, and cross-domain cases. Its deterministic contract fixture
  passes all E4 thresholds at 100%; a credentialed Intern-S2 live run remains
  an explicit external validation gate.

### S6-D

- Upgraded `ProblemIR` to schema 1.3, reworked problem parsing around the final
  requested target rather than nouns anywhere in the input, and added
  host-owned `target_phrase` plus
  `parser_confidence` to `ProblemIR` and public Trace 2.0 parsing events.
- Expanded answer types with vector, tuple, polynomial, and algebraic
  structure outputs while retaining expression as the conservative scalar
  fallback. Matrix, interval, integer, and “explanatory variable” input terms
  no longer dictate the requested output shape.
- Added safe vector/tuple/polynomial/algebraic-structure scorers, broader
  restricted LaTeX normalization, and stable invalid-actual reason codes.
- Made JSONL loading accept `answer` as an `expected_answer` compatibility
  alias and fail when both fields conflict.
- Added a mandatory benchmark preflight for complete/parseable expected
  answers and at least 95% automatic-scoring coverage; benchmark artifact
  schema 3.4 records the preflight result.
- Added a reviewed 88-case normalized gold dataset. It has 88 expected
  answers, 100% parser type agreement, zero invalid expected answers, and
  100% automatic scorer coverage; all 19 previously reproduced parser
  counterexamples are regression-tested.

### S6-C

- Added Trace schema 2.0 with host-owned contiguous sequence numbers,
  nondecreasing elapsed milliseconds, stable event stages, JSON round-trip
  validation, and an always-final `run_completed` event.
- Added immediate candidate start/success/failure events, structured public
  solution steps, Candidate/Claim-bound evidence summaries, repair proposals,
  transparent lexicographic arbitration details, and the complete selected
  public solution.
- Upgraded `CandidateSolution` to schema 2.0 with
  `public_solution_steps`; non-selected and failed candidates never expose
  their full raw `solution_text`.
- Added trace integrity gates for generation terminals, evidence terminals,
  repair and arbitration references, selected-candidate consistency,
  final-response consistency, and cross-session/cross-candidate pollution.
- Removed sanitizer length slicing while retaining recursive secret,
  authorization, traceback, nonce, and absolute-path cleaning. Zero trace
  limits preserve all allowed content and events.
- Upgraded the per-case wall-clock timeout path to emit a complete Trace 2.0
  terminal sequence, and validate Trace 2.0 again at the flat public-output
  boundary.

### S6-B

- Upgraded the configuration schema to 1.2 and made `0` the explicit sentinel
  for dynamic per-call output capacity and unlimited aggregate token recording.
- Added one provider-owned 262,144-token context budget for every LLM role,
  using an 8,192-token safety margin, a hash-pinned Intern-S2 tokenizer
  snapshot when locally available, and a conservative UTF-8 byte fallback.
- Removed role-level low output caps and character-quarter token estimates;
  every client call now receives a positive dynamic maximum that satisfies the
  context invariant, while positive legacy caps remain enforceable.
- Implemented the 600/705/840/870-second runtime phases and a 900-second
  per-case terminal runner with a 30-second persistence reserve, atomic timeout
  output, and no late-result overwrite path.
- Expanded metrics and trace budget summaries with prompt counting mode,
  official/fallback prompt tokens, requested and observed output, characters,
  context window, margin, elapsed call time, deadline phase, and timeout
  counters.
- Added E1 boundary tests for configuration sentinels, exact and fallback token
  counting, near-window allocation, oversized prompts and responses, all role
  stages, deadlines, unlimited trace totals, timeout persistence, and late
  background completion.

### S6-A

- Required the exact callable `intern-s2-preview` model request from
  `INTERN_MODEL`; missing values, suffixed/case variants, and caller-supplied
  display labels now fail closed or are ignored before any model call.
- Upgraded run provenance to schema 1.1 and benchmark artifacts to schema 3.2,
  recording the requested model, its environment source, Git dirty state, and
  the fact that response model and thinking-mode metadata are not observable
  through the injected chat surface.
- Added a repository secret-pattern gate that reports only finding type,
  relative path, and line number, without echoing credential content.
- Added E0 regression coverage for exact model identity, provenance
  consistency, alias-artifact rejection, early failure, and credential
  redaction while preserving the immutable official files.

### Public output contract

- Restricted `ReasoningAgent.solve()` to the flat public fields `id`,
  `final_response`, and `trace`; internal metrics and provenance remain on the
  deterministic Harness result for evaluation.
- Added a per-case runner that atomically writes `<id>.json` as soon as each
  case completes, without waiting for slower concurrent cases or nesting fields
  under `result`.
- Kept the official `main.py` and `llm_client.py` byte-frozen.

### S5

- Made reviewed SQLite FTS5 construction atomic: cards are validated and built
  in a same-directory temporary database, integrity and row counts are checked,
  and only then is the previous database replaced.
- Added controlled Chinese-to-English retrieval normalization, an eight-domain
  bilingual recall gate, and explicit matched/no-match/missing-DB/FTS/query
  statuses in runtime traces.
- Required two distinct verification reviewers before a knowledge card may use
  `verified`; the existing eight internal cards remain `reviewed`.
- Added versioned run provenance for code, config, public model identifier,
  Prompt Contracts, Skills, RAG database, tools, content reviews, and optional
  component decisions.
- Upgraded benchmark artifacts to schema 3.1 with a semantic artifact digest,
  provenance validation, A0–A10 overlay loading, and a standalone verifier.
- Added engineering hash review coverage for 18 domain Skills, six general
  Skills, seven Prompt Contracts, proof obligations, tool capabilities,
  routing calibration, golden E2E cases, and retrieval content. Human
  signatures remain an explicit freeze blocker.
- Kept RAG, StdIO MCP, and the LLM finalizer disabled pending representative
  repeated ablations; Direct remains the default and HTTP/persistent MCP is not
  introduced.
- Added a fully pinned CPython 3.13 dependency lock and a clean-venv,
  `--no-index` installation and public-entry smoke check.

### S4

- Added stable safe failure codes, an always-emitted `run_completed` terminal
  event, and opt-in in-memory/JSONL debug sinks that keep sanitized stack frames
  and internal events outside the judge response.
- Replaced ad-hoc runtime counters with a versioned, validated `RunMetrics`
  contract containing cost, terminal state, context, tool, lemma, repair, RAG,
  session, and request-isolation fields independently of bounded traces.
- Upgraded benchmark artifacts to schema 3.0. Per-case metrics and pollution
  evidence now round-trip independently, and every summary value is recomputed
  from records rather than inferred from truncated judge traces.
- Added seeded repetitions, Wilson and bootstrap accuracy intervals, paired
  exact significance analysis, actual model-message nonce probes, foreign-result
  detection, candidate-ownership checks, and post-return mutation detection.
- Added low/medium/high golden E2E tests, 8-way actual-message isolation, 16-way
  fault injection, prompt/schema fuzz checks, and formal Ruff, Mypy, global
  branch-coverage, and critical-module coverage gates.

### S3

- Upgraded core contracts to schema version 1.2 with a controlled
  `MethodFamily`, structured `MethodStep` records, namespaced `ClaimGraph`
  serialization, and namespaced Lemma sources and dependencies.
- Made lemma expansion history-free: the second Solver round receives the
  original problem, conditions, and verified problem-local LemmaCards without
  any historical `solution_text`.
- Moved the single batch VerifierSkeptic call after optional lemma expansion so
  expanded candidates must repeat schema, answer, evidence, obligation,
  Skeptic, completion, and arbitration gates.
- Recomputed Repair impact from both the original and proposed dependency
  graphs, validated final-answer terminal dependencies, and marked rolled-back
  proposed evidence as a rejected transaction.
- Made answer equivalence use the host ProblemIR answer type, assumptions, and
  domains; unknown comparisons are now distinct from confirmed disagreement.
- Replaced free-text method-label agreement with structured step/theorem/claim
  topology signatures and excluded contract-deviating methods from independent
  agreement.
- Added one capacity-bounded RawContextStore per session, exact prompt-view
  character accounting, a metadata allowlist, and lemma-round context
  isolation.

### S2

- Separated Router confidence, ambiguity margin, and complexity signals; close
  high-confidence domains now retain an auxiliary route and populate
  `ProblemIR.subject_candidates`.
- Added one pure risk-policy derivation for candidate count, reasoning rounds,
  RAG, lemma-loop, and finalizer fields, plus a manually labeled routing
  calibration set.
- Added per-session Claim, Tool, isolated Tool, Tool-time, Evidence, and total
  Prompt-character budgets with usage in run metrics and terminal summaries.
- Extended the shared Deadline across parser, RAG, context compression, Direct
  tools, isolated tools, MCP, and arbitration equivalence checks; model starts
  now preserve a configurable worst-case margin.
- Added an explicit CallAllocationPlan for Router, Primary, Alternatives,
  Verifier, Repair, Lemma, and Finalizer calls. Required Verifier capacity can
  no longer be consumed by an earlier optional Repair.

### S1

- Added versioned, validated ProblemIR, RoutePlan, Claim, and
  CandidateSolution contracts with bounded Claim graphs, strict deserialization,
  and host ownership of candidate identity, role, answer type, method plan, and
  version.
- Added an explicit Runtime phase machine with declared success, skip, failure,
  and fallback transitions recorded in judge-safe traces.
- Made `config/competition.json` the default public and benchmark configuration,
  added fully expanded safe/balanced/competition profiles, and rejected unknown,
  mistyped, out-of-range, or dependency-invalid settings at startup.
- Added semantic configuration and content fingerprints for Prompt, Skill, RAG,
  and Tool inputs to public traces and benchmark metadata.
- Made submission validation explicitly warn while the competition profile
  remains `candidate-unvalidated`.

### S0

- Added host-owned Claim kinds, verification states, and a fixed tool capability
  matrix so syntax, parsing, answer-shape, and numerical support cannot be
  promoted into mathematical proof.
- Required proof completion to cite an explicitly mapped Claim, matching
  capability, Evidence record, and invocation; free-text obligation matching
  and inherited `verified` status no longer complete proofs or verify lemmas.
- Disabled LLM finalization by default and made explicitly enabled finalization
  roll back whenever the answer, derivation, claims, assumptions, or theorems
  change.
- Replaced answer-substring detection with one canonical final-answer block
  while preserving raw-text degradation behavior.
- Preserved token counts and terminal events in judge-safe traces, emitted
  independent run metrics, distinguished tool timeout/unknown/error reasons,
  and made context failure metrics use real runtime events.
- Made benchmark records round-trip serializable so every current summary
  metric can be recomputed offline.

### R0

- Replaced suffix-based benchmark grading with answer-type-aware exact,
  symbolic, set, interval, and matrix scorers; proof text is unscored unless an
  explicit scorer is supplied.
- Included fallback samples in call/token averages, added per-request isolation
  fingerprints, and emitted dataset/config/code provenance in benchmark output.
- Marked the full competition configuration as an unvalidated candidate until
  real repeated ablations justify freezing it.

### R1

- Added a single-call, structured VerifierSkeptic production role for unresolved
  medium/high-risk obligations; its findings are always soft evidence.
- Added a proof-completion hard gate that requires every required obligation to
  be satisfied by a mapped verified claim, deterministic evidence, or a mapped
  Skeptic pass before arbitration and finalization.
- Claimless and incomplete proof candidates now fall back instead of being
  formatted as completed proofs.

### R2

- Added reproducible tool invocation records with exact arguments, assumptions,
  domains, tool version, timeout, duration, and a stable input digest.
- Made symbolic counterexamples domain-aware and conservative: incomplete
  assumption parsing yields medium-strength unknown instead of a hard failure.
- Expanded Repair scope through upstream prerequisites and downstream consumers,
  required hard reverification of failed/changed/previously verified affected
  claims, reran candidate answer-type validation, and rebuilt solution text from
  the accepted Claim graph.
- Completed token accounting for Router and Repair model calls.

### R3

- Added explicit, mutually exclusive method-family plans to RoutePlan and bound
  every solver branch to one required family plus a forbidden-family set.
- Distinguished planned families from returned method signatures, marked actual
  duplicate methods, and excluded same-method/duplicate candidates from
  independent-agreement scoring.
- Made PromptContractLoader the system-prompt entry point for RouterPlanner,
  PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent, and
  LLMFinalizer, preserving each role's visible/forbidden context contract.

### P00

- Imported and froze the official competition baseline.
- Added offline baseline integrity verification and project scaffolding.

### P01

- Replaced the Lagent baseline with a thin, stable `ReasoningAgent` entry point.
- Added an isolated per-problem session, bounded model-call gate, compact trace,
  call budget, and deterministic fallback.

### P02

- Added mathematical problem normalization, six-way problem classification,
  answer-type inference, and explicit serializable solution schemas.
- Added resilient model-output parsing, answer validation, and deterministic
  formatting that preserves the extracted exact answer.

### P03

- Added rule-first domain routing with an LLM fallback for ambiguous problems,
  risk-adaptive plans, bounded dynamic skill loading, and fallback routing.
- Added 18 compact domain skills, six general skills, and statically validated
  prompt contracts for the fixed LLM roles.

### P04

- Added deterministic, risk-sized Primary/Alternative fanout with bounded
  parallel model calls, stable ordering, and branch-failure isolation.
- Kept Primary derivations hidden from Alternative prompts and added structural
  duplicate-method detection.

### P05

- Added nine high-value mathematical checks behind a registry and uniform JSON
  result schema, with restricted AST parsing and isolated subprocess timeouts.
- Added claim-level evidence records and a hard-failure gate before candidate
  selection, while treating timeouts as unknown.

### P06

- Added type-aware proof obligations, conservative verifier findings, exact
  answer equivalence clustering, and deterministic lexicographic arbitration.
- Hard failures are ranked before required coverage and agreement; weighted
  soft evidence is used only after all stronger criteria.

### P07

- Added isolated session memory, permissioned blackboard views, read-only static
  stores, raw-context references, and claim dependency graphs.
- Added deterministic evidence-preserving context compression with role-specific
  views, invariant validation, and automatic snapshot rollback.

### P08

- Added high-risk-only lemma curation and verification with explicit provisional,
  verified, conflicted, and rejected states.
- Added two-round progress accounting and stop conditions; only verified lemmas
  enter solver-visible session memory.

### P09

- Added evidence-triggered, claim-dependency-scoped repair with immutable
  candidate versioning and per-candidate/per-problem attempt limits.
- Repairs must reverify only affected claims and roll back when hard failures
  remain, reverification is missing, or evidence quality decreases.

### P10

- Added offline SQLite FTS5 knowledge cards, read-only BM25 retrieval, subject
  and trust filtering, condition reranking, deduplication, and bounded Top-K.
- Seeded eight reviewed high-priority domain cards from repository Skills and
  preserved a no-database fallback with no network dependency.

### P11

- Added an optional local JSON-RPC StdIO MCP server and adapter that reuse the
  existing tool registry and executor without duplicating implementations.
- Direct execution remains the default; process or protocol failures fall back
  to Direct automatically, and no HTTP or network service is used.

### P12

- Added dual internal/judge trace handling with event allowlisting, sanitization,
  and size limits; raw failures, private candidates, and local paths are excluded.
- Added call, estimated-token, and ordered time budgets plus exploration cutoff,
  submission validation, concurrency coverage, and full operational documentation.

### P13

- Added A0–A9 feature-flag configurations and a concurrent JSONL benchmark runner
  covering correctness, domain/type accuracy, cost, latency, failure, lemma,
  compression, repair, fallback, and concurrency-pollution metrics.
- Froze the full competition configuration without inventing benchmark gains;
  modules can be disabled when measured accuracy does not justify their cost.

### Integration hardening

- Wired deterministic claim checks into the evidence ledger, connected hard
  claim failures to bounded RepairAgent transactions, and retained every version.
- Wired the proof/explanation LLMFinalizer with an exact-answer invariant and
  deterministic rollback; removed ambiguous empty `pass` statements.
- Connected verified lemma progress to a budgeted next-round Primary reasoner;
  only verified cards are injected and full historical candidates remain hidden.
