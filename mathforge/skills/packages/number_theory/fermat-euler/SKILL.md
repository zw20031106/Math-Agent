---
name: fermat-euler
version: 3.0
domain: number_theory
subdomain: number theory
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: fermat little theorem, euler theorem, totient
problem_patterns: large exponent modulo, coprime base
method_family: fermat-euler
alternative_skills: chinese-remainder
requires: small_case_enumeration
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: small_case_enumeration
---
## Recognition
Use when the problem exposes large exponent modulo, coprime base.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
If gcd(a,n)=1 then a^phi(n)=1 mod n; Fermat is the prime-modulus case.

## Exact Preconditions
Coprimality and the modulus conditions are explicit.

## Procedure
Reduce exponents modulo the correct group exponent then compute residues.

## Branch Conditions
Branch when the base is not coprime to the modulus.

## Failure Modes
Euler reduction cannot be used through nonunits.

## Counterexample Patterns
Test bases sharing a factor with the modulus.

## Verification Recipe
Check the reduced result by modular exponentiation.

## Mini Example
2^10=1 mod 11.

## Alternative Strategy
Use CRT or cycle enumeration.

## Stop / Escalate Conditions
Escalate when factorization of the modulus is unavailable.
