---
name: modular-congruence
version: 3.0
domain: number_theory
subdomain: number theory
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: congruence, modulo, residue class
problem_patterns: solve modular equation, divisibility
method_family: modular-congruence
alternative_skills: chinese-remainder
requires: small_case_enumeration
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: small_case_enumeration
---
## Recognition
Use when the problem exposes solve modular equation, divisibility.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
Congruence modulo n means the difference is divisible by n.

## Exact Preconditions
The modulus is a positive integer and cancellation conditions are checked.

## Procedure
Normalize residues then use gcd-aware linear congruence rules.

## Branch Conditions
Branch when coefficients are not invertible modulo n.

## Failure Modes
Cancellation without coprimality can lose solutions.

## Counterexample Patterns
Test composite moduli and zero divisors.

## Verification Recipe
Substitute every residue class into the original congruence.

## Mini Example
3x=1 mod 5 gives x=2 mod 5.

## Alternative Strategy
Use Chinese remainder or valuations.

## Stop / Escalate Conditions
Escalate for nonlinear congruences without a complete residue argument.
