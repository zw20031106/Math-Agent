# ADR-004：激活 LLM LemmaCurator 与自主 Solver Action 循环

- 状态：Accepted
- 日期：2026-08-07
- 阶段：F4

## 背景

F3 已保证每题先经 RouterPlanner，但 Solver 仍由固定轮数或单次 Candidate 调用
驱动，LemmaCurator 也仍是确定性服务。这不能满足独立模型 Agent、自主继续、
显式通信和长程推理的要求。旧的每题六次限制已由 F1 的 48 次题级硬上限替代，
同时保留并发 3、全局 200 RPM、Deadline 和闭合预留。

## 决策

1. PrimarySolver 与 AlternativeSolver 在首次 Candidate 前使用独立
   `ReasoningState`、Agent、Task 和模型 Turn；Alternative 不读取 Primary 的候选
   正文或私有进展。
2. Solver 每次返回严格 `AgentTurnPayload 1.0`，自主选择继续、请求 Lemma、请求
   Host Tool、请求 Router Replan、进入 Candidate 合成或弃权。
3. Host 不设置 Solver 固定轮数。继续条件由公开信息增益、重复 Artifact hash、
   ResourceGovernor、Deadline 和 Agent Action共同决定。
4. LemmaCurator 激活为每题至少一次的独立 LLM Agent，并可由 Solver 请求再次
   唤醒。其 Lemma 一律为 `provisional`，没有 Evidence 时不能关闭证明义务。
5. 确定性 LemmaCurator 保留为候选后 Schema/验证与回退服务，不再代表正式认知
   Agent。ADR-001 因此被取代。
6. Progress Turn 使用 4096 tokens；标准和 compact Candidate 使用 8192；完整
   proof Candidate 使用 12288/270 秒 canary。不支持时显式降级为 8192 compact；
   16384 仍仅属于后续受控实验，不进入正式配置。
7. `finish_reason=length` 或观察到的输出越界只形成 partial Artifact，不能直接成为
  完整 Candidate；恢复必须创建新的 compact-synthesis Turn，且不重放被截断原文。

## 后果

- 长程题可在 48 次题级硬上限内持续产生真实信息增量，不再受六次或固定三轮限制。
- Agent 通信通过 Artifact/Message/Thread 可审计，模型不能伪造 Host ID。
- 两个 Solver 可以合法弃权；Host 不强迫它们编造 Candidate。
- Candidate Artifact 仅保留公开摘要字段，不保存完整失败候选正文或私有推理。
- F4 尚未实现双向 Peer Review、Rebuttal、Verifier Cross Exam 和 Final Audit；这些
  属于 F5–F7，不能因 F4 完成而宣称整个多 Agent 闭环已经完成。
