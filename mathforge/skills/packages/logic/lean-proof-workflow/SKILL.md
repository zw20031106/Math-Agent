---
name: lean-proof-workflow
version: 3.0
domain: logic
subdomain: formal_methods
kind: method
roles: PrimarySolver,AlternativeSolver,LemmaCurator,VerifierSkeptic,RepairAgent
triggers: Lean proof, formalize theorem, proof assistant, compile proof, theorem statement
problem_patterns: theorem-to-formal-statement, proof skeleton, tactic failure diagnosis
method_family: statement-first-formal-proof-workflow
alternative_skills: proof-theory,proof-obligation
description: Organize a statement-first, bottom-up formalization workflow while reporting honestly when no Lean host checker is available.
negative_triggers: claim of compiled proof without Lean output, informal proof only, unsupported library theorem
required_observables: formal statement, imports/context, proof skeleton, compiler evidence, remaining goals
requires: safe_parse_expression
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: safe_parse_expression
---
## Recognition
Use when a mathematical solution should be translated into a Lean-style theorem statement, dependency-aware proof skeleton, and a sequence of small goals.

## Do Not Use When
Do not report a formal proof pass from text parsing, do not invent imports or library lemmas, and do not claim compiler evidence when the Host has no Lean capability. This package is workflow guidance, not a Lean kernel.

## Core Theorem
Formal proof engineering benefits from statement first, design top-down, and prove bottom-up: fix types and hypotheses, split the target into small lemmas, and discharge goals with mechanically checked evidence. Without a compiler/kernel result, formal validity is unresolved.

## Exact Preconditions
Freeze the theorem statement, universes/types, imports, notation, and assumptions. Record the expected Lean version and the exact checker output when available. If no Lean tool is registered, mark the formal-verification obligation `unsupported` before producing any claim.

## Procedure
1. Write and review the smallest complete statement before tactic search.
2. Build a proof skeleton whose holes correspond to named mathematical obligations.
3. Prove bottom-up, keeping each lemma’s assumptions and output types explicit.
4. Run the configured checker only through an approved Host capability and preserve its evidence/version.
5. Translate compiler failures into claim-local repairs; re-run after each material change and never hide an unsolved goal.

## Branch Conditions
Separate elaboration/type errors, missing imports, tactic failures, false statements, and resource/time failures. A successful parser check closes syntax only; a compiler/kernel check is required for a formal proof claim.

## Failure Modes
Overly broad statements, implicit coercions, circular lemmas, brittle automation, unreported `sorry`/holes, and a proof script copied from a different library version.

## Counterexample Patterns
Try an empty type, a missing nonzero hypothesis, a coercion from naturals to integers, and a theorem whose informal statement is stronger than its formal one. Check that every admitted hole is visible.

## Verification Recipe
Host verification currently has only `safe_parse_expression`, which checks restricted syntax/grammar and is not a Lean checker; it is supporting syntax evidence only and cannot prove theorem meaning or kernel acceptance. If no Lean capability is available, final status must be `unsupported` or `incomplete`, never formally verified.

## Mini Example
First state `theorem add_zero (n : Nat) : n + 0 = n`. Then create the one-line proof obligation and record actual checker output. A parsed string without a Lean run is not evidence of compilation.

## Alternative Strategy
Keep an informal proof with explicit obligations and use proof-theory for rule auditing. Defer formalization until the required Host capability is provisioned.

## Stop / Escalate Conditions
Escalate when the statement or imports are unstable, a goal remains unsolved, compiler evidence is absent, or the user asks to convert syntax support into a formal correctness claim.
