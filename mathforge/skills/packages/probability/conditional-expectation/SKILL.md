---
name: conditional-expectation
version: 3.0
format: mmat-method-card-v1
domain: probability
subdomain: expectation
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: conditional expectation, tower property, law total expectation
problem_patterns: nested expectation, latent variable
method_family: conditional-expectation
alternative_skills: indicator-linearity
description: Apply the tower property only for integrable variables and nested sigma-fields or an equivalent valid conditional model.
negative_triggers: nonintegrable variable, incomparable sigma-fields, undefined conditional law
required_observables: integrability, sigma-field inclusion, conditional law
requires: density_normalization
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: density_normalization
---
## Quick Dispatch

- 方法卡：`conditional-expectation`（Skill 3.0，method）；适用角色：PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent。
- 结构触发：conditional expectation, tower property, law total expectation；问题模式：nested expectation, latent variable；核心方法族：`conditional-expectation`。
- 关键词只用于检索，必须继续核对后文的精确前提；不满足前提时不得套用。

## Input Contract

- 必须读取原题、`ProblemIR`、公开条件、当前 Proof Obligation 和已消费的公共状态。
- 本卡声明的 Host 能力：density_normalization；验证 hooks：density_normalization。能力不可用时由主机降级或
  选择替代 Skill（声明替代：indicator-linearity），模型不得伪造工具结果。
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

- 声明 hooks：density_normalization。它们只提供各自 policy 规定的证据强度；数值残差、有限枚举、
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
Use when an expectation is conditioned on a random variable or sigma-field and iterated conditioning can simplify a latent-variable calculation.

## Do Not Use When
Do not use the tower property from the words “conditional” alone. Integrability, sigma-field nesting, or a well-defined conditional distribution must be established first.

## Core Theorem
If G⊆H are sigma-fields and X is integrable, then E[E[X|H]|G]=E[X|G] almost surely and E[E[X|G]]=E[X]. Conditional expectations are equivalence classes up to null sets.

## Exact Preconditions
State the probability space, sigma-fields and their inclusion, the integrability of X (or the applicable nonnegative extension), and the version of the conditional law. For density calculations, verify support and nonnegativity in addition to normalization.

## Procedure
1. Choose the conditioning sigma-field/variable and state the inclusion relation.
2. Establish integrability and write the conditional expectation as a measurable function.
3. Compute the inner conditional quantity, preserving almost-sure equality.
4. Average over the outer law and compare with a direct expectation when available.
5. Record which tower or disintegration obligation has been closed.

## Branch Conditions
Separate discrete sums, continuous densities, and mixed laws; for a transformed variable check the Jacobian and support. Conditional expectations are only unique almost surely.

## Failure Modes
Conditioning on incomparable sigma-fields, using an unnormalized or negative “density,” or ignoring integrability invalidates the simplification. A normalized integral alone does not define a probability density.

## Counterexample Patterns
Use a joint table with a zero-probability conditioning event, a heavy-tailed nonintegrable X, or two sigma-fields without inclusion to expose hidden assumptions.

## Verification Recipe
`density_normalization` proves only that a specified integral equals one; it does not prove nonnegativity, integrability of X, sigma-field nesting, or a conditional-law identity. Treat it as normalization support and require a proof review for the tower property.

## Mini Example
For integrable X and sigma-fields G⊆H, E[E[X|H]|G]=E[X|G] almost surely; taking expectations gives E[X]=E[E[X|G]].

## Alternative Strategy
Use indicator linearity, direct joint-density integration, or a finite conditional-probability table when those structures make all hypotheses explicit.

## Stop / Escalate Conditions
Escalate when integrability, support/nonnegativity, sigma-field inclusion, or the conditioning event is unresolved. Do not close a tower obligation from a normalization check alone.
