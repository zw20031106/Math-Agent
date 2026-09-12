---
name: lhopital-limit
version: 3.0
domain: calculus
subdomain: limit
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: lhopital, 0/0, infinity/infinity
problem_patterns: indeterminate quotient limit, derivative ratio
method_family: lhopital-limit
alternative_skills: taylor-remainder
description: Apply L Hopital only to a justified quotient indeterminate form on a specified one-sided or two-sided neighborhood.
negative_triggers: nonquotient indeterminate form, denominator derivative zero, denominator not tending to zero or infinity
required_observables: quotient form, differentiable punctured neighborhood, derivative-ratio limit
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use for a quotient limit whose numerator and denominator both tend to zero or both diverge in magnitude, with a derivative ratio that can be analyzed on the same side of the target.

## Do Not Use When
Do not apply to a product 0·∞, ∞−∞, 1^∞, or a regular quotient without first rewriting it and rechecking the form. A derivative being computable does not itself authorize the theorem.

## Core Theorem
Under the one-sided neighborhood hypotheses, if f and g are differentiable, g' is nonzero there, f and g have the required indeterminate behavior, and f'/g' has a limit (finite or infinite), then f/g has that limit. The exact theorem variant and side must be stated.

## Exact Preconditions
Specify the approach side, a punctured neighborhood, differentiability of both functions there, g(x)≠0 and g'(x)≠0 as required, the original 0/0 or ∞/∞ form, and the existence of the derivative-ratio limit. Recheck all conditions before a second application.

## Procedure
1. Evaluate the original numerator and denominator limits and classify the form.
2. State the applicable L'Hôpital variant and its neighborhood.
3. Differentiate numerator and denominator, preserving side and domain restrictions.
4. Compute the derivative ratio and prove its limit; repeat only after revalidation.
5. Compare with a Taylor or squeeze derivation when a branch or endpoint is delicate.

## Branch Conditions
Treat left and right limits separately, distinguish finite target points from ±∞, and handle denominator zeros or sign changes by shrinking the punctured neighborhood. Rewriting a non-quotient form creates new domain obligations.

## Failure Modes
Applying the rule to a non-indeterminate form, ignoring a zero derivative, or assuming the derivative ratio has a limit creates an invalid implication. Repeated differentiation can change the form and does not automatically prove the original limit.

## Counterexample Patterns
Test a quotient with a removable denominator zero, an oscillatory derivative ratio, and a product 0·∞ that was never converted to a quotient. Check both sides when parity or absolute values are present.

## Verification Recipe
Use `symbolic_equivalence` to check algebraic rewrites only under explicit domains and assumptions. It cannot certify the L'Hôpital theorem hypotheses or a derivative limit; the proof trace must list the form, neighborhood, nonzero conditions, and derivative-ratio limit.

## Mini Example
For lim_{x→0} sin x/x, the 0/0 form and differentiability justify one application, giving lim cos x=1.

## Alternative Strategy
Prefer a Taylor expansion with a controlled remainder or a squeeze argument when derivatives do not preserve the form cleanly.

## Stop / Escalate Conditions
Escalate when the approach side, derivative-ratio limit, or nonzero denominator condition is unresolved. Do not report a result from symbolic simplification alone.

