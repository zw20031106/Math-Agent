---
name: operations-research
subject: operations-research
kind: domain
version: 2.0
triggers: linear programming, dual, shortest path, max flow, assignment, game value, 线性规划, 最短路, 最大流
roles: PrimarySolver, AlternativeSolver, VerifierSkeptic, RepairAgent
---
## Triggers

Linear programs and duals, shortest paths with negative edges, max flow/min
cut, assignment, and finite zero-sum games.

## Roles

Solvers choose duality, constructive algorithms, or equilibrium equations;
Verifier checks feasibility/optimality certificates; Repair patches failed
constraints or arithmetic.

## Method decision tree

Use primal-dual complementary slackness for LP, Bellman-Ford logic for negative
edges, augmenting paths/min cuts for flows, enumeration/Hungarian structure for
small assignments, and indifference equations for \(2\times2\) games.

## Theorem preconditions

Check constraint direction, sign restrictions, graph reachability, absence of
relevant negative cycles, capacity conservation, and mixed-strategy
probabilities.

## Common errors

Do not flip a dual sign, use Dijkstra with negative edges, violate flow
conservation, or compute a game value outside payoff bounds.

## Counterexample checklist

Verify primal/dual feasibility, reduced costs, every flow cut, alternate
assignments, pure saddle points, and probability normalization.

## Compatible check types

Use `reasoning`, `symbolic_equivalence`, `necessity`, `sufficiency`,
`boundary`, and `answer_type_check`.

## Answer normalization

Return ordered decision vectors, exact objective/cost/flow values, and clearly
state player orientation for game values.

## Trace step guidance

Expose formulation, certificate or algorithm steps, feasibility check, and
exact optimum.
