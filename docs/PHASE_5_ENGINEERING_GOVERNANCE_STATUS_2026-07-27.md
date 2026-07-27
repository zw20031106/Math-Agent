# Phase 5 engineering and governance status

Date: 2026-07-27

## Implemented

- Proof, Evidence, and Candidate services are reached through typed Stage
  boundaries while the orchestrator retains topology and state transitions.
- Disabled RAG and Finalizer components are not constructed. MCP remains a
  lazy opt-in inside `ToolExecutor`.
- Formal Provenance avoids Git worktree inspection and redundant registry
  construction; local benchmark metadata explicitly opts into Git inspection.
- The formal entry loads only the bundled competition profile, with no Harness
  environment override.
- The baseline manifest separates official immutable files from the mutable
  participant entry, and secret scanning covers tracked plus nonignored
  untracked files with digest-scoped allowlisting.
- PEP 621 metadata installs `user_agent`, all MathForge packages, prompts,
  Skills, configuration, data, the knowledge database, and review metadata.
- The authoritative CI gate is Ubuntu/Python 3.10 and includes a runtime
  network-denial smoke using only an injected fake official client.
- Documentation distinguishes the formal entry, safe single-case batch runner,
  and immutable legacy fixtures.

## Deliberate boundaries

- Public `ReasoningAgent.solve()` and output schemas are unchanged.
- The solve topology was not rewritten and no workflow/DAG framework was
  introduced.
- `main.py` and `llm_client.py` remain unchanged.
- Competition status remains `candidate-unvalidated`; Phase 6 model evidence
  and human review are still required before freezing.
