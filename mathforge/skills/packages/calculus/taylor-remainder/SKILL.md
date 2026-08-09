---
name: taylor-remainder
version: 3.0
domain: calculus
subdomain: approximation
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: taylor, remainder, series expansion
problem_patterns: local approximation, error bound
method_family: taylor-remainder
alternative_skills: epsilon-delta
requires: numerical_residual
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: numerical_residual
---
## Recognition
Use when the problem exposes local approximation, error bound.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
Taylor expansion requires an explicit remainder form to support a quantitative error claim.

## Exact Preconditions
Required derivatives exist on the interval between center and target.

## Procedure
Expand to the requested order and bound a valid Lagrange or integral remainder.

## Branch Conditions
Branch by analytic versus finitely differentiable assumptions.

## Failure Modes
A formal series without convergence does not equal the function.

## Counterexample Patterns
Test at the radius boundary and for large derivatives.

## Verification Recipe
Differentiate the claimed polynomial and bound the remainder independently.

## Mini Example
e^x=1+x+R_1 with |R_1|<=e^{|x|}x^2/2.

## Alternative Strategy
Use convexity bounds or an exact identity.

## Stop / Escalate Conditions
Escalate if no uniform derivative bound is available.
