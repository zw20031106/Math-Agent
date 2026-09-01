# AGENTS.md

## Repository Mission

Build a competition-grade mathematical reasoning harness around the official Intern-S client.

## Immutable Files

Never modify:

```text
main.py
llm_client.py
```

Run before every commit:

```bash
python scripts/verify_baseline_files.py
```

## Public Contract

The root `user_agent.py` must expose `ReasoningAgent`, whose `solve(problem, metadata)` method returns a JSON-serializable mapping with a non-empty `final_response` and a list-valued `trace`.

## Model Access

All model calls must use only the injected `client.chat(messages=..., temperature=..., max_tokens=...)` interface. Never create another online model client, read API keys, access client private fields, or assume native function calling.

## Thread Safety

The official runner shares one `ReasoningAgent` instance across concurrent calls. Create a new session inside every `solve()`, keep per-problem state local, keep registries and prompts read-only, and guard model concurrency with a bounded semaphore.

## Architecture Boundary

Use fixed LLM roles (`RouterPlanner`, `PrimarySolver`, `AlternativeSolver`, `LemmaCurator`, `VerifierSkeptic`, `RepairAgent`, and optional `LLMFinalizer`) with dynamic domain skills. Parsing, orchestration, budgets, context, memory, retrieval, tools, evidence, proof obligations, arbitration, formatting, trace, and fallback are deterministic services rather than agents.

## Verification and Repair

Hard evidence gates candidates before lexicographic arbitration; weighted scores are only final tie-breakers. Repair is evidence-triggered, claim-local, versioned, reverified, and rolled back when evidence quality decreases.

## Memory, Context, and Trace

Long-term stores are read-only during evaluation. Per-problem state is isolated and released after `solve()`. Compression must preserve the original conditions, hard evidence, proof obligations, final answer, and claim dependencies. Returned trace must not expose secrets, local absolute paths, raw exceptions, full failed candidates, or private reasoning transcripts.

## Tests Required Before Commit

```bash
python -m compileall .
pytest -q
python scripts/verify_baseline_files.py
```

Implement phases in order, add tests for each phase's invariants, update `CHANGELOG.md`, and use one commit per phase.
## Current Competition and Execution Invariants

The following rules supplement the earlier repository rules and are mandatory for the current competition profile:

- Active problem concurrency is exactly 2.
- Physical model-call concurrency is currently 6.
- The model request budget is 200 requests per minute.
- Standard Solver output keeps a 32K-scale upper cap.
- Proof Solver output keeps a 40K-scale upper cap.
- There is no fixed six-call-per-problem limit.
- The configured 48-call value is a safety fuse against infinite loops, not a target budget or an accuracy policy.
- Long-horizon reasoning is allowed when each additional call has an observable purpose.
- Use config/competition.json as the runtime configuration authority. Do not silently replace these values with duplicated constants.

A problem deadline must be evaluated against the actual remaining model-call window, including model-start margin and deterministic-finalization reserves. A workflow is not feasible merely because its nominal sum is below the outer platform deadline.

## True Multi-Agent Requirements

Every problem must pass through RouterPlanner, including problems that appear easy. The fixed role list defines ownership boundaries; it does not require every optional role to run on every problem.

Whenever a role is admitted by the execution plan, it must perform its own observable call through the injected client.chat interface. The Host may validate, reject, cancel, route, or summarize a role result, but may not fabricate a Solver answer, review, verification result, repair result, or Agent acknowledgement.

Downstream roles are admitted according to remaining time, unresolved proof obligations, evidence gaps, candidate conflicts, and expected information value. Enabling a role in configuration is not proof that the role was executed or useful.

## TaskGraph Is the Production Authority

TaskGraph is the only production scheduling authority:

- Every executable model stage must have a node, operation, dependencies, generation, admission decision, and terminal state.
- Ready waves must be started by SchedulerFlow using the configured worker limit.
- Exploration, synthesis, review, verification, repair, re-verification, and audit must not be started through a parallel legacy path outside the graph.
- Pruning a node must prevent its operation from running.
- Trace node states must come from actual NodeExecution state.
- Generation and cancellation fences must reject late results.
- Node P50/P95 and token caps must use the stage policy actually passed to Provider.
- Feasibility checks must use the remaining model-call window rather than only the outer hard deadline.

A legacy orchestrator may remain only as an explicitly tested migration fallback. It must not run alongside the production graph or be treated as the source of truth for trace state.

## Communication and Replan Semantics

Agent communication must change model-visible or deterministic business state:

- Router plans are versioned artifacts broadcast to the intended Solver branches.
- A required artifact must be consumed before the next relevant Prompt is compiled.
- Delivery, consumption, application, and ignoring are distinct states.
- The next model input must contain the allowed artifact summary and version.
- Generic send_message is permitted only when a deterministic business consumer exists.
- A Replan acknowledgement is valid only after a real Agent Turn reports the applied plan version and application decision.
- The Host must never auto-acknowledge a plan on behalf of an Agent.
- Stale plan versions, stale generations, and unconsumed required artifacts block result submission.
- The protocol trace must represent the actual sequence, not a synthetic success narrative.

