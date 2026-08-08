# Phase F6 验证、Repair/New Branch 与 Final Audit 实施报告

## 结论

Phase F6 已按最终整改方案完成。正式 Competition 路径现在不是在 Solver 相互
审阅后直接仲裁，而是进入独立 Verifier Cross Exam；Verifier 对 Candidate 本身、
Peer Review 和 Rebuttal 做二阶检查，并用结构化 Critique 决定保留、局部修复、
新分支、重规划或拒绝。最终候选再由新的 Verifier 实例独立审计，确定性 Host
仲裁提交 DecisionArtifact。

## 实施内容

### 1. Cross Exam 与 CritiqueArtifact

`VerificationClosureAgent.cross_exam()` 是独立 `client.chat` 调用。输入只包含
公开、规范化对象：ProblemIR、CandidatePool、Candidate、Proof Obligation、
Evidence、Peer Review 和 Rebuttal。输出必须是 AgentTurnPayload 包裹的严格
`CritiqueArtifact`：

- Finding 引用真实 Candidate/Claim/Obligation；
- Peer Review 原始 Finding ID 冲突时使用限定引用；
- 每个 Peer Finding 都必须有二阶 `pass`/`fail`/`unknown` 评估；
- local/global/review scope 与 actionability 分离；
- global failure + local repair 在 Schema 层直接拒绝。

### 2. 局部 Repair 闭环

只有 Critique 中 `fail + local + local_repair` 的 Claim 才进入 Repair。RepairAgent
收到触发 Critique 和失败 Claim 依赖闭包，在新模型 Turn 中发布
`RepairPatchArtifact`，其父 Artifact 是触发 Critique。Host 生成版本化候选并：

1. 重新执行 Candidate admission 与答案形状检查；
2. 重新生成 Proof Obligation；
3. 对受影响 Claim 重新运行 Evidence；
4. 使用新的 Verifier Cross Exam 审查修复版本；
5. 比较修复前后证据质量和 Proof completion。

任一步不可用、证据质量下降、Proof 不闭合或没有严格改善都会回滚。Trace 固定
记录触发 Critique ID、Repair Artifact、受影响/重验 Claim、证据引用和
committed/rolled_back 原因，避免复审产生的新 Critique 覆盖原触发来源。

### 3. 全局错误 New Branch

核心方法错误不会进入 Repair。系统先让 RouterPlanner 发布继承原条件摘要的权威
Replan，再创建新的 `solve_new_branch` Task。新 Solver Candidate 使用新的
Agent/Task/Turn/Call，CandidateArtifact 以触发 Critique 为父；之后重新进入 F5
双向 Peer Review、双方 Rebuttal、Evidence、Proof Obligation 和第二次 Cross
Exam。新分支因此不是 Host 复制候选或更换标签。

### 4. Final Audit 与 DecisionArtifact

证据和证明闭合后，确定性仲裁先选出一个暂定最终 Candidate。新的
VerifierSkeptic `final_audit` 实例只接收这个 Candidate 精确版本及其规范化闭环
Artifact，不读取其他候选全文。Audit 状态限定为：

- `complete_hard`；
- `complete_audited`；
- `incomplete`；
- `failed`。

Audit incomplete 且存在新行动与闭环预算时可重新进入 Cross Exam，再由新的
Final Audit 实例复核；重复状态或资源不足时安全停止。最终确定性仲裁发布
service-authored DecisionArtifact，父引用 CandidateArtifact 和可用 AuditArtifact，
明确区分 LLM 审计与 Host 选择权。

### 5. Trace、配置与资源

新增公开事件：`new_branch_started/completed`、`final_audit_started/completed`、
`audit_reentry_decision`、`decision_committed`。Agent protocol 展示 Cross Exam、
Repair、New Branch、Final Audit 的 Agent/Task/Turn/Artifact/Message 谱系；不暴露
Prompt、原始响应、异常正文、失败候选全文或私有推理。

Competition 新增 `enable_verification_closure=true`。其余正式资源边界不变：

- 每题统一 48 次逻辑调用硬上限；
- 16/28/40 软检查点和 8 次 closure reserve；
- 题目并发 3；
- Provider 200 RPM；
- 分层 Timeout/Token 与统一 Deadline。

Judge Trace 的 `model_activity` 在调用较多时使用两级字段压缩，保持调用序号、
Agent 身份、模式、目的、Candidate 引用和状态，不因长程审查超过单事件大小而
破坏公开输出。

## 验收覆盖

新增 `tests/test_f6_verification_closure.py` 覆盖：

- Cross Exam 与 Final Audit 是不同 Verifier 实例和不同模型调用；
- Verifier 对每个 Peer Finding 做二阶检查；
- Final Audit 只看最终 Candidate；
- global failure 不能伪装成 local repair；
- RepairAgent 独立调用、引用真实 Critique、执行重验/回滚；
- 全局错误触发 Router Replan、新 Solver branch、再次 Peer Review 和 Cross Exam；
- Audit incomplete 触发下一审查/审计循环；
- Final Audit Transport 不可用时非空安全降级；
- DecisionArtifact 为确定性服务产物并引用最终 Audit。

## 后续阶段

F7 继续处理 runtime 模块拆分、统一 Proof 状态语义、旧兼容路径清理，以及从
Agent 事件投影完整 Trace。F6 不提前删除这些兼容路径。
