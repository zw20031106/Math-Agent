# Changelog

## Unreleased

- Completed true multi-Agent remediation Phase F2 in Shadow Protocol mode.
  Added immutable Agent definitions, per-solve Agent instances and validated
  lifecycle/task state, typed turn payloads, content-addressed Artifact
  envelopes, conversation threads, deduplicated Message envelopes, and complete
  call-to-turn-to-artifact-to-message lineage. Every successful model response
  now publishes a safe hash-only Artifact and a visible inter-Agent message;
  all protocol state is isolated per problem and released before `solve()`
  returns. The legacy flow remains the sole candidate-selection authority until
  the later authoritative migration phase.
- Completed true multi-Agent remediation Phase F1 resource governance: case
  concurrency is configuration-driven and capped at 3; the shared Provider now
  applies weighted rolling 200 RPM admission, six-call physical concurrency,
  same-Agent single in-flight control, and auditable background tails. The
  Competition profile now uses a 48-call adaptive per-problem hard limit with
  16/28/40 checkpoints and an eight-call closure reserve, plus Turn-specific
  output, timeout, and minimum-start-window policies. Added CallLedger and
  resource-governor trace fields and deterministic F1 boundary/concurrency
  tests. This phase establishes the resource substrate only; the Agent runtime,
  mailbox, mandatory Router protocol, and autonomous multi-Agent loop remain in
  later phases.
- Completed true multi-Agent remediation Phase F0 without changing runtime
  behavior: synchronized the authoritative final plan, marked the obsolete
  six-call design as superseded, froze the source/config/Prompt/Skill/Data/model
  baseline, restored the deleted Phase 0 regression suite, and documented the
  Definition of Done and phased governance decision in ADR-003. The active
  Competition profile remains `candidate-unvalidated`; concurrency 3, 200 RPM,
  mandatory Router, the 48-call bounded policy, and typed timeout/Token policies
  were recorded as targets for later phases.
- Added the shared executable `ModelCandidatePayload 2.1` boundary used by
  Prompt compilation and Candidate parsing. Solver prompts now receive the
  Host-owned response mode, require LaTeX-delimited public mathematics, retain
  concise auditable steps for answer-only questions, and require a complete
  bounded proof for proof questions. Aligned Verifier, Repair, and Finalizer
  contracts and made Finalizer roll back any public-content rewrite.
- Upgraded Judge Trace to 3.7 as a solution-first logical narrative: a new
  `workflow_overview` follows the detailed solution, model calls are attributed
  to fixed roles and candidate IDs in call order, successful alternatives keep
  bounded public solution content, and claim-local repair attempts expose their
  public proposal and accept/rollback result without leaking private reasoning.
- Upgraded Judge Trace to 3.6 with a mandatory first `solution_process` event
  containing the selected Candidate's public method, ordered steps, response
  mode, and LaTeX conclusion. Removed the full effective-config snapshot and
  omitted-Skill catalog from public projection, and replaced duplicated final
  solution steps with a `trace[0]` reference.
- Made final-response formatting consume `ProblemIR.response_mode`: ordinary
  direct-answer questions now return one LaTeX answer line, explicit exposition
  requests retain their worked solution, and proof requests retain the complete
  public proof before a single canonical answer block. Choice and plain-text
  answers are emitted through `\mathrm{...}` and `\text{...}` respectively.
- Upgraded ProblemIR to 2.1 with a Host-owned `response_mode` contract
  (`answer_only`, `worked_solution`, or `proof_full`), deterministic Chinese
  and English instruction classification, and validated public-metadata
  overrides without consuming another model call.
- Added a reproducible, path-safe T0 public-output baseline over the sixth
  88-case live run, covering final-response shape, Judge Trace size and event
  distribution, first-event semantics, candidate-content coverage, and output
  contract integrity without storing prompts, credentials, or problem text.
