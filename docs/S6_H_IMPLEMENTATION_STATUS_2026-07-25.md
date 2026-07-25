# S6-H Implementation Status — 2026-07-25

## Result

E7 is implemented. The per-case execution path now has a complete,
restart-safe lifecycle from input preflight through terminal atomic output.

## Lifecycle

1. Load JSONL and reject duplicate IDs before creating an online client.
2. Validate or create `run_manifest.json`, binding the run to input/config
   SHA-256, case IDs, seed, and exact model identity.
3. Require a non-empty real response from the configured model before starting
   any case.
4. Under `--resume`, validate existing public files and their manifest hashes,
   then skip only verified cases.
5. Run each missing case under the 900-second wall-clock watchdog. The Harness
   return boundary remains 870 seconds, leaving 30 seconds for persistence.
6. Convert success, internal failure, and timeout into a non-empty result with
   terminal Trace.
7. Sync a temporary case file and atomically replace `<id>.json`.
8. Atomically update the internal manifest with output hash, latency, score,
   RunMetrics, request fingerprint, and terminal state.
9. Print and flush `CASE_COMPLETED` immediately.

The runner serializes injected official-client calls. Failures returned within
20 seconds receive bounded exponential retries; 100 seconds of the call window
is reserved for that policy, leaving a 735-second underlying HTTP timeout.
The sample client's default three 120-second attempts are not used because
they prematurely cut off long Intern-S2 generations and can outlive the
deterministic finalization boundary.

The competition `model_max_concurrency` is one. Parallel candidate tasks wait
at the Harness deadline-aware model gate and cannot create concurrent provider
bursts.

## Public/private boundary

Every case file contains exactly:

```text
id
status
final_response
trace
```

`status=success` means a primary solution was produced. Fallback and execution
failure use `failed`; the wall-clock watchdog uses `timeout`.

`run_metrics`, scoring, model identity, provenance-compatible fingerprints,
and file hashes are confined to `run_manifest.json`; no `result` wrapper is
introduced.

## Recovery and safety

- Unknown case files, unsafe IDs, invalid Schema, ID mismatches, missing
  terminal Trace, input/config changes, seed changes, and output hash changes
  fail before model execution.
- A crash after case replacement but before manifest replacement can recover
  the valid orphan output and bind its hash during Resume.
- A timeout closes the worker's shared result slot before returning the
  deterministic timeout object. A late solve return has no path to output
  persistence.
- Temporary files are removed after replacement or failure.

## Acceptance evidence

- Duplicate-ID preflight regression.
- Exact four-field success, failure, and timeout output regressions.
- Model content-preflight success and empty-response failure regressions.
- Immediate completion persistence regression with a concurrent slow peer.
- Resume and manifest-bound output hash regression.
- Invalid existing Schema and tampering rejection regressions.
- Late-result non-overwrite and wall-clock timeout regressions.
- Full repository test, compile, and immutable-baseline gates before commit.
