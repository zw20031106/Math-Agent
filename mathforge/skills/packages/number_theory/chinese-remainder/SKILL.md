---
name: chinese-remainder
version: 3.0
domain: number_theory
subdomain: number theory
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: chinese remainder, simultaneous congruence
problem_patterns: system of congruences, coprime moduli
method_family: chinese-remainder
alternative_skills: modular-congruence
requires: small_case_enumeration
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: small_case_enumeration
---
## Recognition
Use when the problem exposes system of congruences, coprime moduli.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
Pairwise coprime moduli give a unique residue modulo their product; generalized compatibility uses gcd conditions.

## Exact Preconditions
Moduli and pairwise or generalized compatibility are checked.

## Procedure
Combine two congruences at a time using modular inverses.

## Branch Conditions
Branch for noncoprime compatible and incompatible systems.

## Failure Modes
Multiplying noncoprime moduli overstates uniqueness.

## Counterexample Patterns
Test residues modulo each gcd.

## Verification Recipe
Reduce the final representative in every original congruence.

## Mini Example
x=1 mod 2 and x=2 mod 3 gives x=5 mod 6.

## Alternative Strategy
Use direct substitution for two equations.

## Stop / Escalate Conditions
Escalate when any compatibility condition fails.
