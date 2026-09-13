---
name: existence-uniqueness
version: 3.0
format: mmat-method-card-v1
domain: logic
subdomain: proof
kind: method
roles: PrimarySolver,AlternativeSolver,LemmaCurator,VerifierSkeptic,RepairAgent
triggers: exists unique, existence, uniqueness, exactly one, construct a solution
problem_patterns: witness construction, solution set, equation with uniqueness claim
method_family: existence-and-uniqueness
alternative_skills: proof-strategy-selection,contradiction-contrapositive
description: Separate witness construction from the proof that any two admissible witnesses coincide.
negative_triggers: numerical candidate only, witness outside the domain, uniqueness inferred from monotonic samples
required_observables: admissible domain, witness, existence obligations, pairwise uniqueness obligations
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Quick Dispatch

- 方法卡：`existence-uniqueness`（Skill 3.0，method）；适用角色：PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent。
- 结构触发：exists unique, existence, uniqueness, exactly one, construct a solution；问题模式：witness construction, solution set, equation with uniqueness claim；核心方法族：`existence-and-uniqueness`。
- 关键词只用于检索，必须继续核对后文的精确前提；不满足前提时不得套用。

## Input Contract

- 必须读取原题、`ProblemIR`、公开条件、当前 Proof Obligation 和已消费的公共状态。
- 本卡声明的 Host 能力：symbolic_equivalence；验证 hooks：symbolic_equivalence。能力不可用时由主机降级或
  选择替代 Skill（声明替代：proof-strategy-selection, contradiction-contrapositive），模型不得伪造工具结果。
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
Use for “there exists,” “there is exactly one,” or a problem that asks for a constructed object and a uniqueness proof under stated constraints.

## Do Not Use When
Do not treat a numerical approximation as a witness for an exact statement, do not prove uniqueness without proving existence, and do not compare candidates outside the admissible domain.

## Core Theorem
∃x P(x) requires one x in the domain with P(x). ∃!x P(x) additionally requires that for all y,z in the domain, P(y) and P(z) imply y=z. The two obligations are logically independent.

## Exact Preconditions
State the domain, parameters, regularity assumptions, and the exact predicate P. For uniqueness identify the relation or monotonicity/injectivity lemma that can compare arbitrary witnesses; do not use only the constructed witness.

## Procedure
1. Search for an explicit witness or a theorem supplying one; verify every side condition.
2. Publish the existence derivation with no uniqueness assumptions.
3. Let y and z be arbitrary admissible witnesses and derive equality through injectivity, monotonicity, algebra, or a contradiction.
4. Check boundary, degenerate, and parameter cases separately.
5. State whether the result is existence, uniqueness, or both, and retain unresolved parts as open obligations.

## Branch Conditions
Use monotonicity for scalar equations, contraction/fixed-point arguments when their hypotheses hold, compactness for abstract existence, and direct comparison for algebraic uniqueness. A theorem with several parameter regimes needs one witness/uniqueness branch per regime.

## Failure Modes
An invalid witness, circular substitution of the desired value, a local derivative test presented as global uniqueness, or an unhandled parameter where the domain is empty or the function is constant.

## Counterexample Patterns
Test an empty domain, a flat function with many roots, a boundary-only witness, and a parameter value where the derivative vanishes. A small residual cannot distinguish multiple nearby roots.

## Verification Recipe
Mathematical verification checks witness admissibility and the arbitrary-pair uniqueness argument. Host verification uses `symbolic_equivalence` for conditional algebraic comparison under declared domains; it is not an existence or uniqueness proof and must be labeled supporting algebra.

## Mini Example
For x^2=1 over the reals, witnesses 1 and -1 prove existence but disprove uniqueness. Over x≥0, the witness 1 plus the domain-restricted comparison yields uniqueness.

## Alternative Strategy
Use a counterexample to reject a uniqueness claim, or use a set-valued solution description when the task asks only for all solutions.

## Stop / Escalate Conditions
Escalate when no admissible witness is available, the comparison lemma is local only, the domain changes between branches, or a parameter case is unresolved.
