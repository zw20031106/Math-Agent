---
name: uniform-convergence
version: 3.0
domain: calculus
subdomain: analysis
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: uniform convergence, sup norm
problem_patterns: sequence of functions, interchange continuity
method_family: uniform-convergence
alternative_skills: dominated-convergence
requires: numerical_residual
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: numerical_residual
---
## Recognition
Use when the problem exposes sequence of functions, interchange continuity.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
Uniform convergence controls one index threshold for all points and preserves continuity under standard hypotheses.

## Exact Preconditions
The common domain and target function are fixed.

## Procedure
Bound the supremum norm and make it tend to zero.

## Branch Conditions
Separate compact and noncompact domains.

## Failure Modes
Pointwise convergence alone does not provide a uniform threshold.

## Counterexample Patterns
Test moving peaks or behavior at infinity.

## Verification Recipe
Compute or bound sup_x |f_n-f|.

## Mini Example
On [0,1], x/n converges uniformly to 0.

## Alternative Strategy
Use dominated convergence for integrals.

## Stop / Escalate Conditions
Escalate when the supremum is infinite or unattained without a bound.
