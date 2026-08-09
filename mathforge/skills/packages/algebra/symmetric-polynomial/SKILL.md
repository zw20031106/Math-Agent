---
name: symmetric-polynomial
version: 3.0
domain: algebra
subdomain: polynomial
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: symmetric, elementary symmetric
problem_patterns: symmetric expression, permutation invariant
method_family: symmetric-polynomial
alternative_skills: vieta-relations
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the problem exposes symmetric expression, permutation invariant.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
Every symmetric polynomial can be expressed using elementary symmetric polynomials.

## Exact Preconditions
Variables and coefficient ring must be fixed.

## Procedure
Identify degree then eliminate monomial symmetric terms by leading order.

## Branch Conditions
Branch by number of variables and homogeneity.

## Failure Modes
Cyclic expressions are not necessarily symmetric.

## Counterexample Patterns
Swap two variables to test symmetry.

## Verification Recipe
Substitute elementary symmetric definitions and expand.

## Mini Example
x^2+y^2=(x+y)^2-2xy.

## Alternative Strategy
Use direct factorization for low degree.

## Stop / Escalate Conditions
Escalate when the expression is only cyclic.
