---
name: conditional-expectation
version: 3.0
domain: probability
subdomain: expectation
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: conditional expectation, tower property, law total expectation
problem_patterns: nested expectation, latent variable
method_family: conditional-expectation
alternative_skills: indicator-linearity
description: Apply the tower property only for integrable variables and nested sigma-fields or an equivalent valid conditional model.
negative_triggers: nonintegrable variable, incomparable sigma-fields, undefined conditional law
required_observables: integrability, sigma-field inclusion, conditional law
requires: density_normalization
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: density_normalization
---
## Recognition
Use when an expectation is conditioned on a random variable or sigma-field and iterated conditioning can simplify a latent-variable calculation.

## Do Not Use When
Do not use the tower property from the words “conditional” alone. Integrability, sigma-field nesting, or a well-defined conditional distribution must be established first.

## Core Theorem
If G⊆H are sigma-fields and X is integrable, then E[E[X|H]|G]=E[X|G] almost surely and E[E[X|G]]=E[X]. Conditional expectations are equivalence classes up to null sets.

## Exact Preconditions
State the probability space, sigma-fields and their inclusion, the integrability of X (or the applicable nonnegative extension), and the version of the conditional law. For density calculations, verify support and nonnegativity in addition to normalization.

## Procedure
1. Choose the conditioning sigma-field/variable and state the inclusion relation.
2. Establish integrability and write the conditional expectation as a measurable function.
3. Compute the inner conditional quantity, preserving almost-sure equality.
4. Average over the outer law and compare with a direct expectation when available.
5. Record which tower or disintegration obligation has been closed.

## Branch Conditions
Separate discrete sums, continuous densities, and mixed laws; for a transformed variable check the Jacobian and support. Conditional expectations are only unique almost surely.

## Failure Modes
Conditioning on incomparable sigma-fields, using an unnormalized or negative “density,” or ignoring integrability invalidates the simplification. A normalized integral alone does not define a probability density.

## Counterexample Patterns
Use a joint table with a zero-probability conditioning event, a heavy-tailed nonintegrable X, or two sigma-fields without inclusion to expose hidden assumptions.

## Verification Recipe
`density_normalization` proves only that a specified integral equals one; it does not prove nonnegativity, integrability of X, sigma-field nesting, or a conditional-law identity. Treat it as normalization support and require a proof review for the tower property.

## Mini Example
For integrable X and sigma-fields G⊆H, E[E[X|H]|G]=E[X|G] almost surely; taking expectations gives E[X]=E[E[X|G]].

## Alternative Strategy
Use indicator linearity, direct joint-density integration, or a finite conditional-probability table when those structures make all hypotheses explicit.

## Stop / Escalate Conditions
Escalate when integrability, support/nonnegativity, sigma-field inclusion, or the conditioning event is unresolved. Do not close a tower obligation from a normalization check alone.

