---
name: lean-proof-workflow
version: 3.0
format: mmat-method-card-v1
domain: logic
subdomain: formal_methods
kind: method
roles: PrimarySolver,AlternativeSolver,LemmaCurator,VerifierSkeptic,RepairAgent
triggers: Lean proof, formalize theorem, proof assistant, compile proof, theorem statement
problem_patterns: theorem-to-formal-statement, proof skeleton, tactic failure diagnosis
method_family: statement-first-formal-proof-workflow
alternative_skills: proof-theory,proof-obligation
description: Organize a statement-first, bottom-up formalization workflow while reporting honestly when no Lean host checker is available.
negative_triggers: claim of compiled proof without Lean output, informal proof only, unsupported library theorem
required_observables: formal statement, imports/context, proof skeleton, compiler evidence, remaining goals
requires: safe_parse_expression
failure_signals: missing_condition, contradiction, verification_failed
verification_hooks: safe_parse_expression
---
## Quick Dispatch

- 方法卡：`lean-proof-workflow`（Skill 3.0，method）；适用角色：PrimarySolver, AlternativeSolver, LemmaCurator, VerifierSkeptic, RepairAgent。
- 结构触发：Lean proof, formalize theorem, proof assistant, compile proof, theorem statement；问题模式：theorem-to-formal-statement, proof skeleton, tactic failure diagnosis；核心方法族：`statement-first-formal-proof-workflow`。
- 关键词只用于检索，必须继续核对后文的精确前提；不满足前提时不得套用。

## Input Contract

- 必须读取原题、`ProblemIR`、公开条件、当前 Proof Obligation 和已消费的公共状态。
- 本卡声明的 Host 能力：safe_parse_expression；验证 hooks：safe_parse_expression。能力不可用时由主机降级或
  选择替代 Skill（声明替代：proof-theory, proof-obligation），模型不得伪造工具结果。
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

- 声明 hooks：safe_parse_expression。它们只提供各自 policy 规定的证据强度；数值残差、有限枚举、
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
Use when a mathematical solution should be translated into a Lean-style theorem statement, dependency-aware proof skeleton, and a sequence of small goals.

## Do Not Use When
Do not report a formal proof pass from text parsing, do not invent imports or library lemmas, and do not claim compiler evidence when the Host has no Lean capability. This package is workflow guidance, not a Lean kernel.

## Core Theorem
Formal proof engineering benefits from statement first, design top-down, and prove bottom-up: fix types and hypotheses, split the target into small lemmas, and discharge goals with mechanically checked evidence. Without a compiler/kernel result, formal validity is unresolved.

## Exact Preconditions
Freeze the theorem statement, universes/types, imports, notation, and assumptions. Record the expected Lean version and the exact checker output when available. If no Lean tool is registered, mark the formal-verification obligation `unsupported` before producing any claim.

## Procedure
1. Write and review the smallest complete statement before tactic search.
2. Build a proof skeleton whose holes correspond to named mathematical obligations.
3. Prove bottom-up, keeping each lemma’s assumptions and output types explicit.
4. Run the configured checker only through an approved Host capability and preserve its evidence/version.
5. Translate compiler failures into claim-local repairs; re-run after each material change and never hide an unsolved goal.

## Branch Conditions
Separate elaboration/type errors, missing imports, tactic failures, false statements, and resource/time failures. A successful parser check closes syntax only; a compiler/kernel check is required for a formal proof claim.

## Failure Modes
Overly broad statements, implicit coercions, circular lemmas, brittle automation, unreported `sorry`/holes, and a proof script copied from a different library version.

## Counterexample Patterns
Try an empty type, a missing nonzero hypothesis, a coercion from naturals to integers, and a theorem whose informal statement is stronger than its formal one. Check that every admitted hole is visible.

## Verification Recipe
Host verification currently has only `safe_parse_expression`, which checks restricted syntax/grammar and is not a Lean checker; it is supporting syntax evidence only and cannot prove theorem meaning or kernel acceptance. If no Lean capability is available, final status must be `unsupported` or `incomplete`, never formally verified.

## Mini Example
First state `theorem add_zero (n : Nat) : n + 0 = n`. Then create the one-line proof obligation and record actual checker output. A parsed string without a Lean run is not evidence of compilation.

## Alternative Strategy
Keep an informal proof with explicit obligations and use proof-theory for rule auditing. Defer formalization until the required Host capability is provisioned.

## Stop / Escalate Conditions
Escalate when the statement or imports are unstable, a goal remains unsolved, compiler evidence is absent, or the user asks to convert syntax support into a formal correctness claim.
