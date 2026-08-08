# Phase F5 候选池、交叉审阅与 Rebuttal 实施报告

## 结论

Phase F5 已按整改方案完成。Competition 正式自主管线在 PrimarySolver 与
AlternativeSolver 各自发布第一版 Candidate 后解除隔离，先通过结构独立性门，
再执行 A↔B 双向 Solver Peer Review 和双方作者 Rebuttal。四个协作 Turn 都是
独立的 `client.chat` 调用，并具有 Agent、Task、Turn、Artifact、Message 和
Review Thread 的完整公开谱系。

本阶段没有提前实现 F6：既有 Verifier 仍保留兼容路径，但 F5 未把它改造成
审查 Review/Rebuttal 的新 Cross Exam，也未增加 Repair/New Branch 或 Final
Audit。

## 实施内容

### 1. CandidatePool 与结构独立性门

每个 LLM Solver Candidate 登记以下不可缺少的来源信息：

- `author_agent_id`；
- `source_turn_id`；
- `candidate_artifact_id`；
- Candidate 精确版本；
- `MethodSignature`：method family、representation、core invariant、proof
  direction 与 Claim topology digest。

独立性不是按 Candidate 数量或方法标签计数。相同作者、相同模型 Turn 或在相同
答案下结构高度重合的 Candidate 会被标记为实质重复，保留在 Pool 审计快照中但
不计入独立候选。

### 2. 双向独立 Peer Review

独立性门通过后创建两个 `peer_review_candidate` Task：

1. PrimarySolver 审阅 Alternative Candidate；
2. AlternativeSolver 审阅 Primary Candidate。

每次审阅使用 Solver 自己的 Agent 身份和 `peer_review` Prompt mode，通过新的
模型调用生成 `PeerReviewArtifact`。Finding 必须引用真实 Candidate、版本、Claim，
并给出 status、severity、公开依据、缺失条件和反例尝试。Host 不生成 Review。

### 3. 作者 Rebuttal 与 Candidate 状态

Review 通过 `peer_review_published` Message 投递给 Candidate 作者。作者收到后
创建 `respond_to_peer_review` Task，并在新的模型调用中生成
`RebuttalArtifact`。每个回应引用真实 Finding，并只能执行：

- `defend`；
- `clarify`；
- `concede`。

作者 concede 后 Candidate 状态更新为 `rejected`，在证据准入与后续仲裁前被
剔除。F5 不允许在 Rebuttal 中原地改写 Candidate。

### 4. Review Thread 与无增量停止

每个被审 Candidate 使用独立线程，消息序列为：

`peer_review_requested → peer_review_published → rebuttal_published`

Rebuttal 发布后线程关闭。重复 payload hash 视为无新公开内容并停止循环；关闭
线程只有在提供未出现过的新 Candidate Artifact 时才允许重开。

### 5. 下游影响与 Trace

- Concede/重复候选会改变活动 Candidate 集合；
- 非 pass Peer Finding 会形成 Claim 级 Conflict Graph target；
- Verifier 输入能够读取 Solver Peer Review 与 Rebuttal；
- Judge Trace 展示 CandidatePool、双向 Review、Rebuttal、Artifact/Message/
  Thread ID、独立模型调用标记和线程关闭状态；
- Trace 不包含原始模型响应、完整失败候选或私有思维链。

## 配置与资源

- `enable_peer_cross_review=true` 仅在 Competition 正式自主管线启用；
- 每题 F5 正常增加 4 次逻辑模型调用，计入 48 次硬上限；
- Review/Rebuttal 复用 `peer_review` 档位：6144 tokens、180 秒阶段超时、90 秒
  最小启动窗口；
- closure reserve 仍为 8 次；
- 题目并发 3、模型并发 6、全局 200 RPM 均未改变。

## 验收覆盖

新增 `tests/test_f5_candidate_peer_review.py`，覆盖：

- 两个 Candidate 的不同 Agent/Turn/Artifact 来源；
- A-by-B 与 B-by-A 两个真实模型审阅；
- Review 非 Host 生成且引用真实 Claim；
- 作者收到 Message，Rebuttal 引用 Finding；
- 两条显式线程各自关闭；
- 重复内容关闭、只有新内容可重开；
- 实质重复 Candidate 不计为独立；
- `concede` 更新 Candidate 状态并影响下游准入；
- 正式 Judge Trace 在新增调用后仍满足单事件和总输出边界。

## 后续阶段

F6 应在本阶段 Artifact 和 Conflict Graph 基础上实现 Verifier Cross Exam，审查
Peer Review/Rebuttal 是否真正解决 Finding，并仅在证据触发时进入 claim-local
Repair 或 New Branch；随后再由后续阶段实现 Final Audit。
