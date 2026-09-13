---
name: eigenvalue-diagonalization
version: 3.0
format: mmat-method-card-v1
domain: linear_algebra
subdomain: linear map
kind: method
roles: PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent
triggers: eigenvalue, diagonalizable, eigenvector
problem_patterns: diagonalize matrix, spectrum
method_family: eigenvalue-diagonalization
alternative_skills: jordan-form
description: Diagonalize a finite-dimensional operator only when eigenvectors form a basis over the stated scalar field.
negative_triggers: unavailable exact roots, ambiguous scalar field, one eigenvector for a repeated root
required_observables: scalar field, characteristic polynomial, eigenspace dimensions
requires: symbolic_equivalence
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: symbolic_equivalence
---
## Quick Dispatch

- 方法卡：`eigenvalue-diagonalization`（Skill 3.0，method）；适用角色：PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent。
- 结构触发：eigenvalue, diagonalizable, eigenvector；问题模式：diagonalize matrix, spectrum；核心方法族：`eigenvalue-diagonalization`。
- 关键词只用于检索，必须继续核对后文的精确前提；不满足前提时不得套用。

## Input Contract

- 必须读取原题、`ProblemIR`、公开条件、当前 Proof Obligation 和已消费的公共状态。
- 本卡声明的 Host 能力：symbolic_equivalence；验证 hooks：symbolic_equivalence。能力不可用时由主机降级或
  选择替代 Skill（声明替代：jordan-form），模型不得伪造工具结果。
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
Use when the target asks for a basis P and diagonal D with AP=PD or asks whether a matrix is diagonalizable.

## Do Not Use When
Do not infer diagonalizability from a complete list of eigenvalues, a numerical eigensolver, or a rectangular matrix. The scalar field and exact eigenspace dimensions are decisive.

## Core Theorem
A finite-dimensional operator is diagonalizable over F exactly when the direct sum of its eigenspaces has dimension equal to the space, equivalently when a basis of eigenvectors exists over F.

## Exact Preconditions
State F and the vector-space dimension. Factor the characteristic polynomial over F, compute each eigenspace dimension, and verify the total geometric multiplicity equals the dimension. For an explicit P, prove det(P)≠0.

## Procedure
1. Compute the characteristic polynomial and its roots over F.
2. Solve (A−λI)v=0 for a basis in each eigenspace.
3. Count independent eigenvectors and assemble P and D.
4. Verify P is invertible and AP=PD exactly, with all domain/field assumptions recorded.

## Branch Conditions
Handle repeated roots, complex field extensions, and the nondiagonalizable case separately. Distinct roots are sufficient but not necessary.

## Failure Modes
Replacing geometric multiplicity by algebraic multiplicity, using approximate roots as exact, or skipping P invertibility invalidates the similarity claim.

## Counterexample Patterns
Test a single Jordan block: its repeated eigenvalue has algebraic multiplicity two but only one independent eigenvector.

## Verification Recipe
Use `symbolic_equivalence` to check AP=PD and determinant identities only under the stated field/domain assumptions. A symbolic equality does not prove that P exists or is invertible; the proof trace must close the eigenspace-basis obligation.

## Mini Example
diag(2,3) is already diagonal over the reals with P=I and two independent standard eigenvectors.

## Alternative Strategy
Use Jordan form when the eigenspaces do not span, or the spectral theorem when symmetry/Hermiticity supplies an orthonormal basis.

## Stop / Escalate Conditions
Escalate when roots are unavailable over F, eigenspace dimensions are unresolved, or det(P) is not certified. Do not promote approximate numerical diagonalization to an exact result.
