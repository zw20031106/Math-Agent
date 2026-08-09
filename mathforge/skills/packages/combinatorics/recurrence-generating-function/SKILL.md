---
name: recurrence-generating-function
version: 3.0
domain: combinatorics
subdomain: counting
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: recurrence, generating function, coefficient
problem_patterns: solve recurrence, sequence count
method_family: recurrence-generating-function
alternative_skills: bijection-counting
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the problem exposes solve recurrence, sequence count.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
Multiplying a recurrence by powers of x converts shifts into algebraic generating-function identities.

## Exact Preconditions
Initial conditions and convergence or formal-series interpretation are stated.

## Procedure
Form the generating function include boundary terms solve algebraically then extract coefficients.

## Branch Conditions
Branch by homogeneous and nonhomogeneous recurrences.

## Failure Modes
Dropping initial boundary terms yields the wrong numerator.

## Counterexample Patterns
Check the first several coefficients.

## Verification Recipe
Substitute recovered coefficients into recurrence and initial conditions.

## Mini Example
Fibonacci gives F(x)=x/(1-x-x^2).

## Alternative Strategy
Use characteristic polynomials or combinatorial decomposition.

## Stop / Escalate Conditions
Escalate when coefficient extraction has unresolved branches.
