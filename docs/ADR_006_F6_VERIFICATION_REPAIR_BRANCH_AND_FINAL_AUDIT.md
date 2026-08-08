# ADR-006：F6 验证、修复/新分支与最终审计闭环

- 状态：Accepted
- 日期：2026-08-08
- 阶段：F6

## 决策

1. F5 的 Solver Peer Review 不是最终裁决。独立 `VerifierSkeptic` 必须在新的
   `cross_exam` 模型 Turn 中读取 CandidatePool、Peer Review、Rebuttal、Evidence
   和 Proof Obligation，并对每个 Peer Finding 做二次审查。
2. Cross Exam 只发布严格、可引用的 `CritiqueArtifact`。每个 Finding 必须绑定
   真实 Candidate、Claim、义务和 Peer Finding；`unknown` 不得作为 `pass`。
3. Actionability 是安全边界：Claim 局部错误才可进入 `local_repair`；核心方法、
   全局假设或证明方向错误只能进入 `new_branch`/`replan`/`reject`，不得伪装成
   局部 Patch。
4. `RepairAgent` 是独立模型调用，输入 Artifact 必须包含触发它的真实
   Critique。Host 只允许修改失败 Claim 的依赖闭包，生成新 Candidate 版本，
   再执行确定性证据重验和新的 Verifier Turn。证据下降、证明未闭合或没有严格
   改善时回滚，旧 Candidate 保持有效。
5. 全局错误触发 Router 权威 Replan 和新的 Solver `solve_new_branch` Task。
   新 Candidate 必须有新 Agent/Task/Turn/Call，并以 Critique 为父 Artifact；随后
   重新进入双向 Solver Peer Review、Rebuttal、Evidence 和 Cross Exam。
6. `final_audit` 使用与 Cross Exam 不同的 VerifierSkeptic 实例和独立模型调用，
   且只接收暂定最终 Candidate 的一个精确版本。`incomplete`/`failed` 不自动升级
   为通过；存在新行动和剩余闭环资源时可重新进入审查循环。
7. 最终选择仍由确定性仲裁服务执行。它发布
   `DecisionArtifact(producer_kind=deterministic_service)`，父引用最终 Candidate
   Artifact 和可用 AuditArtifact，不冒充 LLM Agent，也不让加权分数越过硬证据
   门。

## 资源与降级

- F6 不设置“每题六次调用”之类阶段硬截断，所有调用共同受题级 48 次硬上限、
  软检查点和八次 closure reserve 约束。
- 题目并发保持 3，全局 Provider 保持 200 RPM；所有认知调用仍只经过注入的
  `client.chat`、统一 semaphore、速率门和 Deadline。
- Final Audit 不可用时保留已有安全 Candidate 并显式记录 degraded；不会因为
  审计 Transport 失败返回空答案，也不会伪造 Audit pass。

## 后果

Candidate、Peer Review、Rebuttal、Critique、Repair/New Branch、Audit 和
Decision 形成可检查的因果链。Repair 不能脱离 Critique 提交，全局错误不能通过
局部重写掩盖；同时，长程题仍可在统一资源治理内自主发起多轮验证。
