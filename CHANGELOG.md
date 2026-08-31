# Changelog

## Unreleased

- Aligned the R0 evidence registration and task report with the authoritative
  v3 Accuracy/Context/Truncation/Provider plan; historical aggregate evidence
  remains ineligible and the missing three-run current-HEAD baseline remains
  explicitly blocked.
- Added Phase R0 evidence contracts and fail-closed tooling. Current candidate
  identity now records source/config/prompt/skill/model/tokenizer fingerprints;
  historical official 112-case aggregates are registered separately as
  ineligible references; and repeated current-HEAD Benchmark artifacts require
  three comparable runs before a diagnostic baseline can be complete. Added
  `capture_current_identity.py`, `build_r0_baseline.py`, R0 fixtures, and the
  execution report; no active baseline is enabled by this phase.
- Added a fail-closed compatibility normalization for Verifier responses that
  arrive as an unwrapped findings array from the official Intern endpoint;
  Claim/Obligation ownership checks remain unchanged and the case-runner
  preflight can now distinguish that artifact from an empty review. Production
  preflight also retries transient Router and Verifier protocol failures up to
  three bounded attempts before failing closed.
- Implemented E8 Benchmark / Ablation / Release Freeze foundations. Benchmark
  loading now accepts the official JSON-array export as well as JSONL, and the
  repository includes validated B1 gradeability, B2 core-math, and B3 failure
  challenge suites. Added explicit W0–W8, S0–S3, V0–V3 and P0/P1 arm
  registries/config overlays, interleaved paired-run validation with provider
  health and repetition gates, a complete E8 metric vocabulary, and a
  fail-closed freeze-gate CLI. Prompt A/B runs can explicitly select the
  AgentTurn 1.0 or 1.1-lite protocol through the benchmark harness; no public
  JSON fields or release status are changed automatically. Added the explicit
  invalid-expected diagnostic mode required by the supplied 112-case boundary
  export and a read-only full-run analyzer that joins manifest metrics with
  revalidated public outputs; invalid scoring coverage and missing paired or
  human evidence remain visible blockers rather than being treated as passes.
- Completed E7 Public JSON / Trace / Renderer work. The official result now has an
  explicit four-field validator and control-character guard, while runtime
  diagnostics are emitted to a separate Evaluation Artifact sink. The current
  scorer contract is recorded as `worked_solution -> exact answer`; proof-full
  responses use a dependency-ordered `VerifiedProofRenderer` with coverage-aware
  semantic compaction and emergency fallback only when required units cannot fit.
  Trace eviction now follows accuracy-first priorities so plan, reasoning,
  verification, arbitration, and finalization survive before repair, Skill, and
  model-activity details. Added E7 public-contract, artifact-isolation, proof
  renderer, and trace-priority regression coverage; official real-model evidence
  remains pending.
- Completed E6 Verification / Repair / Arbitration work. Added an explicit
  VerificationState that separates not-disproved from hard-verified evidence,
  risk-aware CompletionPolicy, end-to-end AnswerConsistency, Host cognitive
  provenance, conservative same-model corroboration, concession semantics, a
  five-class repair classifier, atomic repair/reverify/audit admission, final
  audit coverage, and PASS/FAIL/UNKNOWN/UNSUPPORTED/MALFORMED/TIMEOUT/
  INTERNAL_ERROR evidence taxonomy. Runtime trace now records the complete
  repair closure reservation and best-available retention decision. Added E6
  invariant coverage; official real-model/full-run evidence remains pending.
- Completed E5 authoritative TaskGraph/Scheduler work. Added the per-session
  `GraphExecutor`/`GraphState` state machine, scheduler task bindings, dynamic
  graph expansion, plan-version cancellation, generation and wave fences, and
  late-result telemetry. Router, long-horizon Primary/Alternative progress,
  and Candidate synthesis now execute as graph waves; strict competition
  configuration rejects unbound Provider calls. Replan acknowledgements are
  accepted only from real Solver Turns, and critical-path admission accounts
  for model-start and deterministic-finalization reserves. Added E5 invariant
  coverage and execution governance evidence; official real-model/full-run
  evidence remains pending.
