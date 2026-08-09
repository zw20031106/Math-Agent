---
name: double-counting
version: 3.0
domain: combinatorics
subdomain: counting
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: double counting, count pairs two ways
problem_patterns: identity of counts, incidence
method_family: double-counting
alternative_skills: bijection-counting
requires: small_case_enumeration
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: small_case_enumeration
---
## Recognition
Use when the problem exposes identity of counts, incidence.

## Do Not Use When
Do not use merely from vocabulary overlap; first verify the stated preconditions.

## Core Theorem
Counting the same finite incidence set by either coordinate yields equal totals.

## Exact Preconditions
The incidence relation and finiteness are clear.

## Procedure
Define ordered pairs then sum fibers over each side.

## Branch Conditions
Branch if multiplicities or orientations matter.

## Failure Modes
Counting unordered objects on one side and ordered ones on the other creates a factor error.

## Counterexample Patterns
Test a smallest nontrivial structure.

## Verification Recipe
List the incidence set explicitly in a small case.

## Mini Example
Sum of graph degrees equals twice the edge count.

## Alternative Strategy
Use bijection or generating functions.

## Stop / Escalate Conditions
Escalate when multiplicity conventions are ambiguous.