- Raised the default and Competition physical model-call concurrency limit from
  4 to 16 while retaining the four-case runner window, and raised the
  background-tail capacity to the same bound.
- Canonicalized mathematical final answers as LaTeX-delimited public output,
  with matching Solver/Repair prompt contracts and deterministic formatting.
- Bound live profiles to the exact run configuration, redacted external
  absolute paths, and replaced string-only answer comparison with the official
  type-aware scorer before configuration freeze decisions.
- Rejected oversized exact or regex-recovered answers during Candidate
  admission and contained a public-output contract failure to the affected
  case, preventing one malformed answer from aborting concurrent peer outputs.
- Extended type-aware scoring for commuted imaginary products, Unicode number
  fields, and LaTeX row/column vectors discovered in the Phase 7 live run.

### 0730 stability remediation phases 0-6 (2026-07-30)

- Added reproducible Phase 0 reliability, general high-difficulty, and
  contract-adversarial baselines, a hash manifest builder, symbolic-equivalence
  golden tests, and typed transport/schema injection coverage without storing
  credentials, local paths, or private reasoning.
- Made allocation replanning monotonic with respect to consumed stage calls.
  Added a hard-evidence-aware last-safe-candidate checkpoint and controlled
  `degraded_candidate_salvage`, so downstream failures preserve a valid
  mathematical candidate but never resurrect a hard-failed one.
- Reserved a lazy low-risk standby Alternative without adding a normal-path
  call. Ordinary provider failures now drive shared health state and suppress
  optional Router, Verifier, Repair, Lemma, and LLM-finalizer work while the
  provider is degraded.
- Added Phase 0 and Phase 1 execution reports and offline regressions for
  baseline determinism, taxonomy, monotonic budgets, standby recovery,
  degraded scheduling, candidate salvage, and hard-gate rejection.
- Added answer-first scheduler aging and per-session case round-robin while
  preserving the shared physical concurrency bound. Verifier work no longer
  preempts a queued Primary or Alternative before an answer has formed.
- Replaced unconditional queue waiting with a stage-p95/deadline feasibility
  budget recorded on every model-call ledger entry. Post-verifier
  Repair/Reverify now requires both call-count and time-atomic reserves.
- Added a deterministic concurrency 1/2/4 capacity-profile comparator with
  frozen formation, answer-production, accuracy-drop, and peak-concurrency
  gates, plus Phase 2 stress/regression coverage.
- Upgraded ProblemIR to 2.0 with reliable option enumeration, independent
  answer-type confidence, definitions, quantifiers, constraints, target kind,
  ambiguities, structural difficulty features, and public subproblem hints.
- Added general structural high-difficulty routing and explicit Primary
  posterior escalation while keeping low-confidence answer-type inference a
  soft normalization gate rather than a Candidate rejection.
- Added Judge Trace 3.2 effective Prompt/Provider/Deadline configuration and
  per-call token/queue-limit explanations. An enabled but empty Frozen Lemma
  Store is now disabled before evaluation work begins.
- Added versioned public `ReasoningState`, `ProblemFrame`, `SubgoalLedger`,
  `ClaimLedger`, and `RoundDelta` contracts with dependency validation and
  token-budgeted compression that preserves the problem frame, Claim graph,
  and open obligations.
- Added explicit `explore`, `continue`, and `synthesize` Prompt protocols.
  High-difficulty cases may use two or three budget-feasible public rounds;
  simple cases remain single-round, and a failed progress protocol falls back
  to direct Candidate generation rather than suppressing answer production.
- Upgraded Judge Trace to 3.3 with bounded round summaries, information gain,
  cross-round references, stop/degradation reasons, and per-round state token
  accounting without private reasoning transcripts.
- Added deterministic, role-specific dynamic Skill fragment selection from
  ProblemIR, open Subgoals, tool feedback, and safe failure codes. Included and
  omitted fragments now carry rank, score, section, and reason metadata.
