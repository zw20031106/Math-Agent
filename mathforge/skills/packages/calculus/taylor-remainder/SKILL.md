---
name: taylor-remainder
version: 3.0
format: mmat-method-card-v1
domain: calculus
subdomain: approximation
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: taylor, remainder, series expansion
problem_patterns: local approximation, error bound
method_family: taylor-remainder
alternative_skills: epsilon-delta
description: Produce a finite Taylor approximation together with a remainder bound whose differentiability hypotheses are explicit.
negative_triggers: formal series without convergence, missing derivative bound, radius boundary without analysis
required_observables: expansion center, truncation order, derivative bound
requires: numerical_residual
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: numerical_residual
---
## Quick Dispatch

- 方法卡：`taylor-remainder`（Skill 3.0，method）；适用角色：PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent。
- 结构触发：taylor, remainder, series expansion；问题模式：local approximation, error bound；核心方法族：`taylor-remainder`。
- 关键词只用于检索，必须继续核对后文的精确前提；不满足前提时不得套用。

## Input Contract

- 必须读取原题、`ProblemIR`、公开条件、当前 Proof Obligation 和已消费的公共状态。
- 本卡声明的 Host 能力：numerical_residual；验证 hooks：numerical_residual。能力不可用时由主机降级或
  选择替代 Skill（声明替代：epsilon-delta），模型不得伪造工具结果。
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
Use when the target asks for a local polynomial approximation, an asymptotic order, or a quantitative error bound near a specified center.

## Do Not Use When
Do not treat a formal power series as the function, extrapolate a local remainder bound outside its interval, or use a finite numerical fit as a convergence proof.

## Core Theorem
If f has n+1 derivatives on an interval containing the center c and x, Taylor's theorem gives f(x)=Σ_{k=0}^n f^(k)(c)(x−c)^k/k!+R_n(x), with a Lagrange or integral remainder under the stated regularity. The remainder form determines the valid error claim.

## Exact Preconditions
Specify c, n, the interval between c and x, and the derivative regularity there. For a Lagrange bound, prove a uniform bound M on |f^(n+1)| over that interval; for analytic series, separately state a convergence domain and do not infer it from differentiability alone.

## Procedure
1. Fix the center and order and compute derivatives exactly.
2. Choose a remainder form compatible with the available regularity.
3. Bound the relevant derivative on the entire interval, preserving signs and domains.
4. State the approximation and an explicit |R_n| bound with its range of validity.
5. Check limiting order only after the finite-order identity is established.

## Branch Conditions
Separate finite differentiability from analyticity, one-sided endpoints from interior points, and real from complex expansions. At a radius boundary, recheck convergence rather than extending the local estimate.

## Failure Modes
Dropping the remainder, using a derivative bound that holds only at c, or claiming equality from an asymptotic series yields an unsupported result. Numerical agreement at sampled x values does not close the error obligation.

## Counterexample Patterns
Test functions with a nearby singularity, a derivative that grows on the interval, and expansions evaluated beyond their radius. Compare the claimed order at the boundary.

## Verification Recipe
Use `numerical_residual` only as finite-sample support for the displayed polynomial; it cannot prove the derivative bound, convergence radius, or universal remainder inequality. The Verifier must check the derivative order and interval-wide bound symbolically or in the proof trace.

## Mini Example
For e^x at 0, e^x=1+x+R_1(x) and |R_1(x)|≤e^{|x|}|x|^2/2 on any stated bounded interval.

## Alternative Strategy
Use an exact integral identity, convexity bounds, or a squeeze estimate when the requested error is easier to control without a power series.

## Stop / Escalate Conditions
Escalate when the interval, derivative order, convergence domain, or uniform derivative bound is missing. Never promote finite residuals to a theorem-level pass.