## Candidate Independence and Arbitration

All candidates must be indexed by candidate_id and branch_id and must retain parent/version lineage.

- Review must reference real Claims, Steps, Findings, or Obligations.
- An unreviewed candidate cannot receive reviewed status.
- A rebuttal may answer a Finding but cannot silently change the answer.
- The same underlying model identity, or an identity that cannot be distinguished, is correlated evidence even when Prompt, Skill, branch, or method differs.
- Correlated agreement must never count as independent model agreement.
- Different methods establish method diversity, not independent model evidence.
- Hard evidence and a complete VerificationClosure gate candidates before model votes or weighted scores.
- Incomplete candidates cannot outrank complete candidates solely because another model reviewed them.
- A targeted_check_required marker must trigger a real targeted check; otherwise the result is explicitly incomplete or best-available.
- Hashes are only a final reproducibility order and never represent mathematical superiority.

## Long-Horizon Calls and Truncation

Long reasoning must not be reduced to a fixed six-call limit, but it must remain value-driven:

- An additional Turn must produce a new public semantic step, evidence record, closed obligation, resolved conflict, or post-repair re-verification.
- A Solver may publish a complete Candidate on its first Turn.
- Progress is optional and must not be an unconditional Progress-then-Synthesis duplicate.
- Stop decisions must account for information value, candidate coverage, closure reserve, and remaining model time.
- Truncated recovery may salvage a canonical answer, but must not fabricate derivation steps, Claims, evidence, or proof completion.
- A recovered answer without sufficient derivation or verification remains degraded or incomplete.

## Public Output and Trace Requirements

The participant result must remain a JSON-serializable mapping with id, status, final_response, and trace.

- final_response is always a non-empty string.
- trace is always a list.
- status is limited to success, failed, or timeout.
- For non-proof problems, final_response contains only the canonical final answer.
- For proof problems, final_response contains the key complete proof.
- Non-proof trace reasoning must contain genuine public solution steps; repeating the answer is not a reasoning step.
- Proof trace steps and final_response must come from the same selected candidate version.
- Cross-review and verification trace entries should show sanitized concrete differences, findings, claims, obligations, and evidence relationships, not only counts.
- Public trace must not expose private chain-of-thought, raw prompts, API keys, absolute paths, raw exceptions, or full failed candidates.

The immutable official wrapper may have a legacy status or field projection. Do not modify frozen files to hide internal failures; keep the participant contract valid in user_agent.py.

## Evidence and Release Governance

A correctness baseline is active only when it is bound to:

- a resolvable clean Git commit;
- exact config, Prompt, Skill, source, dependency, and dataset fingerprints;
- complete per-case public outputs;
- per-case model-call timeline and candidate lineage;
- non-proof automatic scoring;
- proof double review, with a third reviewer for conflicts;
- a closed run manifest and reproducible provenance.

Aggregate logs, old commits, local simulations, Fake or Scripted Clients, and incomplete artifacts remain diagnostic-only. A green unit-test suite is necessary but does not prove mathematical correctness.

Do not change competition status from candidate-unvalidated to frozen until the real FULL run, required C0-C7/component ablations, invalid/timeout/P95/cost gates, proof reviews, test attestation, and provenance checks pass. Never edit a release manifest merely to make a release validator pass.

## Configuration and Documentation Authority

- config/competition.json is the competition configuration authority.
- Stage policy, Python defaults, and documentation must not silently disagree.
- If a code default exists, test it against the loaded competition configuration.
- Historical phase reports, README text, screenshots, and attached plans do not override current code or configuration.
- Any intentional policy change must update tests, evidence fingerprints, and relevant documentation in the same phase.
- Do not put transient scores, API keys, temporary paths, or a single test's commit hash into this file.

## Phase Completion and Required Validation

A phase is complete only when implementation, invariant tests, execution report, and stated external evidence are all present. A commit message containing the word complete is not an acceptance result.

For every phase:

1. Modify only the files necessary for that phase.
2. Add tests for every new invariant.
3. Update CHANGELOG.md.
4. Distinguish code/test results from real-model or official-platform evidence.
5. Use one dedicated commit.
6. Record the commit and all relevant fingerprints before starting the next phase.

Before every commit, run:

~~~bash
python -m compileall .
pytest -q
python scripts/verify_baseline_files.py
~~~

Before a release candidate, also run:

~~~bash
python scripts/verify_content_reviews.py
python scripts/verify_build_provenance.py
python scripts/validate_submission.py
python scripts/validate_release.py --strict
~~~

Never use a trace counter, fabricated acknowledgement, synthetic model response, or manual manifest edit to claim a mathematical or multi-agent acceptance condition has passed.
