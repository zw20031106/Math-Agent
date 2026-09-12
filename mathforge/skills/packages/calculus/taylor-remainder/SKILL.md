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
description: Produce a finite Taylor approximation together with a remainder bound whose differentiability hypotheses are explicit.
negative_triggers: formal series without convergence, missing derivative bound, radius boundary without analysis
required_observables: expansion center, truncation order, derivative bound
requires: numerical_residual
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: numerical_residual
---
## Recognition
Use when the target asks for a local polynomial approximation, an asymptotic order, or a quantitative error bound near a specified center.

## Do Not Use When
Do not treat a formal power series as the function, extrapolate a local remainder bound outside its interval, or use a finite numerical fit as a convergence proof.

## Core Theorem
If f has n+1 derivatives on an interval containing the center c and x, Taylor's theorem gives f(x)=Σ_{k=0}^n f^(k)(c)(x−c)^k/k!+R_n(x), with a Lagrange or integral remainder under the stated regularity. The remainder form determines the valid error claim.

## Exact Preconditions
Specify c, n, the interval between c and x, and the derivative regularity there. For a Lagrange bound, prove a uniform bound M on |f^(n+1)| over that interval; for analytic series, separately state a convergence domain and do not infer it from differentiability alone.

## Procedure
1. Fix the center and order and compute derivatives exactly.
2. Choose a remainder form compatible with the available regularity.
3. Bound the relevant derivative on the entire interval, preserving signs and domains.
4. State the approximation and an explicit |R_n| bound with its range of validity.
5. Check limiting order only after the finite-order identity is established.

## Branch Conditions
Separate finite differentiability from analyticity, one-sided endpoints from interior points, and real from complex expansions. At a radius boundary, recheck convergence rather than extending the local estimate.

## Failure Modes
Dropping the remainder, using a derivative bound that holds only at c, or claiming equality from an asymptotic series yields an unsupported result. Numerical agreement at sampled x values does not close the error obligation.

## Counterexample Patterns
Test functions with a nearby singularity, a derivative that grows on the interval, and expansions evaluated beyond their radius. Compare the claimed order at the boundary.

## Verification Recipe
Use `numerical_residual` only as finite-sample support for the displayed polynomial; it cannot prove the derivative bound, convergence radius, or universal remainder inequality. The Verifier must check the derivative order and interval-wide bound symbolically or in the proof trace.

## Mini Example
For e^x at 0, e^x=1+x+R_1(x) and |R_1(x)|≤e^{|x|}|x|^2/2 on any stated bounded interval.

## Alternative Strategy
Use an exact integral identity, convexity bounds, or a squeeze estimate when the requested error is easier to control without a power series.

## Stop / Escalate Conditions
Escalate when the interval, derivative order, convergence domain, or uniform derivative bound is missing. Never promote finite residuals to a theorem-level pass.

