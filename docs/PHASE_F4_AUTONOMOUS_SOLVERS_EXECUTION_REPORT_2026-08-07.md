# Phase F4 自主长程 Solver 与 LLM LemmaCurator 实施报告

日期：2026-08-07

## 结论

Phase F4 已完成。正式自主管线在强制 Router 后调用独立 LLM LemmaCurator，随后
让 PrimarySolver 与 AlternativeSolver 使用彼此隔离的公开状态自主执行多轮
Action。Host 不再预设 `planned_rounds`，也没有残留的六次 Solver 限制；题级
48 次硬上限、16/28/40 软检查点、八次闭合预留、并发 3 与全局 200 RPM 仍有效。

F4 只完成自主探索、通信、Candidate 发布和截断恢复。候选双向交叉审阅与
Rebuttal 属于 F5，Verifier/Repair/Final Audit 属于后续阶段。

## 已实现

- 严格 `AgentTurnPayload 1.0` parser：精确字段、Action 白名单、嵌套 Host ID
  拒绝、Action/Artifact 类型一致性和 domain payload 二次校验。
- Primary 与 Alternative 都可自主 `continue_reasoning`、`request_lemma`、
  `request_tool_check`、`request_replan`、`complete` 或 `abstain`。
- 两个 Solver 在首次 Candidate 前使用独立 `ReasoningState` 和上下文；初始公共
  Lemma 可共享，但 Primary Candidate、完整正文与私有进展不可进入 Alternative。
- Stall detector 对公开 Artifact 做语义 hash 和信息增益检查：真实增量可连续超过
  十轮，相同 hash 或无新增公开事实时停止并转 Candidate 合成。
- LemmaCurator 每题进行独立 LLM 调用；Solver 请求可唤醒新的 Lemma Turn，并通过
  `lemma_requested` / `lemma_published` 消息返回。未验证 Lemma 始终是 provisional。
- Tool 请求只由 Host 构造和执行安全检查；Router Replan 保留父 Plan、原始条件
  摘要和版本链，并更新请求分支的方法约束。
- Progress、standard Candidate、proof Candidate 和 compact synthesis 使用独立
  Turn kind 与 Token/Timeout Contract：4096、8192、12288、8192。
- `finish_reason=length` 和观察到的输出超限产生 partial Candidate Artifact；原响应
  不被直接解析为完成 Candidate，恢复使用新的 compact-synthesis 调用。
- Provider 拒绝 12288 proof 输出时，Trace 记录 canary 降级并以 8192 compact
  重试；16384 未进入正式配置。
- Agent Protocol 的权威模式标记为 `autonomous_agent_action`；通信保留公开候选
  摘要，不保留完整失败候选正文。

## 验收覆盖

- 十个连续信息增量 Turn 可继续，且 `reasoning_loop_completed` 不含
  `planned_rounds`。
- 重复 hash 停止；`continue_reasoning` 创建新模型 Turn。
- 每题初始 LemmaCurator 独立调用，按需 Lemma request/reply 唤醒 Solver。
- 未验证 Lemma 不作为 Evidence；Primary 与 Alternative 的首次 Candidate 前状态
  隔离。
- 两个 Solver 可同时弃权，系统返回非空安全 fallback，不强造候选。
- Progress=4096、standard Candidate=8192、proof Candidate=12288。
- length 截断只产生 partial Artifact，并触发 8192 compact synthesis。
- Provider 不支持 12288 时显式降级而非静默伪装。

## 下一阶段边界

F5 应在现有 Candidate Artifact 和 Message 基础上实现 CandidatePool、结构独立性
门、Primary 对 Alternative 与 Alternative 对 Primary 的独立 LLM Peer Review、
Claim/Obligation 级 ReviewTarget、作者 Rebuttal 和候选版本链。F5 不应退回共享
全文 Prompt 或由 Host 伪造审阅结论。