- Completed E4 stateful long-horizon and truncation recovery work. Added
  protocol-aware `TruncationAssessment`, bounded public `CheckpointCursor`
  rollback/resume, stateful Candidate rebuilds from `ReasoningState` and
  `ProofBackbone`, closure-window-only emergency fallback, and recovered-answer
  corroboration gates. Host-managed `VerifiedFactBank`, proof-backbone
  dependency inference, semantic information-gain scoring, and public trace
  events now preserve mathematical frontier state without private reasoning.
  Added E4 invariant, solver recovery, and runtime checkpoint regression tests;
  formal competition evidence remains pending.
- Completed E3 executable-Skill work. Added the immutable
  `SkillExecutionPlan`/`SkillOutcome`/`SkillCheckTask` contracts with
  offline utility priors, fail-closed capability admission, alternative and
  degraded outcomes, real verification-hook task materialization, Evidence
  consumption, and failure-signal fallback/replan transitions.  V3 method
  packages now pass a content quality gate with Solver/Verifier-specific
  projections, and Skill-specific benchmarks require positive, negative,
  adversarial, selection, and ablation coverage with paired observable
  scoring.  Added E3 invariant and regression tests.
- Completed E2 Prompt and Structured Output reduction work. Added the
  Host-owned `ModelSemanticPayload` boundary and minimal Candidate profiles,
  an additive `AgentTurnPayload 1.1-lite` parser/wrapper with P0/P1 metrics,
  and a config-gated simple-task direct-Candidate path that skips progress
  artifacts. Compiled prompts now expose answer-free golden snapshots bound to
  contract/version and hash metadata, while CallBudget and RunMetrics report
  contract, runtime-protocol, skill, state, problem, and schema token costs.
  Added E2 invariant, golden, compatibility, and end-to-end regression tests.
- Completed E1 Source-of-Truth and protocol-consistency work. Prompt versions
  now come directly from contract frontmatter; ActionRegistry owns declared
  role/phase actions, prompt enums, and Host routing checks; all model-facing
  condition views use one immutable ProblemConditionEnvelope; the legacy Skill
  selector path is an alias of the canonical implementation; Provider protocol
  admission is fail-closed for invalid, stale, unknown-role, and missing-
  artifact turns; and internal failures are classified for precise metrics and
  test/competition handling. Added E1 invariant and regression coverage.
- Completed E0 evidence-freeze and characterization work.  Benchmark and
  per-case manifests now carry a complete current-run identity (commit,
  competition configuration, Prompt/Skill/Tool, dataset, model, Python, and
  platform fingerprints); baseline validation fails closed for missing,
  dirty, historical, or non-comparable evidence.  Formal competition runs
  enforce the 900-second outer limit, while 1200-second debug runs are
  explicitly labelled non-comparable.  Added deterministic one-primary-cause
  failure attribution and a reproducible workflow characterization test.
- Completed the 2026-08-25 remediation Phase 9 Provider/timeout/resource
  work.  Stage timeout is now the actual caller-visible boundary with only a
  100 ms tail grace; late physical calls are bounded, case-isolated, and
  released from provider finally paths.  Scheduler waves propagate the case
  cancellation token, invalidate pending generations on timeout, and shut
  down their executor in finally so late workers cannot commit stale state.
  Competition remains at case concurrency 3, model concurrency 6, RPM 200,
  and a three-attempt weighted reservation; background tails are capped at
  six.  Standard/compact Solver P95 reservation was recalibrated to 180 s
  from the archived canary distribution while proof output remains at the
  40K-token / 240 s safety envelope.  Added boundary, isolation, cancellation,
  generation-fence, and resource-release regression coverage.