- Added Host-owned typed `CheckSpec` generation and a public
  `work_item -> local tool -> ToolResult -> continue` loop. Unconstructible
  checks remain nonfatal `unknown` results, while hard tool failures can switch
  the next-round strategy without exposing tool arguments in Judge Trace 3.4.
- Made Lemma reuse target-driven through typed source Claims and explicit proof
  obligation IDs. Added a hash-bound, reviewed, versioned, read-only general
  method-card store while keeping runtime RAG and Frozen Lemma Store disabled
  until controlled A/B validation.
- Planned candidate-independent proof obligations before every Solver call,
  then bound them to actual Candidate Claims and appended method-specific
  theorem, boundary, and interchange obligations after generation.
- Replaced summary-only verification with bounded Claim-linked public solution
  segments. Answer, assumption, critical-Claim, and obligation conflicts now
  produce explicit answer- or claim-level review targets and target coverage.
- Separated hard completion, independent corroboration, targeted model review,
  no-proof-required, and incomplete evidence tiers. A soft Verifier pass no
  longer marks a proof hard-complete.
- Removed generation order from exact arbitration ties. Candidate ranking now
  prefers hard evidence, independent agreement, and targeted review before a
  stable digest of public Candidate content.
- Made post-Verifier repair contingent on an atomic Repair/Reverify call and
  time reserve. Failed, missing, non-improving, or evidence-regressing repairs
  retain the original Candidate and reject the proposed evidence transaction.
- Upgraded Judge Trace to 3.5 and Effective Config Snapshot to 1.2 with bounded
  obligation planning, review-target coverage, evidence tiers, and atomic
  repair observability.

### 0729 remediation phase 6 (2026-07-29)

- Upgraded Judge Trace to V3.1 with one protected `closed_loop_health`
  event per case, deterministic status/outcome/proof consistency checks, and
  preservation of specific model transport failure codes.
- Added safe decision summaries for Frozen Lemma Cache, deterministic Shadow,
  adaptive fanout, and Candidate cross-review; viable non-selected Candidates
  now expose only bounded public answers and public solution steps.
- Fixed proof summaries without a selected Candidate and prevented Windows
  path redaction from corrupting LaTeX commands such as `\int`, `\in`, and
  `\lim`.
- Added attempt-scoped `.trace-journal/attempt-000N/` directories and
  Manifest 1.3 attempt history. Resume marks a superseded running attempt as
  interrupted and validates model policy, concurrency, code identity,
  configuration, schemas, and the four-field output contract.
- Isolated console write failures from already-persisted case results and
  added Phase 6 regression coverage for health, root-cause retention,
  compression, attempt recovery, and resume compatibility.

### 0729 remediation phases 4-5 (2026-07-29)

- Added budget-aware adaptive fanout after Primary, capped optional
  Alternatives at two, protected required-stage reserves, and suppressed
  no-benefit branches for complete low-risk candidates.
- Added public Candidate conflict matrices and one joint cross-review,
  operation-derived proof obligations, explicit four-state verifier reporting,
  actionable-failure repair gates, atomic Repair/Reverify reservation, and
  deterministic single-Candidate finalization.
- Added a Host-owned deterministic Shadow capability registry for restricted
  algebra, systems, matrices, limits, integrals, and sums. Shadow answers remain
  hidden from Primary, enter Candidate v2 with independent provenance and hard
  evidence, and provide a concrete degraded-quality result when model branches
  fail.
- Added solve-local L0/L1 memoization and a hash-checked, runtime-read-only
  Frozen Lemma Store with strict assumption revalidation and a separate
  offline human-review-to-freeze builder.
- Changed the candidate competition timing profile to a 900-second outer
  boundary, 850-second Harness hard deadline, 600-second soft cutoff,
  720-second exploration cutoff, and 50-second terminal reserve while
  preserving the 20,000-character final response and unbounded internal trace
  settings.
- Added Phase 4 and Phase 5 execution reports plus deterministic regressions
  for fanout, proof closure, Shadow isolation/fallback/conflict, Frozen Store
  immutability, and deadline contracts.

