---
name: proof-strategy-selection
version: 3.0
format: mmat-method-card-v1
domain: logic
subdomain: proof_planning
kind: method
roles: PrimarySolver,AlternativeSolver,LemmaCurator,VerifierSkeptic,RepairAgent
triggers: choose proof method, proof plan, prove theorem, select strategy
problem_patterns: quantified theorem, implication, equivalence, existence or uniqueness claim
method_family: proof-method-selection
alternative_skills: mathematical-induction,contradiction-contrapositive,case-split-wlog,existence-uniqueness
description: Select a proof architecture from the statement shape and maintain explicit obligations through the selected branches.
negative_triggers: computation-only question, missing proposition, request to choose by keyword alone
required_observables: quantifier shape, hypotheses, target connective, candidate obligations
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Quick Dispatch

- 方法卡：`proof-strategy-selection`（Skill 3.0，method）；适用角色：PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent。
- 结构触发：choose proof method, proof plan, prove theorem, select strategy；问题模式：quantified theorem, implication, equivalence, existence or uniqueness claim；核心方法族：`proof-method-selection`。
- 关键词只用于检索，必须继续核对后文的精确前提；不满足前提时不得套用。

## Input Contract

- 必须读取原题、`ProblemIR`、公开条件、当前 Proof Obligation 和已消费的公共状态。
- 本卡声明的 Host 能力：symbolic_equivalence；验证 hooks：symbolic_equivalence。能力不可用时由主机降级或
  选择替代 Skill（声明替代：mathematical-induction, contradiction-contrapositive, case-split-wlog, existence-uniqueness），模型不得伪造工具结果。
- 保留原题全部量词、定义域、边界、符号约定和目标类型；本卡不授权增加假设。

## Workflow

1. **识别**：以结构模式和目标极性确认本卡是否相关，并记录不适用信号。
2. **前提门**：逐项核对 `Exact Preconditions`、定义域、可逆性、分支和边界；任一
   关键前提未知就把对应义务公开化，不把 Recognition 当成许可。
3. **执行**：按 `Procedure` 形成原子 Claim、依赖关系和可复查的公开步骤；按
   `Branch Conditions` 分开互斥且完备的分支。
4. **验证**：运行已准入的工具或请求独立审阅，按 `Verification Recipe` 记录证据
   的范围；弱证据只能支撑声明范围内的 Claim。
5. **交接**：发布候选、引理、Finding 或修复工件的公开语义摘要，等待主机版本化、
   依赖闭包检查和下一节点准入；失败路径保留为可重启信息。

## Shared Artifacts

- 工件必须能被后续角色消费：包含适用条件、Claim/Obligation 引用、证据关系、
  未决项和下一步建议；不要写私有推理、密钥、路径或原始异常。
- 主机区分 delivery、consumption、application 和 ignoring；下游 Prompt 在消费
  前不得把未消费工件当事实。候选保留 `candidate_id`、`branch_id` 和 parent/version
  lineage，由主机分配生命周期字段。

## Verification Boundary

- 声明 hooks：symbolic_equivalence。它们只提供各自 policy 规定的证据强度；数值残差、有限枚举、
  形状检查或符号等价均不能单独证明未检查的普遍定理前提。
- 对未知、缺证据、版本不匹配、反例风险或开放义务返回 unknown/incomplete，不能
  用计数、哈希或相关模型同意代替数学验证。
- `Counterexample Patterns`、`Failure Modes` 和 `Verification Recipe` 是审计清单；
  发现风险时引用真实 Claim、Step、Obligation 或 Evidence。

## Failure Routing

- 声明失败信号：missing_condition, contradiction, verification_failed。命中信号时先保留失败工件，再按 `Alternative Strategy`
  或替代 Skill 重新规划，不重复同一无效路径。
- 若问题需要改变核心定理、方法族或原题假设，报告全局方法失败；局部错误才交给
  RepairAgent 做有限 dependency closure 补丁，并必须重新验证。

## Output Contract

- 只输出当前角色编译协议要求的公开语义；不得生成 Host ID、版本、预算、工具参数、
  ACK 或未经证据支持的“已通过”状态。
- 非证明题只保留可规范化的答案语义；证明题保留能支撑结论的关键完整步骤。所有
  内容必须可由后续审阅者复核，停止前写明未决义务和升级条件。

## Recognition
Use before proof synthesis when the theorem shape suggests direct proof, contrapositive, contradiction, cases, induction, existence, uniqueness, or a counterexample.

## Do Not Use When
Do not select a method from a surface word, do not turn a numerical check into a theorem, and do not use a contradiction branch without writing the negation of the exact target.

## Core Theorem
Proof methods are sound transformations of obligations: an implication may be proved directly or by contrapositive, an equivalence requires both directions, a universal claim can be refuted by one admissible counterexample, and induction requires a valid base and quantified step.

## Exact Preconditions
Normalize the proposition with variable domains, quantifier order, hypotheses, and conclusion. Identify whether the target is implication, equivalence, universal, existential, uniqueness, or a finite disjunction. Every selected method must map to a finite list of named obligations.

## Procedure
1. Parse the logical outermost connective and list all assumptions.
2. Choose the least-assumptive method that matches the dependency direction.
3. Publish an obligation graph with base, bridge, witness, or contradiction nodes as appropriate.
4. Ask an alternative branch to challenge the choice when the first method has a missing condition or circular dependency.
5. Close obligations only after a claim-specific mathematical verification; retain the selected strategy/version in the candidate lineage.

## Branch Conditions
Direct proof is preferred when hypotheses rewrite the target. Use contrapositive when the negated conclusion exposes a usable hypothesis. Use contradiction when the negation yields a finite inconsistency. Use cases when an exhaustive partition is available. Use induction only for a well-founded indexed family.

## Failure Modes
Proving a converse instead of the implication, losing a quantifier, assuming the desired result, using a non-exhaustive case split, or treating a witness for one instance as a universal construction.

## Counterexample Patterns
Try a false converse, an empty domain, an existential statement with a nonconstructive witness, and a case split that omits zero or a boundary. If one example falsifies a universal statement, record it as a counterexample rather than forcing a proof.

## Verification Recipe
Mathematical verification checks each obligation and dependency. Host verification uses `symbolic_equivalence` only for domain-bounded normalization of formulas; its result is conditional on stated assumptions and does not certify the proof. Record the proposition, assumptions, and comparison domain.

## Mini Example
For “if n^2 is even then n is even,” the conclusion’s negation makes contrapositive useful. The plan still needs the integer-domain assumption and the factorization of an odd square.

## Alternative Strategy
Switch to a claim-local lemma, a finite counterexample search, or a case split when the selected branch has an open obligation. Never keep two strategies as if both were completed proofs.

## Stop / Escalate Conditions
Escalate on ambiguous quantifiers, circular dependencies, an unproved exhaustiveness claim, or a branch whose assumptions differ from the original theorem. A plan is not a final answer.