- Completed the 2026-08-25 remediation Phase 8 Skill/Context/Memory work.
  The legacy and V3 Skill selectors now share one implementation.  Skill
  packages undergo Host capability admission, declared verification hooks are
  converted into a bounded check plan, and AlternativeSolver receives the
  declared alternative method branch.  References are disclosed only on an
  explicit selected-Skill request and carry source hashes.  Role Contexts now
  record and enforce token budgets alongside character budgets while preserving
  an explicit non-compressible core.  Memory is either disabled or receives
  only bounded Host-approved route/evidence summaries.  Skill ablation now
  requires real paired ON/OFF observations, derives correctness from outputs,
  and reports Wilson confidence intervals, unpaired cases, and failure strata;
  manual `skill_on_correct` labels are rejected.  Added Phase 8 admission,
  reference, context, memory, and paired-evaluation regression coverage.
- Completed the 2026-08-24 remediation Phase 7 verification-closure work.
  Evidence, proof obligations, repair transactions, version-matched audits,
  completion status, arbitration, and public trace now share one
  `VerificationClosure` snapshot.  Final Audit is followed by a fresh
  closure recomputation; repaired candidates carry version and transaction
  state, unsupported reasoning checks emit explicit unknown evidence, and
  proof-full candidates cannot become complete without mapped public
  derivation.  Arbitration now gates hard failures and ranks closure,
  derivation quality, parse tier, degradation, and coverage before a digest;
  substantive ties expose a targeted-check requirement instead of claiming
  that a hash is mathematically superior.  Added closure, audit-version,
  unknown-evidence, ranking, and trace regression coverage.
- Completed the 2026-08-24 remediation Phase 6 candidate cross-review and
  independence work. CandidatePool and runtime review selection now preserve
  every candidate by `candidate_id`/`branch_id`, including multiple
  `AlternativeSolver` branches. Three-candidate runs expose a directed,
  conflict-aware coverage graph and per-candidate review coverage. Independence
  evidence now records Prompt, Skill, model, shared/branch context, lemma
  disclosure, execution, method, and tool-evidence dimensions; same-model
  agreement is labelled correlated corroboration rather than independent
  proof. Peer-review payloads include bounded Claim/Step-linked segments and
  real obligations, while rebuttal traces explicitly prohibit silent answer
  mutation. Failed reviewer turns are surfaced as coverage gaps without
  fabricating reviewed status or discarding otherwise eligible candidates.
  Scheduler startup ordering is deterministic for the first branch while the
  remaining review/exploration tasks stay in the bounded parallel wave. Added
  Phase 6 graph, provenance, coverage, and regression gates.
- Completed the 2026-08-24 remediation Phase 5 long-horizon policy work.
  Solver exploration now reserves time by bounded parallel waves instead of
  serially charging every branch, while the 48-call hard fuse remains active.
  Competition long-horizon runs apply a medium-risk floor after Router
  dispatch, preserve high-risk three-branch recovery, and keep every extra
  Turn observable through obligation/evidence deltas.  Generic post-candidate
  Lemma calls are skipped when no concrete unresolved obligation exists;
  explicit Solver requests and verified obligation-driven expansion remain
  supported.  Added parallel-reserve, progress-delta, and long-horizon
  regression gates, and refreshed build/review provenance fingerprints.
- Completed the 2026-08-24 remediation Phase 4 executable TaskGraph work.
  Task nodes can now bind host operations without leaking callables into the
  public graph, dependency-ready waves are grouped deterministically, optional
  nodes are pruned and rewired before admission, and bounded-worker P95 is
  estimated from the actual scheduler capacity.  Scheduler generations reject
  late results, graph runs expose terminal node states, and autonomous Solver
  exploration and candidate synthesis now use the same scheduler wave service
  with public state transitions and parallelism evidence.  Added graph binding,
  pruning, worker-P95, generation-token, and execution regression gates.
