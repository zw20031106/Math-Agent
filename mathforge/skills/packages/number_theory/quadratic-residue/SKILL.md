---
name: quadratic-residue
version: 3.0
domain: number_theory
subdomain: number theory
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: quadratic residue, legendre, square modulo
problem_patterns: square congruence, Legendre symbol
method_family: quadratic-residue
alternative_skills: modular-congruence
requires: small_case_enumeration
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: small_case_enumeration
---
## Recognition
Use when the problem exposes square congruence, Legendre symbol.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
Quadratic reciprocity and supplement laws decide Legendre symbols for odd primes.

## Exact Preconditions
Moduli are odd primes unless a generalized symbol is explicitly used.

## Procedure
Factor the numerator then apply reciprocity and supplements.

## Branch Conditions
Branch for p=2 and composite moduli.

## Failure Modes
A Jacobi symbol of one does not guarantee a square modulo a composite.

## Counterexample Patterns
Test p=2 and zero residues separately.

## Verification Recipe
Square returned roots modulo the original modulus.

## Mini Example
2 is a residue mod 7 since 3^2=2 mod 7.

## Alternative Strategy
Use direct enumeration for small moduli.

## Stop / Escalate Conditions
Escalate for composite moduli without factorization.
