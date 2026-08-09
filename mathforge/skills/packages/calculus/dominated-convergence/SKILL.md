---
name: dominated-convergence
version: 3.0
domain: calculus
subdomain: integration
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: dominated convergence, exchange limit integral
problem_patterns: limit under integral, measurable functions
method_family: dominated-convergence
alternative_skills: uniform-convergence
requires: numerical_residual
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: numerical_residual
---
## Recognition
Use when the problem exposes limit under integral, measurable functions.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
Pointwise almost-everywhere convergence plus one integrable dominator permits interchanging limit and integral.

## Exact Preconditions
Measurability and an integrable bound independent of the sequence are established.

## Procedure
Identify pointwise limit then exhibit and integrate a dominator.

## Branch Conditions
Branch for finite measure spaces and parameter limits.

## Failure Modes
Pointwise boundedness without one integrable dominator is insufficient.

## Counterexample Patterns
Check mass escaping to infinity.

## Verification Recipe
Verify domination for all indices and integrability on the whole domain.

## Mini Example
On [0,1], x^n->0 a.e. and |x^n|<=1.

## Alternative Strategy
Use monotone convergence or uniform convergence.

## Stop / Escalate Conditions
Escalate when domination holds only locally.
