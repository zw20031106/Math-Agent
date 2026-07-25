---
name: general-math
subject: general-math
kind: domain
version: 2.0
triggers: no dedicated subject trigger, mixed unknown problem, general mathematics
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Use only when no registered subject trigger explains the problem or when a
mixed problem cannot be safely assigned.

## Roles

Solvers take a conservative direct route; Verifier challenges assumptions;
Repair patches only evidenced local failures.

## Method decision tree

Restate the target, identify definitions and domains, try direct deduction or
constructive computation, and keep unresolved obligations explicit.

## Theorem preconditions

Name every theorem and its hypotheses; do not infer unstated subject-specific
conventions.

## Common errors

Do not invent a theorem, silently choose a domain, or force a familiar answer
type from an input object.

## Counterexample checklist

Test boundaries, degeneracies, alternate interpretations, and the smallest
admissible cases.

## Compatible check types

Use `reasoning`, `definition`, `theorem_preconditions`, `boundary`, and
`answer_type_check`.

## Answer normalization

Match the explicit target and state any unavoidable convention or unresolved
ambiguity.

## Trace step guidance

Record the general-math fallback reason, chosen interpretation, public steps,
checks, and final answer.
