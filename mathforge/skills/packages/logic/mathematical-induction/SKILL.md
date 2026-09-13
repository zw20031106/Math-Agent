---
name: mathematical-induction
version: 3.0
format: mmat-method-card-v1
domain: logic
subdomain: proof
kind: method
roles: PrimarySolver,AlternativeSolver,LemmaCurator,VerifierSkeptic,RepairAgent
triggers: induction, for all n, recurrence proof, base case, inductive step
problem_patterns: indexed integer statement, recursively defined object, well-founded measure
method_family: induction
alternative_skills: proof-strategy-selection,case-split-wlog
description: Prove an indexed family by a valid base and an explicitly quantified step over a well-founded index.
negative_triggers: continuous parameter without discretization, missing base, circular step, finite samples only
required_observables: index domain, base set, induction hypothesis, target step, well-founded measure
requires: small_case_enumeration
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: small_case_enumeration
---
## Quick Dispatch

- 方法卡：`mathematical-induction`（Skill 3.0，method）；适用角色：PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent。
- 结构触发：induction, for all n, recurrence proof, base case, inductive step；问题模式：indexed integer statement, recursively defined object, well-founded measure；核心方法族：`induction`。
- 关键词只用于检索，必须继续核对后文的精确前提；不满足前提时不得套用。

## Input Contract

- 必须读取原题、`ProblemIR`、公开条件、当前 Proof Obligation 和已消费的公共状态。
- 本卡声明的 Host 能力：small_case_enumeration；验证 hooks：small_case_enumeration。能力不可用时由主机降级或
  选择替代 Skill（声明替代：proof-strategy-selection, case-split-wlog），模型不得伪造工具结果。
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

- 声明 hooks：small_case_enumeration。它们只提供各自 policy 规定的证据强度；数值残差、有限枚举、
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
Use for statements indexed by natural numbers, finite structures with a size measure, or recursively generated objects where smaller instances support the next case.

## Do Not Use When
Do not infer an infinite theorem from a few enumerated cases, do not use induction on a non-well-founded relation, and do not let the induction hypothesis assume the target at the same index.

## Core Theorem
If P holds for every base index and P(k) implies P(k+1) for every k in the stated domain, then P holds for all indices reachable from the base. Strong or structural induction changes the hypothesis set but not the need for a well-founded measure.

## Exact Preconditions
State the index set and its order, all base cases, and the exact induction hypothesis. For strong/structural induction specify which smaller indices or substructures are available and why the measure decreases. Check side conditions at the smallest index.

## Procedure
1. Write P(n) with domains and parameters fixed.
2. Prove every base case separately; do not hide multiple bases in “obvious.”
3. Assume only the permitted induction hypothesis and derive P(k+1) (or the next structure).
4. Check that recursive calls decrease the well-founded measure and that all branches are covered.
5. Reconcile the base and step versions with the original quantifiers before closing the obligation.

## Branch Conditions
Use ordinary induction for successor indices, strong induction when several smaller cases are needed, and structural induction when constructors define the object. Finite induction ranges still require an endpoint convention.

## Failure Modes
An omitted base, an invalid starting index, a step that only handles even k, a circular use of P(k+1), or a recursive decomposition that does not decrease. A correct step cannot repair a false base.

## Counterexample Patterns
Check n=0 and the first index after every claimed threshold; test a recurrence with exceptional initial data and a measure that can stay equal. A statement true for the first six cases may fail at the seventh.

## Verification Recipe
Host verification uses `small_case_enumeration` for supplied finite base/edge cases only. It is exact for those cases but cannot prove the induction step or the universal theorem; label it supporting evidence and require a written quantified step.

## Mini Example
For 1+2+...+n=n(n+1)/2, verify n=1, assume the formula at k, add k+1, and simplify the resulting expression under the integer-domain assumption.

## Alternative Strategy
Use a direct invariant, a recurrence unrolling, or a minimal-counterexample argument when the induction step is opaque. Preserve the same well-founded obligation.

## Stop / Escalate Conditions
Escalate when the base set is unclear, the measure is not well-founded, the step has an uncovered constructor/case, or finite enumeration is the only evidence.
