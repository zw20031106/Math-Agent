---
name: spectral-theorem
version: 3.0
format: mmat-method-card-v1
domain: linear_algebra
subdomain: linear map
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: spectral theorem, symmetric matrix, self-adjoint
problem_patterns: orthogonal diagonalization, Hermitian
method_family: spectral-theorem
alternative_skills: eigenvalue-diagonalization
description: Use the real symmetric or complex Hermitian spectral theorem only after the inner-product hypotheses are verified.
negative_triggers: merely diagonalizable, nonsymmetric matrix, unspecified inner product
required_observables: finite dimensional inner product, symmetry or self-adjointness, orthonormal basis
requires: matrix_shape_check
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: matrix_shape_check
---
## Quick Dispatch

- 方法卡：`spectral-theorem`（Skill 3.0，method）；适用角色：PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent。
- 结构触发：spectral theorem, symmetric matrix, self-adjoint；问题模式：orthogonal diagonalization, Hermitian；核心方法族：`spectral-theorem`。
- 关键词只用于检索，必须继续核对后文的精确前提；不满足前提时不得套用。

## Input Contract

- 必须读取原题、`ProblemIR`、公开条件、当前 Proof Obligation 和已消费的公共状态。
- 本卡声明的 Host 能力：matrix_shape_check；验证 hooks：matrix_shape_check。能力不可用时由主机降级或
  选择替代 Skill（声明替代：eigenvalue-diagonalization），模型不得伪造工具结果。
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

- 声明 hooks：matrix_shape_check。它们只提供各自 policy 规定的证据强度；数值残差、有限枚举、
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
Use when the target concerns orthogonal/unitary diagonalization, an orthonormal eigenbasis, or spectral decomposition of a finite-dimensional self-adjoint operator.

## Do Not Use When
Do not apply merely because eigenvalues exist. A diagonalizable nonsymmetric matrix need not be orthogonally diagonalizable, and “symmetric” depends on the specified inner product and field.

## Core Theorem
Every real symmetric matrix is orthogonally diagonalizable, and every complex Hermitian matrix is unitarily diagonalizable with real eigenvalues. The statement is finite-dimensional and inner-product dependent.

## Exact Preconditions
State the scalar field, finite dimension, and inner product. Verify A=A^T over the reals or A=A* over the complexes in that inner product; then verify the eigenvectors can be normalized to an orthonormal basis.

## Procedure
1. Check the adjoint/symmetry identity with the correct conjugation.
2. Find eigenvalues and eigenspaces, retaining algebraic/geometric multiplicities.
3. Orthogonalize within repeated eigenspaces and normalize.
4. Form Q and verify Q*Q=I and Q*AQ is diagonal, including dimensions.
5. State the resulting spectral sum and its field of scalars.

## Branch Conditions
Separate real symmetric and complex Hermitian cases, and treat a nonstandard inner product by computing the corresponding adjoint rather than using A^T blindly.

## Failure Modes
Confusing ordinary transpose with conjugate transpose, checking only eigenvalue reality, or assuming any diagonalization is orthogonal leaves the theorem unproved.

## Counterexample Patterns
Use a nonsymmetric matrix with distinct eigenvalues to show diagonalizable does not imply orthogonally diagonalizable. Change the inner product and recheck the adjoint relation.

## Verification Recipe
`matrix_shape_check` verifies only dimensions and rectangular shape; it cannot verify symmetry, unitarity, or diagonalization. The Verifier must check A=A* and Q*Q=I/Q*AQ diagonal explicitly; a shape pass is only a structural support record.

## Mini Example
A real diagonal matrix is symmetric, its standard basis is orthonormal, and Q=I gives the spectral decomposition directly.

## Alternative Strategy
Use general eigenvalue diagonalization when orthogonality is not available, or use quadratic-form arguments when the target is an extremal property.

## Stop / Escalate Conditions
Escalate when the inner product, adjoint relation, field, or orthonormal basis is unspecified. Do not report a spectral theorem pass from matrix shape alone.