- Completed the 2026-08-24 remediation Phase 3 least-privilege and real-Agent
  communication work. Added an executable role/task-phase permission matrix
  for Artifact reads and writes, Actions, inbound message consumption, and
  outbound message types. Router plans are broadcast to every admitted Solver,
  dynamically created Solver branches receive the active PlanArtifact, and a
  Solver's first Turn cannot run without consuming it. Replans now remain
  paused until each live Solver explicitly acknowledges the new version;
  publication no longer fabricates ACKs, and stale Solver Turns cannot commit.
  `send_message` now requires one supported business routing intent. Mailbox
  delivery is phase-filtered so concurrent reviews cannot leak an unrelated
  branch's pending Artifact into a Turn. Shared and branch context hashes are
  computed from the exact public payloads dispatched to Solver branches and
  carried into Candidate provenance. Agent lifecycle projection now follows a
  single Host sequence instead of regrouping events by object type, and Prompt
  versions are loaded from contract frontmatter rather than hard-coded. Added
  permission-overreach, candidate-isolation, plan-consumption, message-routing,
  explicit-replan-ACK, stale-Turn, context-hash, temporal-order, and contract-
  version regression gates.
- Completed the 2026-08-24 remediation Phase 2 Turn/Candidate protocol work.
  Each compiled model Turn now names one authoritative output schema. Candidate
  wire profiles are selected only from ProblemIR response mode: answer-only
  uses an exact answer plus semantic check, worked solutions use ordered
  semantic steps, and proofs require at least two complete proof steps. Models
  provide mathematical statements, prior-step references, and claim kinds;
  the Host assigns Candidate, Claim, MethodStep, Progress, lifecycle, version,
  branch, and Artifact identifiers. Progress Turns accept semantic deltas only
  and reject model-created IDs, status, version, provenance, or check specs.
  Prompt examples and Candidate validators now share the same executable
  profile definitions, while repeated answer-first, optional-exposition, and
  boxed-answer rules were removed. Truncated autonomous responses are parsed
  before answer salvage so complete public derivations survive; answer-only
  salvage no longer invents a fake reasoning step. Repair patches may cite
  existing Host Claim IDs without reassigning them, and finalization uses its
  own two-field presentation schema. Added response-profile, Host-ownership,
  semantic-delta, schema-generation, 20-case contract-probe, repair-lineage,
  truncation, and proof-delivery regression gates.
- Completed the 2026-08-24 remediation Phase 1 ProblemIR and public-answer
  contract work. Replaced the line-start-only option regex with a bounded
  Choice Scanner that recognizes reliable inline and line-based A-H sequences
  while retaining the complete stem and original problem. ProblemIR 2.2 now
  records target, answer-type, and response-mode confidence, dimension-specific
  conflicts, and the deterministic Router-disambiguation decision. Low-
  confidence routing receives the exact original statement plus public parser
  uncertainty instead of a shortened target. Normal, candidate-salvage, raw-
  salvage, terminal fallback, public projection, and outer entry recovery now
  share bare-answer canonicalization; successful proof-full formatting retains
  its complete public proof steps and conclusion. Added inline English/Chinese,
  false-positive, schema round-trip, Router prompt, response-profile, and JSON-
  serialization gates. The 112-case boundary set was also checked read-only:
  all 28 labeled choice cases were detected with no false choice promotions.
- Implemented the 2026-08-24 remediation Phase 0 evidence freeze and official
  case-audit gate. The frozen candidate now records the clean parent commit and
  config, Prompt, Skill, and 171-file competition-source fingerprints. The
  supplied official log is retained only as aggregate diagnostic evidence
  because its commit is unavailable locally and it lacks current fingerprints
  and per-case lineage; no active baseline was fabricated. Added a strict
  ten-label case taxonomy, complete model-call timelines, Candidate lineage,
  deterministic non-proof scoring, independent two-review proof adjudication,
  and activation gates for official origin, exact fingerprints, complete
  records, and trace/call/candidate lineage.
- Completed the 2026-08-11 audit remediation Phase P4 runtime-slimming work
  while retaining the required LLM Router. Competition no longer runs the
  optional deterministic shadow path, and disabled RAG, frozen-lemma, MCP, and
  shadow implementations are lazily loaded instead of entering startup. The
  judge-trace module is now a small stable public facade over its private,
  behavior-compatible projection implementation. Critical provider exception
  handling was narrowed to expected protocol failures, while the sole broad
  online transport boundary remains classified and attributed; response-
  observer failure is also captured in model-call lineage. Documented and
  tested that zero internal trace limits defer to a 4,096-event hard safety
  ceiling plus the separately bounded judge projection rather than enabling
  unbounded output.
