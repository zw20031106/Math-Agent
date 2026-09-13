---
name: dominated-convergence
version: 3.0
format: mmat-method-card-v1
domain: calculus
subdomain: integration
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: dominated convergence, exchange limit integral
problem_patterns: limit under integral, measurable functions
method_family: dominated-convergence
alternative_skills: uniform-convergence
description: Exchange a limit and an integral only after almost everywhere convergence and one integrable dominator are proved.
negative_triggers: pointwise convergence only, nonintegrable bound, finite sample evidence
required_observables: almost everywhere convergence, measurable functions, integrable dominator
requires: numerical_residual
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: numerical_residual
---
## Quick Dispatch

- 方法卡：`dominated-convergence`（Skill 3.0，method）；适用角色：PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent。
- 结构触发：dominated convergence, exchange limit integral；问题模式：limit under integral, measurable functions；核心方法族：`dominated-convergence`。
- 关键词只用于检索，必须继续核对后文的精确前提；不满足前提时不得套用。

## Input Contract

- 必须读取原题、`ProblemIR`、公开条件、当前 Proof Obligation 和已消费的公共状态。
- 本卡声明的 Host 能力：numerical_residual；验证 hooks：numerical_residual。能力不可用时由主机降级或
  选择替代 Skill（声明替代：uniform-convergence），模型不得伪造工具结果。
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

- 声明 hooks：numerical_residual。它们只提供各自 policy 规定的证据强度；数值残差、有限枚举、
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
Use when a sequence of measurable functions is integrated and the target asks to interchange a limit and an integral. The phrase “bounded” alone is not enough.

## Do Not Use When
Do not apply from vocabulary overlap, pointwise convergence alone, a dominator that depends on the index, or a bound that is not integrable on the whole measure space.

## Core Theorem
On a measure space, if measurable f_n converge to f almost everywhere, |f_n| is bounded by one integrable g for every n, and g is in L^1, then the integrals of f_n converge to the integral of f. The three hypotheses are independent obligations.

## Exact Preconditions
Name the measure space and its domain; prove measurability, f_n→f almost everywhere, |f_n(x)|≤g(x) for all n outside one null set, and ∫|g|<∞. A finite measure space does not replace the integrable-dominator proof unless a uniform bound is supplied.

## Procedure
1. State the quantifiers and identify a single candidate limit f.
2. Prove almost-everywhere convergence, including the exceptional set.
3. Exhibit an index-independent measurable g and prove |f_n|≤g.
4. Establish g∈L^1 on the complete domain, then invoke dominated convergence.
5. Record which obligation each estimate closes before writing the integral equality.

## Branch Conditions
For a finite measure space, a uniform constant bound may yield an integrable dominator; for an infinite space it generally does not. Treat parameter-dependent domains, complex-valued functions, and subsequences separately and preserve the almost-everywhere qualifier.

## Failure Modes
Pointwise boundedness, convergence at sampled points, local domination, or an index-dependent g does not establish the theorem. A divergent or merely conditionally integrable bound leaves the interchange obligation open.

## Counterexample Patterns
Try mass escaping to infinity, a moving spike whose height grows while its support shrinks, or f_n(x)=n·1_(0,1/n)(x). These expose why pointwise convergence and finite numerical checks are insufficient.

## Verification Recipe
Use `numerical_residual` only as finite-sample support for an algebraic subexpression; it cannot verify almost-everywhere convergence, integrability, or a universal interchange. The Verifier must explicitly review all three theorem obligations and mark the claim incomplete when any one is missing.

## Mini Example
On [0,1] with Lebesgue measure, x^n→0 almost everywhere and |x^n|≤1 with 1∈L^1, so the theorem justifies passing the limit through the integral.

## Alternative Strategy
If 0≤f_n and f_n increases, test monotone convergence; if a uniform bound on the integral error is available, use uniform convergence. These alternatives require their own hypotheses.

## Stop / Escalate Conditions
Escalate when the exceptional set, global integrability, or an index-independent dominator cannot be proved. Never close the obligation from numerical samples alone.
