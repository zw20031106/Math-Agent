---
name: contradiction-contrapositive
version: 3.0
domain: logic
subdomain: proof
kind: method
roles: PrimarySolver,AlternativeSolver,LemmaCurator,VerifierSkeptic,RepairAgent
triggers: contradiction, contrapositive, assume not, impossible, reductio
problem_patterns: implication with hard conclusion, incompatible hypotheses, negated target
method_family: contradiction-and-contrapositive
alternative_skills: proof-strategy-selection,case-split-wlog
description: Transform an implication or target into a precisely scoped negation branch and expose the contradiction obligations.
negative_triggers: inconsistent original hypotheses, missing negation, contradiction based on an unstated axiom
required_observables: original proposition, exact negation, domain assumptions, contradiction endpoint
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the negated conclusion supplies a direct hypothesis, or when combining the original assumptions with the negation of the target yields a finite contradiction.

## Do Not Use When
Do not replace “not (A implies B)” with “A and not B” unless the outer logic has been normalized, and do not call an intuitive impossibility a contradiction without a named inconsistent pair.

## Core Theorem
For classical logic, A→B is equivalent to ¬B→¬A. A proof by contradiction assumes ¬T and derives a proposition and its negation (or another formally impossible state), thereby closing T under the adopted logic.

## Exact Preconditions
Record whether classical logic is allowed, normalize all quantifiers and domains, and write the exact negation of the target. The contradiction endpoint must follow from stated assumptions or a previously verified lemma, not from the desired conclusion.

## Procedure
1. Copy the original theorem and mark its logical scope.
2. For contrapositive, assume ¬B and target ¬A; for contradiction, assume ¬T.
3. Derive claims with dependencies, preserving domains and inequality directions.
4. Identify the first explicit incompatible pair or forbidden object and verify it independently.
5. Remove the temporary assumption and restate the original target.

## Branch Conditions
Use contrapositive for implication targets; use contradiction when the negation creates a global extremal or parity conflict. For constructive or intuitionistic settings, do not silently use double-negation elimination.

## Failure Modes
Proving only a weaker negation, using an inconsistent hypothesis as if it were a conclusion, hiding a division-by-zero, or asserting “therefore impossible” without a violated axiom.

## Counterexample Patterns
Try a theorem whose converse is false, a vacuous implication with impossible A, and a contradiction that depends on an omitted nonzero or integrality condition. Check whether the contradiction already existed in the premises.

## Verification Recipe
Mathematical verification checks the normalized logical equivalence and the concrete contradiction. Host verification uses `symbolic_equivalence` only for conditional formula rewriting with explicit assumptions; it does not establish classical validity or the mathematical contradiction.

## Mini Example
To prove an integer square is not congruent to 2 mod 4, assume the residue is 2 and split the integer as even or odd; each branch gives a different square residue, closing the contradiction.

## Alternative Strategy
Prefer a direct residue classification or a finite case split when it exposes the same obligations with less classical machinery.

## Stop / Escalate Conditions
Escalate when the negation is ambiguous, the logic is nonclassical, the contradiction uses an unverified lemma, or a branch silently changes the domain.
