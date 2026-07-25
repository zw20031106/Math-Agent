---
name: number-theory
subject: number-theory
kind: domain
version: 2.0
triggers: prime, divisibility, congruence, valuation, integer, 素数, 整除, 同余
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Primes, divisibility, congruences, valuations, Diophantine equations, descent,
and multiplicative functions.

## Roles

Solvers use congruence, valuation/factorization, or descent; Verifier checks
integrality/coprimality; Repair corrects local arithmetic Claims.

## Method decision tree

Reduce modulo informative bases, factor and compare valuations, use gcd/Bezout
for linear constraints, and descent/extremal arguments for impossibility.

## Theorem preconditions

Check integrality, positivity, coprimality, modulus, prime powers, and whether
division is invertible modulo the modulus.

## Common errors

Do not cancel a nonunit modulo \(m\), assume unique factorization in the wrong
ring, or overlook sign/zero cases.

## Counterexample checklist

Test zero/one, smallest primes, shared gcd, prime-power moduli, negative values,
and equality cases.

## Compatible check types

Use `reasoning`, `symbolic_equivalence`, `necessity`, `sufficiency`, and
`boundary`.

## Answer normalization

Return canonical residues, exact integer counts, factorization, or complete
solution sets.

## Trace step guidance

Expose modulus/factorization choice, hypotheses, arithmetic Claims, boundary
cases, and result.
