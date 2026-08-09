---
name: monotonicity-partition
version: 3.0
domain: calculus
subdomain: optimization
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: monotone, increasing, decreasing
problem_patterns: monotonic intervals, derivative sign
method_family: monotonicity-partition
alternative_skills: derivative-stationarity
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the problem exposes monotonic intervals, derivative sign.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
A derivative with fixed sign on an interval determines monotonicity there.

## Exact Preconditions
Continuity and differentiability exceptions are identified.

## Procedure
Solve derivative sign changes and partition the domain.

## Branch Conditions
Branch at singularities and excluded points.

## Failure Modes
A derivative sign sampled at too few points can miss roots.

## Counterexample Patterns
Test each connected interval separately.

## Verification Recipe
Use exact sign analysis at one valid point per root-separated interval.

## Mini Example
For f=x^3-3x, f'=3(x^2-1) partitions at -1 and 1.

## Alternative Strategy
Use direct comparison or convexity.

## Stop / Escalate Conditions
Escalate when derivative roots cannot be isolated reliably.
