# Configuration sources

The formal entry has one configuration path:

```text
user_agent.ReasoningAgent
  -> mathforge.config.load_competition_config()
  -> bundled config/competition.json
```

`config/competition.json` is a fully expanded, schema-validated profile and is
the single source of truth for competition behavior. There are no environment
overrides for Harness features, MCP, candidate concurrency, budgets, or
deadlines. The frozen outer runner has its own immutable dispatch setting, but
`ReasoningAgent` enforces the effective maximum of four active cases.

`HarnessConfig()` retains conservative programmatic defaults for unit tests and
custom embedding. Those defaults are intentionally not presented as competition
defaults. `safe.json` and `balanced.json` are named local profiles. Benchmark
commands use the file passed through `--config`; they do not silently merge the
competition profile or environment settings.

The candidate competition timing boundary is fully explicit: 900 seconds at
the outer per-case runner, 850 seconds at the Harness hard deadline, a
600-second soft cutoff, a 720-second exploration cutoff, and a 50-second
deterministic terminal/serialization margin. The profile also explicitly
enables the local deterministic Shadow registry and the reviewed, runtime
read-only Frozen Lemma Store. Neither feature reads model settings or writes
cross-case state during `solve()`.

Local runner inputs outside Harness configuration are explicit CLI arguments:

- `--model intern-s2-preview-397b` selects and validates the exact local model.
- `--concurrency 4` selects one to four active cases and defaults to four.

The only optional environment input documented outside the official client is:

- `MATHFORGE_INTERN_S2_TOKENIZER_DIR` selects an optional, hash-verified local
  tokenizer snapshot.

Any new competition setting must be added to `HarnessConfig`, fully specified in
every named profile, and covered by the configuration contract tests.