### 0729 remediation phases 2-3 (2026-07-29)

- Added one bounded Primary recovery envelope for retryable transport failures
  or Candidate contract correction, while local transport remains single-shot.
- Added stage-priority physical-call scheduling, actual-dispatch accounting,
  background-tail permit retention, budget snapshots, and deterministic Router
  defaults for the competition profile.
- Extended Candidate v2 with Host-owned source and parse tiers, accepted safe
  recovered/answer-recovered responses behind deterministic gates, and made
  method-label differences a diversity signal instead of an admission failure.
- Added complete-Candidate tail extraction, Host-generated MethodSteps,
  claim-local `CandidatePatch` repair, public cross-review summaries, and a
  deterministic conflict matrix.
- Added Phase 2 and Phase 3 execution reports and offline transport, scheduling,
  parsing, Host-ownership, Repair Patch, and cross-review regressions.

### 0729 remediation phases 0-1 (2026-07-29)

- Added sanitized live-response replay fixtures and strict regression
  characterizations for all defects assigned to later phases.
- Added a four-case admission boundary to `ReasoningAgent`, aligned the
  competition model-call gate at four, and made Candidate generation dispatch
  Primary before optional alternatives.
- Replaced eager full-dataset submission with a rolling four-case scheduler;
  each completed case is still persisted immediately and resume compatibility
  now includes case concurrency.
- Removed the local retry client's network-wide lock. Local runners select the
  exact `intern-s2-preview-397b` model through `--model` and no longer require
  `INTERN_MODEL` or `LOCAL_MAX_CONCURRENCY`.
- Added Phase 0 and Phase 1 execution reports plus offline concurrency,
  scheduling, manifest, model-selection, and Primary-first regression tests.

### 0728 audit remediation phases 0-4 (2026-07-29)

- Added regression characterization for deadline-bound Candidate retention and
  response/context-budget handling, and refreshed prompt-content provenance.
- Raised formal Harness model concurrency to three, separated timed-out calls
  into a bounded background-tail pool, and opened the circuit only after the
  configured tail threshold instead of after one slow call.
- Preserved valid responses that arrive before their provider timeout even
  when deterministic finalization has begun.
- Refunded call allocations for requests rejected before dispatch and retained
  completed responses that exceed a role's soft output budget while remaining
  inside the 256K context boundary.
- Replaced UTF-8-byte token estimation with a conservative multilingual
  estimator and separated model-start, deterministic-finalization, and local
  stage deadline semantics.
- Replaced the false fixed formal-model identity with an explicit
  `unreported` identity for the injected official client; local validation
  continues to require an exact configured model ID.
- Changed proof completion to best-available arbitration: incomplete original
  Candidates remain eligible, hard-failed Candidates are rejected, and
  unreviewed lemma-expanded Candidates remain barred from arbitration.
- Added empty-LLM-finalizer rollback, terminalization failure metrics,
  candidate-ID-based rejection bookkeeping, and less aggressive high-risk
  routing.
- Removed the ignored generated `build/` source duplicate and refreshed build
  provenance hashes. Added a stage execution report for every remediation
  phase.

### Phase 6 live-model validation (2026-07-28)

- Raised the L1 structured preflight output budget from 256 to 4,096 tokens
  after the official Intern-S2 397B client returned a response truncated at
  `{"` while spending the small budget on reasoning. The exact
  `{"status":"ok"}` semantic gate remains unchanged.
- Added the exact model-owned Claim and MethodStep key sets to the compact
  runtime solver protocol after the live L2 probe improvised common but
  non-contract `id`, `step_number`, `description`, and `justification` fields.
- Required string Claim/MethodStep identifiers and enumerated the allowed
  `check_type` values after the next live probe emitted numeric step IDs and an
  unsupported check suggestion.
