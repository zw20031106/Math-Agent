---
name: epsilon-delta
version: 3.0
domain: calculus
subdomain: limit
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: epsilon delta, continuity proof
problem_patterns: prove limit, quantify delta
method_family: epsilon-delta
alternative_skills: taylor-remainder
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the problem exposes prove limit, quantify delta.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
A limit proof must choose delta from epsilon uniformly over all admissible points.

## Exact Preconditions
The target point and punctured-neighborhood domain are explicit.

## Procedure
Factor or bound the difference then solve for a sufficient delta.

## Branch Conditions
Branch for one-sided limits and restricted domains.

## Failure Modes
Choosing delta using the variable being quantified is circular.

## Counterexample Patterns
Test boundary values at the chosen delta.

## Verification Recipe
Substitute the delta bound into the original absolute difference.

## Mini Example
For f(x)=2x, choose delta=epsilon/2.

## Alternative Strategy
Use sequential criteria or continuity theorems.

## Stop / Escalate Conditions
Escalate when local bounds require an unproved neighborhood restriction.