- Completed the 2026-08-11 audit remediation Phase P3 concurrency and circuit-
  breaker work without changing the global physical limit of six concurrent
  model calls or the 200 RPM ceiling. Provider transport health, background
  tails, circuit state, and protocol counters are now isolated per case and
  released at terminal cleanup. Four consecutive transport failures open only
  that case's circuit; after a 60-second cooldown exactly one half-open probe
  is admitted. Tail degradation now requires more than half of physical model
  concurrency, while the Competition tail threshold is 24. All Competition
  stage start windows are 30 seconds and tight-deadline queueing receives a
  bounded positive budget above that reserve. A response arriving after its
  stage timeout but before the case model deadline is retained instead of
  discarded, and a completed response beyond the estimated context window is
  returned with warning telemetry. Added focused isolation, recovery, tail,
  queue, late-result, and context-warning regression gates.
- Completed the 2026-08-11 audit remediation Phase P2 contract and answer-
  extraction work without removing or bypassing the LLM Router. Model candidate
  output now requires only `final_answer` and `solution_text`; optional method,
  step, Claim, theorem, assumption, and obligation data receives deterministic
  Host defaults. Candidate prompts use a compact two-field JSON protocol and
  put a JSON-escaped `\boxed{...}` answer first. Removed ineffective reasoning-
  suppression instructions while keeping non-answering roles free of answer
  directives. Added one parsing-entry `<think>` policy: closed blocks are
  removed and unclosed blocks are marked truncated with answer-only salvage.
  Parsing, evaluation, and verification now share an arbitrary-depth boxed-
  answer scanner, and unknown Claim check suggestions normalize to `reasoning`.
  Added focused gates for nested LaTeX, Router JSON after closed thinking,
  truncated-think salvage, minimal candidate defaults, and check normalization.
- Completed the 2026-08-11 audit remediation Phase P1 truncation work without
  removing the LLM Router. Competition stage ceilings now range from 8,192
  Router tokens through 40,960 proof tokens, with solver timeouts raised to
  420 seconds while preserving the 850-second case deadline. Removed the
  misleading global `primary_max_tokens` override so stage policies are the
  effective source of truth. The string-only official client path now infers
  length truncation from token proximity, incomplete JSON/think blocks, and
  incomplete endings. Solver candidate Turns salvage complete answers before
  issuing one 2,048-token answer-only retry, record retry telemetry, and retain
  recovered Candidates with explicit degraded assurance. Truncated JSON
  prefixes containing an answer are non-fatal and round-trip with a degraded
  Candidate marker. Added focused detection, recovery, retry, and policy gates.
- Completed the 2026-08-11 audit remediation Phase P0 deliverability work
  without removing or disabling the LLM Router. Terminal failure paths now
  return a gradeable `\boxed{0}` instead of explanatory prose, preserve
  bounded per-case raw model responses for answer salvage, and recover boxed,
  JSON `final_answer`, Chinese, and English labeled answers from complete or
  truncated output. Public result projection now trims oversized answers while
  retaining the latest recoverable answer, replaces invalid trace bookkeeping,
  and never discards a non-empty answer because trace or byte-budget validation
  failed. Added a 20-scenario deliverability gate and refreshed the affected
  engineering-review fingerprints.
- Completed the 2026-08-09 remediation Phase 10 Production Preflight and
  Release Governance work. The batch runner now reports distinct L0 Client,
  L1 raw JSON, L2 AgentTurn, L3 authoritative Router, L4 Solver Candidate,
  and L5 optional Verifier checks; a failure is attributed to the first exact
  layer and reports only a safe code. Added a release-governance manifest with
  Competition, Prompt, Skill, evidence-registry, content-review, and test-
  attestation identities. `validate_submission` remains the development/
  package check, while `validate_release --strict` additionally requires an
  active fingerprint-verified baseline from the clean release commit, all
  tests, human review, and a frozen Competition config. The current profile
  truthfully remains `candidate-unvalidated`, so strict release is expected
  to stay blocked until Phase 11/12 evidence and signatures exist.
