---
name: lhopital-limit
version: 3.0
format: mmat-method-card-v1
domain: calculus
subdomain: limit
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: lhopital, 0/0, infinity/infinity
problem_patterns: indeterminate quotient limit, derivative ratio
method_family: lhopital-limit
alternative_skills: taylor-remainder
description: Apply L Hopital only to a justified quotient indeterminate form on a specified one-sided or two-sided neighborhood.
negative_triggers: nonquotient indeterminate form, denominator derivative zero, denominator not tending to zero or infinity
required_observables: quotient form, differentiable punctured neighborhood, derivative-ratio limit
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Quick Dispatch

- 方法卡：`lhopital-limit`（Skill 3.0，method）；适用角色：PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent。
- 结构触发：lhopital, 0/0, infinity/infinity；问题模式：indeterminate quotient limit, derivative ratio；核心方法族：`lhopital-limit`。
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
Use for a quotient limit whose numerator and denominator both tend to zero or both diverge in magnitude, with a derivative ratio that can be analyzed on the same side of the target.

## Do Not Use When
Do not apply to a product 0·∞, ∞−∞, 1^∞, or a regular quotient without first rewriting it and rechecking the form. A derivative being computable does not itself authorize the theorem.

## Core Theorem
Under the one-sided neighborhood hypotheses, if f and g are differentiable, g' is nonzero there, f and g have the required indeterminate behavior, and f'/g' has a limit (finite or infinite), then f/g has that limit. The exact theorem variant and side must be stated.

## Exact Preconditions
Specify the approach side, a punctured neighborhood, differentiability of both functions there, g(x)≠0 and g'(x)≠0 as required, the original 0/0 or ∞/∞ form, and the existence of the derivative-ratio limit. Recheck all conditions before a second application.

## Procedure
1. Evaluate the original numerator and denominator limits and classify the form.
2. State the applicable L'Hôpital variant and its neighborhood.
3. Differentiate numerator and denominator, preserving side and domain restrictions.
4. Compute the derivative ratio and prove its limit; repeat only after revalidation.
5. Compare with a Taylor or squeeze derivation when a branch or endpoint is delicate.

## Branch Conditions
Treat left and right limits separately, distinguish finite target points from ±∞, and handle denominator zeros or sign changes by shrinking the punctured neighborhood. Rewriting a non-quotient form creates new domain obligations.

## Failure Modes
Applying the rule to a non-indeterminate form, ignoring a zero derivative, or assuming the derivative ratio has a limit creates an invalid implication. Repeated differentiation can change the form and does not automatically prove the original limit.

## Counterexample Patterns
Test a quotient with a removable denominator zero, an oscillatory derivative ratio, and a product 0·∞ that was never converted to a quotient. Check both sides when parity or absolute values are present.

## Verification Recipe
Use `symbolic_equivalence` to check algebraic rewrites only under explicit domains and assumptions. It cannot certify the L'Hôpital theorem hypotheses or a derivative limit; the proof trace must list the form, neighborhood, nonzero conditions, and derivative-ratio limit.

## Mini Example
For lim_{x→0} sin x/x, the 0/0 form and differentiability justify one application, giving lim cos x=1.

## Alternative Strategy
Prefer a Taylor expansion with a controlled remainder or a squeeze argument when derivatives do not preserve the form cleanly.

## Stop / Escalate Conditions
Escalate when the approach side, derivative-ratio limit, or nonzero denominator condition is unresolved. Do not report a result from symbolic simplification alone.
