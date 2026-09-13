---
name: case-split-wlog
version: 3.0
format: mmat-method-card-v1
domain: logic
subdomain: proof
kind: method
roles: PrimarySolver,AlternativeSolver,LemmaCurator,VerifierSkeptic,RepairAgent
triggers: cases, without loss of generality, WLOG, symmetry, parity split
problem_patterns: finite partition, symmetric variables, sign/order cases
method_family: exhaustive-case-analysis
alternative_skills: proof-strategy-selection,contradiction-contrapositive
description: Establish an exhaustive disjoint partition or a symmetry reduction before solving each proof branch.
negative_triggers: omitted boundary, non-symmetric target, overlapping cases without reconciliation
required_observables: partition predicate, coverage proof, disjointness, symmetry map, branch obligations
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Quick Dispatch

- 方法卡：`case-split-wlog`（Skill 3.0，method）；适用角色：PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent。
- 结构触发：cases, without loss of generality, WLOG, symmetry, parity split；问题模式：finite partition, symmetric variables, sign/order cases；核心方法族：`exhaustive-case-analysis`。
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
Use when the domain naturally splits by parity, order, sign, a finite value, or a genuine symmetry that maps every omitted arrangement to a handled one.

## Do Not Use When
Do not say WLOG merely because variables look interchangeable, and do not replace an exhaustive proof with checking representative samples. Boundaries and equality cases must belong to a branch.

## Core Theorem
If cases C₁,…,Cₖ cover the domain and are disjoint (or are reconciled on overlaps), proving the target under each case proves it globally. WLOG is valid only when a stated symmetry preserves hypotheses and target and maps every arrangement to a selected representative.

## Exact Preconditions
Define the universe, predicates for each case, coverage and disjointness arguments, and the exact symmetry transformation when using WLOG. Track which original variables/constraints are transformed and restored.

## Procedure
1. Choose the smallest partition that exposes the relevant invariant.
2. Prove coverage and handle boundary/equality cases before branch algebra.
3. Solve each branch under its added assumptions; do not import assumptions across branches.
4. For WLOG, prove invariance and provide the reverse mapping for omitted arrangements.
5. Merge the branch conclusions and record any branch-specific exceptional parameter.

## Branch Conditions
Separate sign, order, parity, and parameter cases. Use symmetry only for a permutation/scaling or other explicit map preserving the full proposition; if it changes an orientation or inequality, keep both cases.

## Failure Modes
Non-exhaustive cases, overlapping cases with incompatible conclusions, division by a branch-zero term, and an invalid WLOG reduction that changes the hypothesis or target.

## Counterexample Patterns
Try zero, equal variables, negative values, the omitted permutation, and a parameter at the partition boundary. These commonly expose a missing case or false symmetry.

## Verification Recipe
Mathematical verification proves coverage, disjointness, and each branch. Host verification uses `symbolic_equivalence` for conditional normalization of a branch or symmetry map; it cannot certify exhaustiveness or WLOG validity and is only supporting algebra.

## Mini Example
For a symmetric inequality in x,y, split x≥y and y≥x; equality lies in both but has the same target. The WLOG statement is justified only after showing the inequality is invariant under swapping x and y.

## Alternative Strategy
Use a symmetric polynomial reduction, an invariant, or a direct extremal argument when case growth is excessive. Keep a finite case enumerator as evidence, not a universal proof.

## Stop / Escalate Conditions
Escalate when coverage cannot be proved, cases proliferate without new obligations, the target is not invariant, or an equality/boundary branch remains open.
