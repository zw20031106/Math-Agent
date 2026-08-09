---
name: polynomial-factorization
version: 3.0
domain: algebra
subdomain: polynomial
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: factor, roots, zero product
problem_patterns: polynomial roots, factor polynomial
method_family: polynomial-factorization
alternative_skills: quadratic-completion
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the problem exposes polynomial roots, factor polynomial.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
Factorization is equivalent to locating roots with multiplicity over the chosen field.

## Exact Preconditions
State the coefficient field and verify degree preservation.

## Procedure
Extract common factors then apply identities or root tests recursively.

## Branch Conditions
Branch by coefficient field and repeated-root evidence.

## Failure Modes
A factorization over complex numbers may not exist over reals or integers.

## Counterexample Patterns
Test irreducible quadratics and repeated factors.

## Verification Recipe
Multiply factors back and compare normalized coefficients.

## Mini Example
x^2-5x+6=(x-2)(x-3).

## Alternative Strategy
Use gcd with the derivative or Vieta relations.

## Stop / Escalate Conditions
Escalate when the intended coefficient field is unspecified.
