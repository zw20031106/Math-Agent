# ADR-005：F5 候选池、Solver 交叉审阅与 Rebuttal

- 状态：Accepted
- 日期：2026-08-08
- 阶段：F5

## 决策

1. 正式自主管线启用题级 `CandidatePool`。候选登记必须绑定
   `author_agent_id`、模型 `source_turn_id` 和 `CandidateArtifact`，不能仅凭
   Candidate 文本推断“多 Agent”。
2. 独立性门同时检查作者、模型 Turn、方法族、representation、核心不变量、
   proof direction 和 Claim 拓扑。实质重复候选保留审计记录，但状态为
   `rejected`，不计入两份独立候选。
3. 两份独立 Candidate 发布前继续隔离；发布后建立两条独立 Review Thread，
   分别执行 Primary→Alternative 和 Alternative→Primary 的真实模型审阅。
4. Peer Review 必须引用精确 Candidate 版本与真实 Claim；Host 只校验 Schema、
   引用和权限，不生成审阅结论。
5. Review 通过 Message 发回作者，作者在新的模型 Turn 中对 Finding 执行
   `defend`、`clarify` 或 `concede`。F5 不允许借 Rebuttal 静默修复 Candidate。
6. Rebuttal 后线程关闭；没有新 Artifact/公开增量的重复内容不能重开。新的
   Candidate 版本可作为后续阶段重开的依据。
7. `concede` 会把候选状态更新为 `rejected`，并在证据准入前从活动候选中
   剔除；未解决 Peer Finding 进入 Conflict Graph，供下游 Verifier 消费。

## 资源与边界

- F5 为每个满足独立性门的问题增加四个认知调用：两个 Peer Review 和两个
  Rebuttal；它们属于 48 次题级硬上限内的 closure work。
- 单次 Review/Rebuttal 使用 `peer_review` 档位：6144 tokens、180 秒阶段上限、
  90 秒最小启动窗口。
- 外层题目并发仍为 3，全局模型调用由 6 并发槽和 200 RPM 加权滚动限制统一
  控制，没有新增私有模型客户端。
- F5 不实现 F6 的 Verifier Cross Exam、Repair/New Branch 或 Final Audit。

## 后果

正式路径现在能证明候选来自不同 Agent 和不同模型调用，交叉审阅及作者回应
也具备 Artifact/Message/Thread 因果链。若独立性门失败或模型返回无效 Review，
Trace 会明确记录 partial/failed，而不会由 Host 补写“通过”的伪结果。
