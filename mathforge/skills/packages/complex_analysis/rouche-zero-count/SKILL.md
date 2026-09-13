---
name: rouche-zero-count
version: 3.0
format: mmat-method-card-v1
domain: complex_analysis
subdomain: proof
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: rouche, zeros inside contour, dominates
problem_patterns: count complex zeros, contour dominance
method_family: rouche-zero-count
alternative_skills: argument-principle
description: Transfer a zero count using strict boundary dominance between two holomorphic functions on a specified contour.
negative_triggers: non-strict dominance, boundary singularity, function not holomorphic inside
required_observables: holomorphic neighborhood, strict boundary margin, dominant zero count
requires: numerical_residual
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: numerical_residual
---
## Quick Dispatch

- 方法卡：`rouche-zero-count`（Skill 3.0，method）；适用角色：PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent。
- 结构触发：rouche, zeros inside contour, dominates；问题模式：count complex zeros, contour dominance；核心方法族：`rouche-zero-count`。
- 关键词只用于检索，必须继续核对后文的精确前提；不满足前提时不得套用。

## Input Contract

- 必须读取原题、`ProblemIR`、公开条件、当前 Proof Obligation 和已消费的公共状态。
- 本卡声明的 Host 能力：numerical_residual；验证 hooks：numerical_residual。能力不可用时由主机降级或
  选择替代 Skill（声明替代：argument-principle），模型不得伪造工具结果。
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
Use when a polynomial or holomorphic function splits as f+g and one term has an easy zero count while |g|<|f| is plausible on a simple closed contour.

## Do Not Use When
Do not use a non-strict inequality, a contour containing a singularity, or a function that is only meromorphic inside. “Dominates at sampled points” is not global boundary dominance.

## Core Theorem
If f and g are holomorphic on and inside Γ and |g(z)|<|f(z)| for every z∈Γ, then f and f+g have the same number of zeros inside Γ, counted with multiplicity. Strictness and the full contour are essential.

## Exact Preconditions
Specify Γ and orientation, prove holomorphicity on a neighborhood of its closure, establish f(z)≠0 on Γ, and prove a strict margin |f|−|g|>0 at every boundary point. Count zeros of the dominant f in the same interior.

## Procedure
1. Choose f with an elementary interior zero count and set g=(f+g)−f.
2. Parameterize Γ and derive an analytic lower bound for |f|−|g|.
3. Prove the bound is strictly positive globally, including corners or endpoints.
4. Apply Rouché and transfer the multiplicity-aware count.
5. Recheck the margin if the contour radius or parameters change.

## Branch Conditions
Handle circles, piecewise smooth contours, and parameter-dependent radii separately. If equality occurs at any boundary point, switch to another estimate or another theorem.

## Failure Modes
A ≥ inequality, a zero of f on Γ, or a missing holomorphic neighborhood leaves Rouché unavailable. Counting only distinct roots loses multiplicities.

## Counterexample Patterns
Search for equality points on Γ, perturb a coefficient until a root crosses the boundary, and compare with a direct factorization for a low-degree case.

## Verification Recipe
Use `numerical_residual` only as finite-sample support for a proposed boundary margin. It cannot certify strict dominance on the entire contour or holomorphicity; the Verifier must provide a global inequality and mark the obligation open otherwise.

## Mini Example
On |z|=2, f=z^3 and g=z+1 satisfy |f|=8 and |g|≤3, so the strict margin transfers the three-zero count.

## Alternative Strategy
Use the argument principle or direct factorization when no global strict margin can be proved.

## Stop / Escalate Conditions
Escalate when the margin is only sampled, equality is possible, or an interior singularity is present. Do not convert numerical agreement into a Rouché pass.
