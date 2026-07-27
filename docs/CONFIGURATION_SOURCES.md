# Configuration sources

The formal entry has one configuration path:

```text
user_agent.ReasoningAgent
  -> mathforge.config.load_competition_config()
  -> bundled config/competition.json
```

`config/competition.json` is a fully expanded, schema-validated profile and is
the single source of truth for competition behavior. There are no environment
overrides for Harness features, MCP, concurrency, budgets, or deadlines.

`HarnessConfig()` retains conservative programmatic defaults for unit tests and
custom embedding. Those defaults are intentionally not presented as competition
defaults. `safe.json` and `balanced.json` are named local profiles. Benchmark
commands use the file passed through `--config`; they do not silently merge the
competition profile or environment settings.

The only environment inputs documented by the project are outside Harness
configuration:

- `INTERN_MODEL` is an exact-identity preflight for local benchmark runners.
- `MATHFORGE_INTERN_S2_TOKENIZER_DIR` selects an optional, hash-verified local
  tokenizer snapshot.

Any new competition setting must be added to `HarnessConfig`, fully specified in
every named profile, and covered by the configuration contract tests.
