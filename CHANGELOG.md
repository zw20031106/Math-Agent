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
