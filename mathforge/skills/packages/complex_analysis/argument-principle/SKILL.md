---
name: argument-principle
version: 3.0
domain: complex_analysis
subdomain: proof
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: argument principle, winding number, zero pole count
problem_patterns: count zeros minus poles, change argument
method_family: argument-principle
alternative_skills: rouche-zero-count
description: Count zeros minus poles from the winding number or f prime over f integral on a contour with no boundary singularity.
negative_triggers: boundary zero, boundary pole, nonmeromorphic function
required_observables: meromorphic neighborhood, boundary nonvanishing, contour orientation
requires: numerical_residual
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: numerical_residual
---
## Recognition
Use when a meromorphic function is evaluated around a closed contour and the target is the number of zeros or poles with multiplicity.

## Do Not Use When
Do not apply if f is not meromorphic on a neighborhood of the closure or if a zero or pole lies on the contour. A winding-number plot is not a substitute for boundary nonvanishing.

## Core Theorem
For a positively oriented piecewise smooth closed contour Γ and meromorphic f with no zeros or poles on Γ, (1/(2πi))∮Γ f′/f equals the number of enclosed zeros minus enclosed poles, counted with multiplicity.

## Exact Preconditions
Specify Γ and its orientation, prove meromorphicity on and inside a neighborhood of Γ, locate all boundary singularities, and establish f(z)≠0 on Γ. If the contour is not simple, state the winding-number version.

## Procedure
1. List zeros and poles in the interior and their multiplicities.
2. Prove boundary nonvanishing and choose the argument/winding representation.
3. Evaluate f′/f or the change of argument with the correct orientation.
4. Compare the count with a factorized test case and record every boundary exclusion.

## Branch Conditions
Separate poles from zeros, account for negative orientation, and treat parameter changes that can move a zero across Γ as a new case. A boundary crossing changes the count discontinuously.

## Failure Modes
Ignoring a boundary zero/pole, forgetting multiplicity, or using f′/f at a branch point invalidates the theorem. A numerical winding estimate without a separation margin is inconclusive.

## Counterexample Patterns
Move a parameter so a simple zero reaches the contour, reverse orientation, and test f(z)=z^n to expose multiplicity errors.

## Verification Recipe
Use `numerical_residual` only as finite-sample support for a boundary nonvanishing margin or a simple factorization. It cannot certify nonvanishing on the full contour or the meromorphic hypotheses; the proof trace must do so.

## Mini Example
For f(z)=z^n on |z|=1 with positive orientation, the argument changes by 2πn and the theorem returns n zeros.

## Alternative Strategy
Use Rouché when a strict boundary dominance inequality is easier, or factor the polynomial directly when all roots are explicit.

## Stop / Escalate Conditions
Escalate when boundary nonvanishing, meromorphicity, orientation, or multiplicity is unresolved. Mark the count incomplete rather than guessing from samples.

