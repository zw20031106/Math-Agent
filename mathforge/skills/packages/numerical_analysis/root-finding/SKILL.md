---
name: root-finding
version: 3.0
domain: numerical_analysis
subdomain: nonlinear_equations
kind: method
roles: PrimarySolver,AlternativeSolver,LemmaCurator,VerifierSkeptic,RepairAgent
triggers: solve f(x)=0, root, zero of a function, bracket, Newton iteration
problem_patterns: scalar nonlinear equation, bracketed interval, iterative root approximation
method_family: root-finding-method-selection
alternative_skills: numerical-stability,optimization
description: Select and audit a scalar root method using bracketing, smoothness, multiplicity, and residual evidence.
negative_triggers: symbolic-only identity, no target function, discontinuity at the proposed root, unsupported multivariate system
required_observables: function and domain, initial bracket or seed, stopping criterion, residual and iteration history
requires: numerical_residual
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: numerical_residual
---
## Recognition
Use for a scalar equation f(x)=0 or an explicitly stated scalar component of a system when the task asks for a numerical root, convergence argument, or method choice.

## Do Not Use When
Do not call a small residual a proof of a root, do not apply Newton across a zero derivative or singularity, and do not silently reduce a multivariate system to one coordinate. A discontinuous function or an unbounded search needs a separate existence argument.

## Core Theorem
If f is continuous on [a,b] and f(a)f(b)<0, bisection maintains a bracket and converges to a root. Newton and secant methods need local regularity and suitable seeds; their convergence is conditional, not guaranteed by the iteration formula.

## Exact Preconditions
Specify f, its domain, target precision, and whether a root is known to exist. For bisection verify continuity and a strict sign change. For Newton verify differentiability near the root, a nonzero derivative along accepted steps, and a seed in a basin where the stated convergence claim applies. For secant record denominators and safeguards.

## Procedure
1. Establish existence or label it unresolved; preserve the original domain.
2. Prefer a bracketed method when a strict sign-changing interval is available and robustness matters.
3. Use safeguarded Newton for a differentiable well-conditioned simple root; fall back to bisection when a step leaves the bracket.
4. Use secant only when derivative evaluation is unavailable and denominator safeguards are explicit.
5. Report the candidate root, residual, interval/step error bound, iterations, and every failed or rejected step.

## Branch Conditions
Single simple root, multiple root, clustered roots, and endpoint roots require separate stopping rules. If f(a)f(b)=0 return the endpoint exactly; if signs do not change, do not infer nonexistence. For a system, escalate to a system-specific method rather than pretending scalar convergence.

## Failure Modes
An iteration can converge to a different root, cycle, diverge, divide by a near-zero derivative, or stop with a small residual while the function is ill-conditioned. Rounding and an unverified bracket invalidate a claimed error bound.

## Counterexample Patterns
Test x^3-2x+2 with a poor Newton seed, a double root (x-1)^2 with no sign change, a discontinuity 1/x, and a flat function with a small residual far from the intended root. Check endpoint and overflow behavior.

## Verification Recipe
Host verification uses `numerical_residual` for finite samples and a reported residual/interval; it is supporting evidence only and cannot prove existence, uniqueness, or universal convergence. Mathematical verification must supply continuity, sign/bracket, conditioning, and a valid error argument. Record the method and all assumptions.

## Mini Example
For f(x)=x^2-2 on [1,2], continuity and f(1)f(2)<0 justify bisection. A residual below the requested tolerance supports the approximation, while the maintained bracket supplies the deterministic error bound.

## Alternative Strategy
Use an analytic factorization, monotonicity plus an inverse, interval arithmetic, or a safeguarded hybrid. Use a distinct skill for multivariate Newton or optimization.

## Stop / Escalate Conditions
Stop when the requested error certificate is closed. Escalate when no existence evidence is available, the bracket is lost, conditioning is unknown, a step is rejected repeatedly, or only sampled residuals support the claim.