- Completed the 2026-08-09 remediation Phase 9 Scheduler / Runtime
  modularization work. Added a validated TaskNode DAG with dependency and
  cycle checks, critical-path p95 calculation, bounded Solver and Review
  waves, and stateless atomic closure admission for repair/reverification.
  The autonomous Primary/Alternative candidate synthesis and bidirectional
  Solver review paths now use the extracted SchedulerFlow while the global
  provider continues to enforce case concurrency 3, model concurrency 6,
  per-Agent inflight 1, and 200 RPM. Model-call records now carry action and
  scheduler task identities and expose deterministic accounting grouped by
  role, action, task, and terminal status. Added Phase 9 gate coverage for
  DAG integrity, parallel overlap, closure isolation, call accounting, and
  frozen resource boundaries.
- Completed the 2026-08-09 remediation Phase 8 Review / Repair /
  Communication / Audit work. Concrete Message recipients are now reused by
  downstream model Turns, consumed Artifact references produce bounded
  `message_consumed` receipts, and the protocol reports a deterministic
  recipient/called integrity check. Bidirectional Solver review now requires
  two independent Candidates with incremental review value. Concessions are
  severity-aware: warnings remain challenged, local errors request repair,
  and only confirmed global critical findings reject. Added the five-class
  repair taxonomy, explicit detect-to-commit/rollback transaction lineage,
  and global-failure new-branch enforcement. Final Audit now carries positive
  reviewed Finding/obligation coverage, enforces required Artifact/Finding/
  obligation sets, rejects stale Candidate versions, and cannot commit a
  Decision from an incomplete or stale Audit. Added focused Phase 8 regression
  coverage for all five gates.
- Completed the 2026-08-09 remediation Phase 7 Verification V2 work.
  Host-selected conclusion Claims now define a transitive critical dependency
  closure, required obligations without a real Claim remain explicitly
  `unmapped_required_obligation`, and compatible hard evidence is evaluated
  only inside that closure. Added the ordered assurance taxonomy
  (`candidate_valid` through `formally_verified`), terminal-closure metadata,
  public assurance fields, and deterministic arbitration gating. Verifier LLM
  findings and audits cannot manufacture `formally_verified`; a formal level
  requires an explicit deterministic formal engine capability. Legacy proof
  status strings remain wire-compatible but no longer imply V2 hard
  verification. Added regression coverage for unknown Claims, missing
  mappings, peripheral evidence, compatible obligation support, and LLM/audit
  limits.
- Completed the 2026-08-09 remediation Phase 6 ReasoningState V2 work.
  Claims now carry lifecycle status, monotonically increasing versions,
  supersession links, evidence references, provenance, and branch identity.
  Tool evidence transitions active claims to supported, verified, or
  challenged states and contributes to information gain. Semantic GC keeps
  only the branch-local active frontier, compacts stale rounds and tool
  payloads, and the compressor emits an active-frontier projection with
  dependency and evidence invariants. Twenty-four-round synthetic stress
  coverage verifies bounded context growth and supersession behavior.
- Completed the 2026-08-09 remediation Phase 5 Router/Host/Agent governance
  work. RouterIntent and the compatibility AuthoritativePlan now pass through
  explicit HostAdmittedPlan and EffectiveExecutionPlan layers, with fanout,
  Agent tasks, model-call lineage, plan versions, and replan ACK barriers tied
  to the effective plan. Added a unified least-privilege ActionRegistry,
  branch-local override validation, post-backbone-only shared provisional
  lemmas, four-dimensional Candidate independence and public branch
  provenance. Non-independent Candidates remain viable corroboration rather
  than being rejected, and concessions request severity-scoped repair unless
  later evidence confirms a global critical failure.
