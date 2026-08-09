---
name: convexity-jensen
version: 3.0
domain: algebra
subdomain: inequality
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: jensen, convex, concave
problem_patterns: weighted average, convex function
method_family: convexity-jensen
alternative_skills: inequality-am-gm
requires: numerical_residual
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: numerical_residual
---
## Recognition
Use when the problem exposes weighted average, convex function.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
A convex function at a weighted mean is at most the weighted function mean.

## Exact Preconditions
Weights are nonnegative and sum to one on a convex domain.

## Procedure
Prove convexity on the exact interval then apply weighted Jensen.

## Branch Conditions
Reverse the direction for concavity and split nonconvex domains.

## Failure Modes
A global second-derivative sign cannot be assumed from local behavior.

## Counterexample Patterns
Test domain endpoints and equality conditions.

## Verification Recipe
Check weights and the sign of the second derivative over the full domain.

## Mini Example
For convex x^2, ((a+b)/2)^2<=(a^2+b^2)/2.

## Alternative Strategy
Use tangent-line bounds or Cauchy-Schwarz.

## Stop / Escalate Conditions
Escalate if convexity changes inside the feasible interval.
