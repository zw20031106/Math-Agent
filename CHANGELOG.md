# Changelog

## Unreleased

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
