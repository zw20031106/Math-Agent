---
name: markov-chebyshev
version: 3.0
domain: probability
subdomain: inequality
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: markov, chebyshev, tail bound
problem_patterns: probability tail, variance bound
method_family: markov-chebyshev
alternative_skills: conditional-expectation
requires: numerical_residual
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: numerical_residual
---
## Recognition
Use when the problem exposes probability tail, variance bound.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
Markov bounds a nonnegative variable; Chebyshev applies Markov to squared centered deviation.

## Exact Preconditions
Nonnegativity or finite variance conditions are checked.

## Procedure
Choose the nonnegative quantity and threshold then apply the bound.

## Branch Conditions
Branch to one-sided or higher-moment bounds when available.

## Failure Modes
Markov cannot be applied directly to a signed variable.

## Counterexample Patterns
Test zero variance and heavy tails.

## Verification Recipe
Check the bound lies in [0,1] and compare small cases.

## Mini Example
P(|X-EX|>=t)<=Var(X)/t^2.

## Alternative Strategy
Use Chernoff bounds if moment generating functions exist.

## Stop / Escalate Conditions
Escalate when the required moment is infinite.