- Reserved one otherwise-unused Primary call and retry a rejected Primary
  candidate contract once at temperature zero. The retry remains inside the
  existing call allocation, deadline, context, parser, and evidence gates.
- Require theorem-using candidates to emit a theorem-preconditions Claim, and
  dynamically allocate Verifier review whenever required obligations exist.
  Low-risk routing no longer makes strict proof completion impossible.
- Convert malformed or natural-language symbolic tool inputs into bounded soft
  tool errors at the resource boundary instead of allowing `SyntaxError` to
  terminate the entire Harness run.
- Set the public `final_response` budget to 20,000 characters as a versioned
  configuration value. Limit handling preserves the complete exact-answer
  block, while Judge Trace remains governed by its separate evidence budgets.
- Added a compact exact Candidate JSON skeleton to the production prompt and
  feed safe field-level parser deviations into the bounded zero-temperature
  Primary retry. Nested Candidate schema failures now enter the same retry
  path, and final branch failures retain only safe validation codes.
- Treat an assigned method-family mismatch as a retryable model response error
  and enforce the same method contract again at deterministic Candidate
  admission instead of merely reducing its arbitration score.
- Make L2 model preflight use the production `SolverExecutor`, Parser, method
  contract, and one bounded feedback retry. A single stochastic schema miss no
  longer aborts a run under a stricter path than the real case path.
- Preserve safe first-attempt Candidate deviation codes when the bounded
  corrective retry encounters a transport failure; raw provider errors and
  failed Candidate text remain excluded.
- Normalize nested-brace LaTeX fractions and common Unicode mathematical
  constants/operators in strict benchmark scoring after live outputs exposed
  false `invalid_actual_syntax` results for equivalent answers.
- Raise VerifierSkeptic's request window from 90 to the existing 125-second
  provider boundary after a valid live Candidate was discarded when its
  required Verifier timed out early and tripped the background-tail circuit.
- Separate the official 120-second generation boundary, a 150-second HTTP
  delivery window, and a 165-second Harness gate window after live validation
  showed that a local system proxy could consume the former five-second grace.
  Apply the same reasoning-call window to repair and lemma roles.
- Classify proxy/TLS EOF and connection-reset signatures as retryable network
  connection failures, and bound Candidate/repair output to 8,192 tokens.
  This still exceeds the 20,000-character public answer budget while making a
  complete Candidate realistically returnable inside the provider generation
  window.
- Specify scalar and list-item types for every model-owned Candidate field after
  a live 397B response used an object-valued `theorems[0]` despite otherwise
  valid strict JSON.
- Normalize Unicode lambda, alpha, and beta in symbolic scoring after a correct
  live characteristic polynomial was misreported as invalid syntax.

### Phase 5 architecture and engineering governance (2026-07-27)

- Added typed Candidate, Evidence, and Proof Stage boundaries without changing
  the public API or the runtime state topology.
- Made disabled RAG and LLM Finalizer construction lazy, retained lazy MCP
  opt-in, and removed import-time Git/DB/registry Provenance work.
- Established the fully expanded competition profile as the formal
  configuration source and removed unused Harness environment overrides.
- Split immutable and participant-mutable baseline manifest groups and expanded
  secret scanning with digest-scoped allowlisting.
- Added PEP 621 metadata, bundled runtime resources, Linux Python 3.10
  constraints, a real installed-wheel smoke from outside the repository, and
  an Ubuntu 3.10 network-denial formal CI gate.
- Documented the formal entry, safe bounded single-case runner, and immutable
  legacy runner boundary.

### Phase 4 domain-aware math kernel and sandbox (2026-07-27)

- Added a minimal Expression IR that preserves normalized source, restricted
  AST, SymPy expression, symbols, explicit domains, derived constraints,
  singularities, unresolved conditions, and context completeness.
- Replaced the temporary syntax-risk gate with source-domain equivalence:
  removable singularities remain conditional, supplied conditions can
  discharge domain obligations, and ambiguous natural/complex conventions
  cannot produce unconditional hard evidence.
