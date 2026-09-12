---
name: case-split-wlog
version: 3.0
domain: logic
subdomain: proof
kind: method
roles: PrimarySolver,AlternativeSolver,LemmaCurator,VerifierSkeptic,RepairAgent
triggers: cases, without loss of generality, WLOG, symmetry, parity split
problem_patterns: finite partition, symmetric variables, sign/order cases
method_family: exhaustive-case-analysis
alternative_skills: proof-strategy-selection,contradiction-contrapositive
description: Establish an exhaustive disjoint partition or a symmetry reduction before solving each proof branch.
negative_triggers: omitted boundary, non-symmetric target, overlapping cases without reconciliation
required_observables: partition predicate, coverage proof, disjointness, symmetry map, branch obligations
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Recognition
Use when the domain naturally splits by parity, order, sign, a finite value, or a genuine symmetry that maps every omitted arrangement to a handled one.

## Do Not Use When
Do not say WLOG merely because variables look interchangeable, and do not replace an exhaustive proof with checking representative samples. Boundaries and equality cases must belong to a branch.

## Core Theorem
If cases C₁,…,Cₖ cover the domain and are disjoint (or are reconciled on overlaps), proving the target under each case proves it globally. WLOG is valid only when a stated symmetry preserves hypotheses and target and maps every arrangement to a selected representative.

## Exact Preconditions
Define the universe, predicates for each case, coverage and disjointness arguments, and the exact symmetry transformation when using WLOG. Track which original variables/constraints are transformed and restored.

## Procedure
1. Choose the smallest partition that exposes the relevant invariant.
2. Prove coverage and handle boundary/equality cases before branch algebra.
3. Solve each branch under its added assumptions; do not import assumptions across branches.
4. For WLOG, prove invariance and provide the reverse mapping for omitted arrangements.
5. Merge the branch conclusions and record any branch-specific exceptional parameter.

## Branch Conditions
Separate sign, order, parity, and parameter cases. Use symmetry only for a permutation/scaling or other explicit map preserving the full proposition; if it changes an orientation or inequality, keep both cases.

## Failure Modes
Non-exhaustive cases, overlapping cases with incompatible conclusions, division by a branch-zero term, and an invalid WLOG reduction that changes the hypothesis or target.

## Counterexample Patterns
Try zero, equal variables, negative values, the omitted permutation, and a parameter at the partition boundary. These commonly expose a missing case or false symmetry.

## Verification Recipe
Mathematical verification proves coverage, disjointness, and each branch. Host verification uses `symbolic_equivalence` for conditional normalization of a branch or symmetry map; it cannot certify exhaustiveness or WLOG validity and is only supporting algebra.

## Mini Example
For a symmetric inequality in x,y, split x≥y and y≥x; equality lies in both but has the same target. The WLOG statement is justified only after showing the inequality is invariant under swapping x and y.

## Alternative Strategy
Use a symmetric polynomial reduction, an invariant, or a direct extremal argument when case growth is excessive. Keep a finite case enumerator as evidence, not a universal proof.

## Stop / Escalate Conditions
Escalate when coverage cannot be proved, cases proliferate without new obligations, the target is not invariant, or an equality/boundary branch remains open.
