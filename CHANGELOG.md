# Changelog

## Unreleased

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
