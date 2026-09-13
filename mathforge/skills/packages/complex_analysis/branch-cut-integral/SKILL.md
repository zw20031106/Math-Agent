---
name: branch-cut-integral
version: 3.0
format: mmat-method-card-v1
domain: complex_analysis
subdomain: integration
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: branch cut, keyhole contour, log branch
problem_patterns: multivalued complex function, contour integral
method_family: branch-cut-integral
alternative_skills: residue-theorem
description: Evaluate a contour integral involving a multivalued function after fixing one analytic branch and its jump across the cut.
negative_triggers: unspecified branch, contour crosses cut, nonintegrable endpoint
required_observables: branch domain, argument convention, contour orientation
requires: numerical_residual
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: numerical_residual
---
## Quick Dispatch

- 方法卡：`branch-cut-integral`（Skill 3.0，method）；适用角色：PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent。
- 结构触发：branch cut, keyhole contour, log branch；问题模式：multivalued complex function, contour integral；核心方法族：`branch-cut-integral`。
- 关键词只用于检索，必须继续核对后文的精确前提；不满足前提时不得套用。

## Input Contract

- 必须读取原题、`ProblemIR`、公开条件、当前 Proof Obligation 和已消费的公共状态。
- 本卡声明的 Host 能力：numerical_residual；验证 hooks：numerical_residual。能力不可用时由主机降级或
  选择替代 Skill（声明替代：residue-theorem），模型不得伪造工具结果。
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
Use when powers, logarithms, roots, or inverse functions are multivalued and a keyhole, slit, or dog-bone contour is proposed.

## Do Not Use When
Do not choose this if the branch, argument range, contour orientation, or endpoint behavior is unspecified. A numerical contour value cannot repair an inconsistent branch choice.

## Core Theorem
After deleting a cut and fixing a continuous argument interval, z^α and Log z are single-valued analytic on the branch domain. The two banks of a cut differ by the prescribed monodromy factor, and a contour integral is the oriented sum of all pieces.

## Exact Preconditions
State the branch function, cut, argument interval, contour and orientation. Prove analyticity on and between contour pieces, account for endpoint indentations, and establish convergence/vanishing of every auxiliary arc before taking a limit.

## Procedure
1. Fix the branch and write its values on both banks of the cut.
2. Parameterize each segment with its orientation and list the induced jump factor.
3. Bound small and large circular arcs and justify their limiting contribution.
4. Combine the real-axis or bank integrals only after checking endpoint integrability.
5. Cross-check the final orientation and branch factor with a simple integer exponent.

## Branch Conditions
Separate upper and lower bank arguments, inner versus outer radius limits, and integer versus noninteger exponents. A different argument convention changes the jump and must be carried through every segment.

## Failure Modes
Using principal values on one bank and another branch on the other, reversing an orientation, omitting an arc, or assuming an endpoint is integrable invalidates the result. Branch points are not ordinary poles.

## Counterexample Patterns
Test an integer exponent where the jump should vanish, reverse the contour orientation, and inspect a parameter for which the endpoint exponent is ≤−1.

## Verification Recipe
Use `numerical_residual` only as finite-sample support for a parameterized segment after the branch is fixed. It cannot certify analyticity, orientation, jump factors, or vanishing arcs; the proof trace must close those contour obligations explicitly.

## Mini Example
For a keyhole contour with a fixed branch of z^α, the two banks differ by e^{2πiα}; when α is an integer the factor is one and no branch jump remains.

## Alternative Strategy
Use a real substitution or residues when the integrand is single-valued on a simpler contour; verify that no hidden branch point remains.

## Stop / Escalate Conditions
Escalate when the branch domain or endpoint integrability is unresolved, an arc does not vanish, or the contour intersects the cut. Do not report a numerical value as a proof.
