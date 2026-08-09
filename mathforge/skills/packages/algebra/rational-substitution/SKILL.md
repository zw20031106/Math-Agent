---
name: rational-substitution
version: 3.0
domain: algebra
subdomain: equation
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: substitute, rational equation
problem_patterns: rational equation, denominator
method_family: rational-substitution
alternative_skills: polynomial-factorization
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the problem exposes rational equation, denominator.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
A substitution is valid only on the domain where it is invertible or branches are restored.

## Exact Preconditions
Record excluded denominator zeros before transforming.

## Procedure
Choose a repeated rational subexpression then solve and back-substitute.

## Branch Conditions
Branch over every inverse image of the substitution.

## Failure Modes
Clearing denominators can introduce excluded solutions.

## Counterexample Patterns
Test every denominator-zero point separately as excluded.

## Verification Recipe
Back-substitute each candidate into the original equation.

## Mini Example
For x+1/x=t require x nonzero and solve x^2-tx+1=0.

## Alternative Strategy
Clear denominators with explicit domain filtering.

## Stop / Escalate Conditions
Escalate when inverse branches cannot be enumerated.