- Changed numerical residual checks to deterministic independent,
  domain-aware products and exposed attempted/valid/rejected sample counts,
  symbol count, strategy, and maximum residual while retaining medium strength.
- Added expression length/node/depth/integer/exponent/cost limits, isolated
  every SymPy-backed formal tool, POSIX CPU/address/file limits, bounded worker
  requests/responses, suppressed tool stdout/stderr, and safe crash/timeout
  outcomes.
- Added deterministic property/metamorphic tests and explicit branch gates for
  symbolic, numerical, worker, formal-entry, completion, and terminalization
  code, including subprocess coverage collection.

### Phase 3 judge trace and output governance (2026-07-27)

- Added an explicit Judge Trace V3 projection for the formal public result
  while retaining the complete sanitized Debug Trace in local incremental
  journals.
- Reduced every rejected Candidate to an identity/method/status/digest/
  rejection/evidence summary; rejected answers, solution steps, Claims, raw
  responses, and private reasoning never enter public output.
- Protected selection, evidence, proof-completion, arbitration, terminal, and
  budget events while applying structured digest summaries to optional
  overflow.
- Enforced public-result UTF-8 byte, Judge Trace event/character, per-event
  character, and rejected-Candidate count budgets from named configuration
  profiles.
- Added adversarial coverage for conflicting answers, long proofs, 64 Claims,
  4,096 internal events, secrets, absolute paths, tracebacks, private payload
  keys, terminal failures, and final-response consistency.

### Phase 2 concurrency, timeout, and lifecycle closure (2026-07-27)

- Added an explicit per-call model queue budget and made role timeouts include
  semaphore wait, execution, and the shared absolute deadline reserve.
- Added separate queue, execution, total-call, admission-rejection, and queue
  timeout telemetry to call records, internal metrics, and the compact budget
  trace.
- Added a deterministic provider health state with bounded background tails,
  circuit-open fast failure, automatic reset only after all tails complete, and
  a bounded late-result registry that stores no Session or Candidate objects.
- Froze Session state at terminalization and froze Budget and Trace before
  returning, while preventing late provider completion from mutating per-case
  ledgers.
- Parameterized the 20-minute competition profile as a 1,200-second outer
  limit, 1,150-second Harness deadline, 50-second Harness finalization reserve,
  and 50-second runner persistence reserve without changing model concurrency.
- Added fake-clock deadline checks, 2/4/8 shared-instance concurrency coverage,
  weak-reference lifecycle checks, and a 100-request circuit/timeout soak.

### Phase 1 trusted correctness path (2026-07-27)

- Added a no-throw terminalizer and a dependency-free outer fallback so
  bookkeeping, metrics, trace, debug-sink, and final token-count faults cannot
  violate the public result contract.
- Added one deterministic Candidate admission gate and applied it to primary,
  alternative, lemma-expanded, repaired, and selected Candidates before they
  can advance.
- Narrowed Verifier unavailability handling to expected budget, transport, and
  context failures; programming defects now fail closed through the runtime
  fallback.
- Removed proof-completion degradation: every required obligation must have
  mapped active evidence before arbitration, regardless of problem type.
- Added one bounded post-Verifier repair cycle with claim-local scope, full
  admission/evidence/obligation/Verifier replay, strict-improvement acceptance,
  and evidence rollback.
- Corrected lifecycle semantics with `PRECHECKED`, post-completion `VERIFIED`,
  and conditional `REVERIFIED` only after a post-Verifier repair was actually
  revalidated.

### Phase 0 stop-line remediation (2026-07-27)

- Decoupled the formal `ReasoningAgent` entry from local API/model
  environment variables while retaining exact-model enforcement in local
  benchmark runners.
- Replaced the permissive offline smoke with one strict Candidate fixture and
  assertions for genuine success, answer `2`, list-valued trace, and no
  fallback.
