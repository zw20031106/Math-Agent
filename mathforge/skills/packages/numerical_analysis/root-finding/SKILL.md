---
name: root-finding
version: 3.0
format: mmat-method-card-v1
domain: numerical_analysis
subdomain: nonlinear_equations
kind: method
roles: PrimarySolver,AlternativeSolver,LemmaCurator,VerifierSkeptic,RepairAgent
triggers: solve f(x)=0, root, zero of a function, bracket, Newton iteration
problem_patterns: scalar nonlinear equation, bracketed interval, iterative root approximation
method_family: root-finding-method-selection
alternative_skills: numerical-stability,optimization
description: Select and audit a scalar root method using bracketing, smoothness, multiplicity, and residual evidence.
negative_triggers: symbolic-only identity, no target function, discontinuity at the proposed root, unsupported multivariate system
required_observables: function and domain, initial bracket or seed, stopping criterion, residual and iteration history
requires: numerical_residual
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: numerical_residual
---
## Quick Dispatch

- 方法卡：`root-finding`（Skill 3.0，method）；适用角色：PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent。
- 结构触发：solve f(x)=0, root, zero of a function, bracket, Newton iteration；问题模式：scalar nonlinear equation, bracketed interval, iterative root approximation；核心方法族：`root-finding-method-selection`。
- 关键词只用于检索，必须继续核对后文的精确前提；不满足前提时不得套用。

## Input Contract

- 必须读取原题、`ProblemIR`、公开条件、当前 Proof Obligation 和已消费的公共状态。
- 本卡声明的 Host 能力：numerical_residual；验证 hooks：numerical_residual。能力不可用时由主机降级或
  选择替代 Skill（声明替代：numerical-stability, optimization），模型不得伪造工具结果。
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
Use for a scalar equation f(x)=0 or an explicitly stated scalar component of a system when the task asks for a numerical root, convergence argument, or method choice.

## Do Not Use When
Do not call a small residual a proof of a root, do not apply Newton across a zero derivative or singularity, and do not silently reduce a multivariate system to one coordinate. A discontinuous function or an unbounded search needs a separate existence argument.

## Core Theorem
If f is continuous on [a,b] and f(a)f(b)<0, bisection maintains a bracket and converges to a root. Newton and secant methods need local regularity and suitable seeds; their convergence is conditional, not guaranteed by the iteration formula.

## Exact Preconditions
Specify f, its domain, target precision, and whether a root is known to exist. For bisection verify continuity and a strict sign change. For Newton verify differentiability near the root, a nonzero derivative along accepted steps, and a seed in a basin where the stated convergence claim applies. For secant record denominators and safeguards.

## Procedure
1. Establish existence or label it unresolved; preserve the original domain.
2. Prefer a bracketed method when a strict sign-changing interval is available and robustness matters.
3. Use safeguarded Newton for a differentiable well-conditioned simple root; fall back to bisection when a step leaves the bracket.
4. Use secant only when derivative evaluation is unavailable and denominator safeguards are explicit.
5. Report the candidate root, residual, interval/step error bound, iterations, and every failed or rejected step.

## Branch Conditions
Single simple root, multiple root, clustered roots, and endpoint roots require separate stopping rules. If f(a)f(b)=0 return the endpoint exactly; if signs do not change, do not infer nonexistence. For a system, escalate to a system-specific method rather than pretending scalar convergence.

## Failure Modes
An iteration can converge to a different root, cycle, diverge, divide by a near-zero derivative, or stop with a small residual while the function is ill-conditioned. Rounding and an unverified bracket invalidate a claimed error bound.

## Counterexample Patterns
Test x^3-2x+2 with a poor Newton seed, a double root (x-1)^2 with no sign change, a discontinuity 1/x, and a flat function with a small residual far from the intended root. Check endpoint and overflow behavior.

## Verification Recipe
Host verification uses `numerical_residual` for finite samples and a reported residual/interval; it is supporting evidence only and cannot prove existence, uniqueness, or universal convergence. Mathematical verification must supply continuity, sign/bracket, conditioning, and a valid error argument. Record the method and all assumptions.

## Mini Example
For f(x)=x^2-2 on [1,2], continuity and f(1)f(2)<0 justify bisection. A residual below the requested tolerance supports the approximation, while the maintained bracket supplies the deterministic error bound.

## Alternative Strategy
Use an analytic factorization, monotonicity plus an inverse, interval arithmetic, or a safeguarded hybrid. Use a distinct skill for multivariate Newton or optimization.

## Stop / Escalate Conditions
Stop when the requested error certificate is closed. Escalate when no existence evidence is available, the bracket is lost, conditioning is unknown, a step is rejected repeatedly, or only sampled residuals support the claim.
