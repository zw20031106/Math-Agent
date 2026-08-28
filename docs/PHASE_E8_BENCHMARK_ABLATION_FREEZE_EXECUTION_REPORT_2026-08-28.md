# E8 Benchmark, Ablation, and Freeze-Gate Execution Report

Date: 2026-08-28

## Scope

This phase implements the E8 evaluation layer without changing the immutable
official wrapper or client.  The release profile remains
`candidate-unvalidated`; a full run, even when successful, is not treated as a
freeze.

## Implemented contracts

- `mathforge/evaluation/e8.py` defines B1/B2/B3 suite contracts, W0-W8,
  S0-S3, V0-V3, and P0/P1 arm registries, the required E8 metric vocabulary,
  interleaved paired-run validation, and a fail-closed freeze gate.
- `scripts/run_e8_ablation.py` executes one arm family in interleaved repeated
  order through the existing injected-client benchmark runner.  Missing or
  failed child artifacts remain invalid evidence.
- `scripts/validate_e8_freeze.py` evaluates explicit evidence and never edits
  release manifests.
- `scripts/analyze_e8_run.py` revalidates persisted public case files and joins
  them with recorded manifest metrics; it does not infer missing scores or
  private model events.
- The benchmark loader accepts both JSONL and the official JSON-array export.
  `run_case_outputs.py --allow-invalid-expected` is an explicit diagnostic
  mode for boundary datasets containing answers outside the automatic scorer;
  those cases remain unscored.

## Deterministic checks

- E8 targeted tests: 6 passed.
- Compile check: `python -m compileall .` passed.
- Full suite replay after the E8 commit: 995 passed.
- Baseline immutability: `python scripts/verify_baseline_files.py` passed.
- Content review, build provenance, and submission validation pass after the
  E8 source fingerprint update.
- Ruff and mypy are not installed in the current environment, so their E8
  gates remain explicitly unverified.

## External evidence policy

The official 112-case boundary export is intentionally run only through the
real Intern client and is stored outside the repository under the user-specified
verification-results directory.  Its report must include the preflight
scoring coverage, per-case public-output validation, status counts, latency,
candidate availability, truncation/recovery markers, and all unscored cases.
No API credential is persisted in source or artifacts.

The E8 freeze gate requires repeated paired ablations (at least three
interleaved repetitions per arm), a resolvable baseline, complete provenance,
and human mathematical review.  Until those external conditions are present,
the gate is expected to remain blocked.

## Official boundary-run attempt

The supplied 112-case JSON-array file was loaded successfully.  Diagnostic
benchmark preflight found 64 automatically scorable cases, 27 manual/rubric
cases, and 21 invalid expected answers (automatic coverage 57.14%); the latter
were retained as explicitly unscored rather than coerced.

Three real-client attempts were made with the requested model and concurrency
3 (the last in a clean final-fingerprint subdirectory).  All passed the local
model-identity check but stopped at official model preflight L1 with
`network_connect_failure` caused by a TLS EOF while connecting to the
configured Intern endpoint.  No case was executed, so no accuracy or
model-quality claim is made.  The failure manifests and the read-only analysis
are stored in the user-specified verification-results directory; the final
analysis records 112 missing case outputs and keeps the freeze gate blocked.