- Reduced runtime metadata to opaque identifiers before context, memory,
  prompts, or trace construction.
- Made finite enumeration fail closed for empty or oversized input, removed
  silent truncation, exposed counts, and enforced the same 1–128 bounds in
  tool Schemas.
- Made symbolic equivalence conservative for variable denominators,
  domain-sensitive functions, non-polynomial powers, incomplete assumptions,
  and the ambiguous natural-number convention.

### Phase 5 trace and observability

- Added explicit per-call Transport Events with canonical fixed-role names,
  status, attempts, response-validation outcome, elapsed time, output size,
  and safe provider failure categories. Raw provider exceptions never enter
  the public event.
- Added a deterministic Claim—Evidence Proof Graph linking Candidate,
  Claim dependencies, active or rolled-back Evidence, Proof Obligations,
  candidate versions, final states, and the selected Candidate.
- Added a per-case structured trace summary covering roles called, Candidate
  completeness and answers, evidence outcomes, Repair decisions, rejection
  reasons, selection reasons, provider outcomes, and the decision path.
- Added an optional sanitized JSONL event sink and enabled one isolated,
  fsynced incremental trace journal per case in the custom case-output
  runner.
- Separated thread-safe public and internal Trace streams, bounded resident
  event memory even when configured character/event limits are zero, merged
  repeated public lifecycle events, and summarized oversized payloads with
  a preview and digest.
- Extended Trace V2 validation with Transport, Proof Graph, case-summary,
  cross-reference, JSON round-trip, and sensitive-content invariants.

### Phase 4 evidence, tool, and proof closure

- Added a Host-owned Claim-to-tool request builder and a shared input-Schema
  validator. Every supported Claim now records whether arguments were
  reconstructable, Schema-valid, executed, unknown, or erroneous.
- Restricted fatal hard failures to evidence whose semantic capability applies
  to the Claim kind and whose input and assumption/domain context are complete.
  Answer-shape and syntax checks can no longer reject mathematical truth.
- Added answer normalization for wrappers, fractions, ordered/unordered
  structures, vectors, intervals, and matrices before shape or equivalence
  decisions.
- Added a deterministic proof degradation path for genuine Verifier
  unavailability. It preserves only candidates with existing semantic hard
  evidence and no fatal failure; malformed Verifier findings still fail closed.
- Strengthened method independence with both MethodStep and Claim-topology
  signatures, and added tool argument/Schema rates plus Repair success,
  rollback, and evidence-quality rollback metrics.
- Kept Repair claim-local and versioned; invalid answer-shape patches,
  incomplete reverification, remaining fatal evidence, and reduced evidence
  quality are rolled back.

### Phase 3 prompt, parser, and output integrity

- Added a Host-side Prompt Compiler that selects `minimal`, `standard`,
  `tool`, or `proof` Solver profiles from `ProblemIR` and `RoutePlan`, and
  compiles concise Router, Verifier, Repair, and Finalizer contracts without
  repeating the static long-form examples at runtime.
- Put durable Candidate fields first, added profile-specific output budgets,
  and reduced the representative simple production prompt from the audited
  roughly 9.5K fallback tokens to about 4.0K including production Skill
  context.
- Added precise, executable Claim/input examples for all nine local tools;
  tool prompts expose only examples and continue to forbid model-emitted tool
  arguments or native tool calls.
- Made Candidate response integrity explicit for complete, Schema-violating,
  truncated, malformed, natural-language-only, and empty responses. All but a
  complete strict Candidate now fail the Solver/Repair/Finalizer response gate.
- Rejected JSON wrappers embedded in `solution_text` before deterministic
  formatting, preventing Candidate protocol objects from leaking into
  `final_response`.
- Added the Prompt Compiler and tool Claim examples to prompt/content
  fingerprints and engineering review scopes.

### Phase 2 runner and frozen-entry parity

