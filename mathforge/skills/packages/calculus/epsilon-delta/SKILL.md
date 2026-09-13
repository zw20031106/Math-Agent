---
name: epsilon-delta
version: 3.0
format: mmat-method-card-v1
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
## Quick Dispatch

- 方法卡：`epsilon-delta`（Skill 3.0，method）；适用角色：PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent。
- 结构触发：epsilon delta, continuity proof；问题模式：prove limit, quantify delta；核心方法族：`epsilon-delta`。
- 关键词只用于检索，必须继续核对后文的精确前提；不满足前提时不得套用。

## Input Contract

- 必须读取原题、`ProblemIR`、公开条件、当前 Proof Obligation 和已消费的公共状态。
- 本卡声明的 Host 能力：symbolic_equivalence；验证 hooks：symbolic_equivalence。能力不可用时由主机降级或
  选择替代 Skill（声明替代：taylor-remainder），模型不得伪造工具结果。
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
