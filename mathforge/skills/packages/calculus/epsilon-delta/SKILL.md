---
name: epsilon-delta
version: 3.0
domain: calculus
subdomain: limit
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: epsilon delta, continuity proof
problem_patterns: prove limit, quantify delta
method_family: epsilon-delta
alternative_skills: taylor-remainder
description: Construct a delta from epsilon using bounds that hold for every admissible point in the stated neighborhood.
negative_triggers: delta depends on x, unproved neighborhood restriction, sequential evidence only
required_observables: target point, punctured neighborhood, epsilon bound
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the requested result is a limit or continuity statement whose quantifiers must be made explicit, especially for a boundary or a restricted domain.

## Do Not Use When
Do not select this merely because a limit appears. A calculator, a sequence of sample points, or a delta chosen after seeing x cannot establish the universal quantifier.

## Core Theorem
lim_{x→a}f(x)=L means for every ε>0 there exists δ>0 such that every x in the stated domain with 0<|x−a|<δ satisfies |f(x)−L|<ε. The order ∀ε∃δ∀x is part of the claim.

## Exact Preconditions
State a, L, the domain and whether the limit is one-sided; preserve any puncture or boundary restriction. Every inequality used to choose δ must be valid for all x in that neighborhood, and δ may depend on ε and fixed problem data but not on x.

## Procedure
1. Write the target absolute difference and factor or bound it.
2. Establish a local bound on auxiliary factors without assuming the conclusion.
3. Choose a positive δ as a function of ε and fixed constants.
4. Substitute the bound back into the original difference for arbitrary admissible x.
5. State the quantifiers and close the obligation only after the final inequality is <ε.

## Branch Conditions
Use separate left/right neighborhoods at endpoints, include the punctured condition for limits, and split cases when an auxiliary factor may vanish. For continuity, remove the puncture and evaluate at a.

## Failure Modes
A circular δ involving x, an unproved bound such as |x+a|<C, or a hidden domain restriction invalidates the proof. Checking a finite collection of ε values is not a quantifier proof.

## Counterexample Patterns
Look for an unbounded auxiliary factor near a boundary, a denominator approaching zero, or a proposed δ that becomes nonpositive for some ε. These expose missing local restrictions.

## Verification Recipe
Use `symbolic_equivalence` to validate factorization or inequality rearrangements under the stated domain. It does not verify the ∀ε∃δ quantifier closure; the proof must show the chosen positive δ and the final bound for arbitrary x.

## Mini Example
For f(x)=2x at a=0 and L=0, |2x|<ε follows from δ=ε/2 for every |x|<δ.

## Alternative Strategy
Use the sequential criterion or a continuity theorem only when its hypotheses are explicitly available; convert back to the requested quantifier form in the final proof.

## Stop / Escalate Conditions
Escalate when a local auxiliary bound cannot be proved, δ is nonpositive, or the domain/side is ambiguous. Do not replace the construction with numerical sampling.

