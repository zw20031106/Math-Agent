---
name: p-adic-valuation
version: 3.0
domain: number_theory
subdomain: number theory
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: valuation, divisibility exponent, p-adic
problem_patterns: highest prime power, factorial divisibility
method_family: p-adic-valuation
alternative_skills: modular-congruence
requires: small_case_enumeration
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: small_case_enumeration
---
## Recognition
Use when the problem exposes highest prime power, factorial divisibility.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
The p-adic valuation is additive on products and takes the minimum on sums only absent cancellation.

## Exact Preconditions
The base p is prime and nonzero quantities are handled.

## Procedure
Factor products or use Legendre's formula then analyze cancellations separately.

## Branch Conditions
Branch when summands have equal valuation.

## Failure Modes
Assuming v(a+b)=min(v(a),v(b)) at equal valuations is invalid.

## Counterexample Patterns
Test a+b where leading p-adic digits cancel.

## Verification Recipe
Reconstruct divisibility and nondivisibility by the next prime power.

## Mini Example
v_2(12)=2.

## Alternative Strategy
Use modular congruences or factorization.

## Stop / Escalate Conditions
Escalate when cancellation depth is unresolved.