- Made the custom competition runner strictly single-case (`concurrency=1`) so
  a case's 900-second wall clock starts only when that case is actually
  dispatched; queued cases can no longer consume their deadline.
- Added explicit Manifest lifecycle states for `created`,
  `preflight_passed`, `running`, `completed`, `degraded`, `aborted`, and
  `failed`, including safe SIGINT/SIGTERM handling that finishes the active
  case write and stops accepting new cases.
- Added controlled stops with `--max-cases` and `--stop-after-case`, and
  changed provider-circuit termination from a fatal run failure to a
  resumable degraded run.
- Changed `--resume` to skip only successful case files by default and rerun
  `failed`/`timeout` files, with an explicit `--rerun-status` override.
- Added frozen official-entry parity tests and documented the remaining
  immutable `main.py` wrapper differences (`idx`, forced success, extra error
  payload, and default concurrency eight) that cannot be corrected without
  written permission to change the official baseline.

### Phase 1 model-call minimum closed loop

- Added L0/L1/L2 preflight for exact model/client readiness, strict short JSON,
  and a compact mathematical Candidate that must pass the production parser,
  deterministic formatter, Trace validator, and flat public contract before a
  batch can start.
- Replaced the former 600-second local request assumption with a
  server-clock-aware 125-second transport ceiling and shorter role deadlines.
- Added role-specific output caps for Router, Primary, Alternative, Verifier,
  Repair, Lemma, and Finalizer while preserving the 256K context invariant.
- Added safe transport and response classifications, rejected truncated or
  schema-invalid Candidate JSON in Solver, Repair, and Finalizer paths, and
  kept raw exceptions out of Trace and preflight reports.
- Made the frozen official client's internal attempt count one in the custom
  runner, allowed one outer retry only for explicit fast retryable failures,
  and added per-call attempt/failure/validation telemetry to RunMetrics 1.3.
- Added a consecutive provider-failure circuit breaker that stops scheduling
  later batches and records the open circuit in the run manifest.

### Phase 0 evidence freeze

- Confirmed that no benchmark process was still running before changing
  evaluation governance.
- Added a deny-by-default evidence registry with an explicit active-baseline
  gate. The old 88-case three-field run, the interrupted uppercase-model run,
  and the current two-case provider-failure diagnostic are all recorded as
  ineligible for an accuracy baseline.
- Added deterministic directory fingerprints and an optional local tree check
  without moving, deleting, or rewriting historical user results.
- Integrated evidence-registry validation into submission validation. The
  competition profile remains `candidate-unvalidated` and has no active
  benchmark baseline.
- Recorded that a longer local HTTP timeout does not override the official
  provider's documented response-time boundary; existing long-timeout runs are
  transport diagnostics rather than proof of model reliability.

### Public output and rerun hardening

- Restored the enforced API request field to the official exact version ID
  `intern-s2-preview-397b`. The apparently successful `intern-s2-preview`
  comparison used the documented Legacy alias, which currently targets 35B
  and therefore was not a valid 397B acceptance test.
- Reclassified the earlier 397B formal-request failure as a 120-second client
  timeout, not an invalid model ID.
- Verified the corrected path with a real end-to-end case using
  `intern-s2-preview-397b`: the formal model call completed in 85.15 seconds,
  parsed as strict CandidateSolution JSON, and produced the symbolically
  correct answer under a terminal `success`/`primary` result.
- After observing consecutive provider failures at 126.6 and 158.9 seconds,
  expanded the bounded retry window to 180 seconds, allowed one retry, and set
  each underlying HTTP request to 600 seconds. The worst retry path remains
  inside the 15-minute per-case deadline.
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
- Serialized real model calls and allowed one bounded retry for failures
  returned within 180 seconds. The competition profile reserves 235 seconds
  for failure handling and permits a 600-second underlying request.
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

- Required the exact lowercase `intern-s2-preview-397b` model request from
  `INTERN_MODEL`; missing values, aliases, case variants, and caller-supplied
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
