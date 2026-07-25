---
name: discrete-math
subject: discrete-math
kind: domain
version: 2.0
triggers: graph, recurrence, discrete structure, 图论, 递推
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Graphs, recurrences, discrete structures, induction, and finite algorithms.

## Roles

Solvers use recurrence/invariants; Verifier checks conventions and base cases;
Repair fixes failed discrete Claims.

## Method decision tree

Define vertices/edges or state variables, choose recurrence/generating
functions, induction, or invariant/extremal reasoning.

## Theorem preconditions

State directed/undirected, simple/multigraph, connectivity, index ranges, and
all recurrence base values.

## Common errors

Do not change graph conventions, omit a base case, or assume connectivity or
acyclicity without evidence.

## Counterexample checklist

Test empty/single-vertex graphs, smallest indices, disconnected components,
loops, and parity boundaries.

## Compatible check types

Use `reasoning`, `definition`, `boundary`, `necessity`, and `sufficiency`.

## Answer normalization

Return exact integer sequences, graph invariants, or constructions with stated
index ranges.

## Trace step guidance

Expose definitions, recurrence/invariant, base cases, induction step, and exact
answer.