- Completed the 2026-08-09 remediation Phase 4 standard Skill Package and
  Math Skill V3 work. Added a read-only V3 package schema and loader alongside
  the validated V2 compatibility adapter, 51 high-frequency method packages,
  pattern-aware Top-K selection, tuple-safe subject matching, role-specific
  progressive disclosure, bounded references/assets, and ToolRegistry-only
  capability authorization. Added explicit selection precision/recall, token
  increment, and Skill ON/OFF contract-canary metrics; these results are
  labeled synthetic and do not claim real-set accuracy improvement.
- Completed the 2026-08-09 remediation Phase 3 provider, timeout, health, and
  cancellation repair. Effective call timeouts are now bounded by the
  configured stage window, the 165-second injected-client delivery window,
  and the remaining per-problem deadline, with all three values retained in
  call telemetry. Worst-case RPM reservations reconcile downward only when
  physical attempt counts are observable; connect/429/5xx remain the only
  same-branch fast-retry classes and read timeouts do not retry blindly.
  TransportHealth, ProtocolHealth, and CognitiveHealth are reported
  separately, and only transport failures influence the provider circuit.
  Added cooperative CancellationToken propagation from the wall-clock runner
  through Harness, resource governance, Agent Runtime, and Provider so a
  timed-out case cannot admit new tasks or model calls and late in-flight
  results are discarded without cross-case health pollution. Runtime shutdown
  now records unfinished work as cancelled, aborted, or deadline-expired
  instead of rewriting it as completed.
- Completed the 2026-08-09 remediation Phase 2 candidate-availability and
  gradeability repair. Every routed problem now starts with independent
  PrimarySolver and AlternativeSolver branches, missing backbone Candidates
  receive bounded compact replacement attempts, damaged AgentTurn envelopes
  can recover answer-only Candidates with explicit assurance degradation, and
  an emergency direct PrimarySolver path prevents ordinary branch failures
  from collapsing into zero Candidates. Final responses now pass a production
  formatter-to-scorer round trip, including text and choice wrapper
  normalization, before release. These recovery paths reuse the adaptive
  problem budget and do not introduce a six-call ceiling or raise the global
  call/token limits.
- Completed the 2026-08-09 remediation Phase 1 prompt and structured-output
  protocol repair. Production prompts now compile from one contract-backed
  source of truth, RouterPlanner emits only minimal routing intent while the
  Host owns plans and task graphs, and Solver output uses bounded simple,
  standard, or proof profiles. Added shared ordered JSON recovery, JSON/LaTeX
  lexical validation, semantic AgentTurn salvage with assurance degradation,
  and per-call protocol/truncation telemetry. Host-owned workflow fields are
  rejected at the model boundary, and the model preflight now exercises the
  2048-token simple protocol rather than requesting the former 8192-token
  payload.
- Completed the 2026-08-09 remediation Phase 0 evidence freeze. Added a
  final-corpus aggregator that keeps resumed attempt diagnostics separate from
  the authoritative one-record-per-case corpus, a causal failure taxonomy,
  hashed local-88 and official-112 evidence, and redacted id=7/id=77
  regressions. The baseline now automatically reproduces 49/88 correct, 38
  `all_candidates_failed`, Router 0/88 accepted, 10/88 dual Candidate, 92/112
  official invalid, and 444/657 truncated.
- Completed true multi-Agent remediation Phase F7. Proof completion now has
  exactly four public states (`complete_hard`, `complete_audited`,
  `incomplete`, and `failed`); a repaired Candidate cannot complete without a
  version-matched Final Audit, and `proof_full` cannot complete without public
  proof steps. Extracted deterministic session-contract, Agent-event, and final
  proof services from the runtime facade. Removed the legacy
  `CallAllocationPlan`, stage quotas, fixed planned-round policy, and runtime
  Blackboard write paths; all roles now share the adaptive 48-call problem
  bound with an eight-call closure reserve. Judge Trace now projects Agent,
  Task, Turn, Artifact, Message, repair, audit, decision, and shutdown events
  without raw responses or private reasoning, and explicitly records the
  immutable formal-entry status limitation. Added F7 proof, lifecycle,
  resource-cleanup, privacy, and public-contract regression coverage.
- Completed true multi-Agent remediation Phase F6. VerifierSkeptic now runs
  independent `cross_exam` Turns over CandidatePool, Solver Peer Reviews,
  Rebuttals, Evidence, and Proof Obligations, publishes strict Claim-linked
  CritiqueArtifacts, and performs second-order assessment of every Peer
  Finding. Claim-local failures may enter a Critique-parented RepairAgent model
  Turn followed by deterministic re-verification and a fresh Verifier Turn;
  evidence regressions roll back. Global method failures instead trigger an
  authoritative Router replan and a new Solver branch that re-enters Solver
  Peer Review. A distinct Verifier instance audits only the tentative final
  Candidate, incomplete audits may re-enter the closure loop, and deterministic
  arbitration commits a service-authored DecisionArtifact parented to the final
  Candidate and available Audit. The Competition profile enables F6 inside the
  existing 48-call adaptive bound, three-case concurrency, and 200 RPM gate.
- Completed true multi-Agent remediation Phase F5. Added a per-problem
  CandidatePool with author/Turn/Artifact lineage, measurable MethodSignature
  fields (`representation`, `core_invariant`, and `proof_direction`), and a
  structural gate that rejects same-author, same-call, or substantively
  duplicate candidates. After both independent Candidates publish, isolation
  is released into two explicit review threads: PrimarySolver reviews the
  Alternative and AlternativeSolver reviews the Primary in separate model
  calls, then each author answers the resulting Claim-linked Findings in a new
  rebuttal model Turn. Review and Rebuttal Artifacts, Task/message/thread
  lineage, no-new-content close/reopen rules, Candidate concession state, and
  downstream candidate filtering/conflict targets are now auditable in Trace.
  The Competition profile enables this bounded F5 closure path; F6 Verifier
  cross-exam, repair/new-branch policy, and final audit remain out of scope.
- Completed true multi-Agent remediation Phase F4. PrimarySolver and
  AlternativeSolver now run isolated, independently stateful Agent Action
  loops without fixed planned rounds; public information gain, repeated
  Artifact hashes, the 48-call ResourceGovernor, deadlines, and explicit
  `complete`/`abstain` Actions govern continuation. Activated an independent
  LLM LemmaCurator for every autonomous solve and request/reply wake-up,
  connected Host-executed Tool and versioned Router replan requests, and added
  typed 4096 Progress, 8192 standard/compact Candidate, and 12288 proof Turn
  contracts. `finish_reason=length` now creates a partial Artifact and a fresh
  compact-synthesis Turn; unsupported proof output degrades visibly to 8192.
  Added F4 protocol, autonomy, isolation, abstention, token, truncation, and
  long-horizon regression tests. Peer review and rebuttal remain Phase F5.
- Completed true multi-Agent remediation Phase F3. Production profiles now
  require an independent RouterPlanner model call before every Solver call.
  Router output contains a validated route, method families, acyclic subgoal
  DAG, and Agent task proposals; its Plan ID, subgoals, and method assignment
  causally bind subsequent Solver tasks and prompts. Added authoritative
  Route/Plan Artifacts, versioned replan inheritance, explicit rule-engine
  fallback reasons, production-config guards, and F3 ordering/DAG/replan tests.
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
## 2026-08-13 - Public final response and reasoning-trace contract

- Changed non-proof `final_response` values to the canonical answer only, without
  a `Final answer:` label, outer math delimiters, or derivation text.
- Preserved public proof steps and the conclusion in proof-mode
  `final_response` values.
- Added an official `{step, content}` trace projection covering planning,
  reasoning, candidate comparison, cross-review, verification, repair,
  arbitration, model-call summary, and finalization while retaining Judge Trace
  V4 internally.
- Added conservative Chinese proof/justification markers for `求证`, `论证`,
  `说明为什么`, and `说明为何`.
- Updated case-output validation, public-output documentation, and contract
  tests for the new boundary.
