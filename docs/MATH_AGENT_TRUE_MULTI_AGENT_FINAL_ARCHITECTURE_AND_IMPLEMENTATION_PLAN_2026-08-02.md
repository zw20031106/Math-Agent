# Math-Agent 真正多 Agent 最终架构方案与实施计划

> 最终方案日期：2026-08-02；日志驱动修订：2026-08-07
> 审查代码基线：b5a743426a85c7d843215dec590497a61f0067f2
> 方案状态：Final Design，尚未实施
> 上一版方案：MATH_AGENT_TRUE_MULTI_AGENT_AUDIT_AND_REMEDIATION_PLAN_2026-08-01.md
> 本文件根据最新要求重写并取代上一版中的调用调度、角色激活和长程推理设计；2026-08-02 最终修订保留单题硬调用上限，但废弃不合理的六次上限；2026-08-07 根据上一版测评日志同步修订阶段超时与 Solver Token/Turn 策略

---

## 0. 审查范围、输入文件与证据优先级

本文件是对当前 `math_agent` 项目的审查结论、目标架构和实施计划，不是本轮代码修改记录。审查输入包括：

- 当前仓库源代码、配置、测试、Runner 和注入式 `client.chat` 边界；
- `Math-Agent_真正多智能体整改方案_详细审查与实施设计.md`；
- `Math-Agent_Codex_真正多Agent架构审查与Harness整改提示词.md`；
- 上一版测评日志 `eval_log_4845c9e0b3d44f89a97080d924ebb4da.log`；该日志对应提交 `e1aee21`，本地当前基线为 `b5a7434`，因此只把可复核的运行统计用于策略校准，不把两版代码差异静默混为一谈；
- 用户在本轮补充的正式约束：题目并发 3、全局模型请求最高 200 次/分钟、每题必须先 Router、参与 Agent 独立调用并通信、不得把长程推理压缩成六次调用。

参考 Markdown 只作为待核验假设，不自动视为事实。证据优先级为：不可变项目契约与用户明确约束 > 当前源代码和可重复测试行为 > 当前有效配置与运行日志 > 参考方案中的设计主张。若参考文件与代码或最新用户约束冲突，以高优先级证据为准，并在本方案中明确标出取舍。

本文件只新增审查/设计文档；`main.py`、`llm_client.py` 及业务运行代码在本轮未修改。上一版 0801 方案保留在仓库中作为历史记录，本文件是当前应执行的权威版本。

---

## 1. 最新需求与最终设计决议

本方案以以下要求为最终约束：

1. 不考虑低难度题目的简化路径；
2. 每一道题都必须先经过 RouterPlanner Agent 的独立大模型调用；
3. 参与协作的每个认知 Agent 都必须独立调用大模型；
4. Agent 之间必须存在显式、可追踪、能改变后续行为的通信；
5. 每题保留有限的模型调用硬上限，但不能沿用六次上限；本方案建议 Competition 初始值为每题 48 次逻辑调用；
6. 支持同一 Agent 和多个 Agent 的长程、多轮模型调用；
7. Agent 必须体现自主决策，而不是由 Harness 写死全部下一步；
8. 每题必须形成多个独立候选答案；
9. Solver Agent 之间必须进行交叉审阅；
10. 必须有独立验证、修复、再验证和最终审计；
11. 题目并发保持为 3；
12. 全局模型请求最高为 200 次/分钟；
13. main.py 和 llm_client.py 不修改；
14. 所有模型调用仍只能使用注入的 client.chat 接口；
15. 评测期间题目之间状态严格隔离；
16. 阶段超时必须按角色、Turn 类型和输出规模分层，不能让 Router、短审阅和长证明共用同一个固定值；
17. Solver 的单次 `max_tokens` 不能统一固定为 8192：长程能力通过多轮 Progress Turn 获得，最终 Candidate 再按标准解答与完整证明分别配置输出上限。

最终设计因此作出以下关键决议：

- Competition 路径中 RouterPlanner 永远启用，不再有确定性路由直接跳过 LLM Router 的正常路径；
- 每题至少创建 PrimarySolver 和一个 AlternativeSolver，形成至少两个独立 Candidate；
- LemmaCurator 从确定性模板升级为真正的 LLM Agent，并参与每题的长程协作；
- PrimarySolver 与 AlternativeSolver 在独立提交 Candidate 后互相进行 LLM Peer Review；
- VerifierSkeptic 以 cross_exam 和 final_audit 两种独立实例参与；
- RepairAgent 在存在可操作缺陷时独立调用模型；
- 不再使用 `max_model_calls=6`，改为每题 48 次逻辑调用的总硬上限；
- 不再预先计划固定 planned_rounds；
- 16、28、40 次处设置软检查点，40 次后保留 8 次收敛额度；
- 在未达到硬上限时，调用是否继续由 Agent 自主 Action、公开信息增益、未闭合义务、消息请求、Deadline、全局 200 RPM 和模型并发共同决定；
- Provider 阶段调用采用按 Turn 类型分层的执行超时，并从“实际派发”开始计时；有效超时还必须受题级剩余 Deadline 与最终化预留约束；
- Solver 探索默认使用 4096-token Progress Turn，标准 Candidate 默认 8192 tokens，完整证明 Candidate 默认 12288 tokens；16384 只作为受控 canary 候选，不直接进入正式配置；
- `finish_reason=length`、阶段超时和后台尾调用成为一等运行事件：截断输出不得被当作完整 Candidate，超时后不得立即在同一 Agent 上制造重试风暴；
- Harness 保持确定性运行时和安全边界，不代替 Agent 生成开放式数学规划、解答、质询或修复内容。

---

## 2. 与上一版方案相比的实质变化

| 上一版假设 | 最终方案 |
|---|---|
| 低风险题可跳过 Router、Alternative、Cross Exam | 不再存在低难度简化路径 |
| 低风险题可只调用 Primary | 每题至少 Router、Primary、Alternative、Lemma、Verifier |
| 每题最多六次逻辑模型调用 | 每题最多 48 次逻辑调用，并在 16/28/40 次执行软检查 |
| Long Horizon 由 planned_rounds 控制 | 改为消息驱动、进展驱动的开放轮次 |
| LemmaCurator 保持确定性服务 | LemmaCurator 成为独立 LLM Agent |
| Solver 主要提交 Candidate，Verifier 统一审查 | Solver 先互审，再由 Verifier 独立审查 |
| Repair 与 Audit 受固定调用预算配对 | 由 ResourceGovernor 根据时间、进展和义务动态批准 |
| CallAllocationPlan 预分配各阶段次数 | 不按 Agent/阶段切死份额，改用共享总额度、优先级和资源准入 |
| max_model_calls=6 是硬安全边界 | 保留总硬边界但提高为 48；CallLedger 记录，SessionCallBudget 执行 |
| 所有 Solver Turn 统一最多输出 8192 tokens | Progress Turn 4096；标准 Candidate 8192；完整证明 Candidate 12288；16384 仅受控 canary |
| Router、Solver、Verifier 等阶段可共用固定 165 秒执行超时 | 按角色、Turn 类型和输出规模分层，并由实测 P95、Deadline 余额及最终化预留共同裁剪 |

仍然保留：

- 题目并发为 3；
- 全局 200 次/分钟；
- 模型并发门；
- Deadline；
- Provider Circuit Breaker；
- 确定性工具和硬证据门；
- Claim-local Repair；
- 确定性最终仲裁；
- 每题 Session 隔离；
- Trace 隐私约束。

---

## 3. 当前系统审查结论

当前系统已经有多个 LLM 角色、候选隔离、工具证据、Verifier 和 Repair，但角色仍是由一个 2700 余行的中心 solve 流程按预先确定阶段直接调用。

当前可准确描述为：

> 中央 Harness 控制的多角色、有限轮次、同模型数学推理流水线。

### 3.1 可复核的当前基线事实

| 位置 | 当前观察 | 对目标的影响 |
|---|---|---|
| `user_agent.py:14` | `CASE_MAX_CONCURRENCY = 4` | 与正式并发 3 冲突，必须由题内 Case Gate 限制为 3 |
| `scripts/run_benchmark.py:76`、`scripts/run_case_outputs.py:834` | 默认/校验范围仍允许并发 4 | Runner 层仍可能绕过正式并发约束 |
| `config/competition.json:5,8,38` | `model_max_concurrency=16`、`max_model_calls=6`、`enable_router=false` | 16 不是 RPM；6 无法容纳闭环；Router 不是强制首调用 |
| `mathforge/config.py:24,27,57,129–131` | 默认 `max_model_calls=6`，对字段做 1–64 校验 | 需要迁移为题级显式硬预算，并避免旧默认值回流 |
| `mathforge/runtime.py:334,555–686,3061–3164` | 仍创建 `CallBudget`，使用 `remaining_calls`、`planned_rounds` 和固定循环 | 中心 Host 仍掌握轮次和阶段调用权 |
| `mathforge/agents/router_planner.py:409,430`、`mathforge/harness/reasoning_state.py:1248–1288` | 存在 `max_reasoning_rounds`（当前最高 3） | 长程推理被预设轮次截断 |
| `mathforge/harness/provider.py:33–60` | 有模型并发门，但没有全局滚动 200 RPM 准入器 | 需要增加带传输重试权重的全局限流 |
| `llm_client.py:19,50–66` | `retry=3`，且为不可修改文件 | RPM 必须按保守物理尝试数预留，不能读取私有字段 |
| `mathforge/harness/lemma_loop.py:57`、相关确定性服务 | Lemma 流程当前不是每题独立 LLM Agent | 必须激活真实 LemmaCurator 调用和消息线程 |
| `mathforge/harness/model_policy.py` | Provider 响应 120 秒、HTTP grace 30 秒、调用 grace 15 秒，主要阶段最终均落到 165 秒 | 对约 8K 长输出过短，而且没有区分 Router、Progress、Candidate、Proof、Review、Repair |
| `mathforge/agents/prompt_compiler.py` | Primary/Alternative 的 minimal、standard、tool、proof 与 progress 输出上限均为 8192 | 配置中的更大 Solver 上限会被编译器取最小值，实际形成“一刀切 8192” |
| `mathforge/harness/provider.py` | 阶段超时后调用转为后台尾任务，迟到成功结果不再进入当前状态 | 超时配置过短会同时制造逻辑失败、并发槽占用和重试放大 |

因此，本文的 48 次设计是对现有六次限制的有界替换，不是把限制删除后交给 Provider 或模型自行失控。

### 3.2 上一版测评日志对超时与 Token 策略的校准证据

对所给上一版日志可复核得到：

- 112 题中 82 题为 `invalid`，占 73.2%；Runner 均成功结束，没有证据指向外层进程崩溃或 1200 秒整题超时；
- 共记录 342 次模型请求，但只找到 220 条完成记录，另有 122 次请求没有配对完成行；这不能逐条等同于超时，但说明模型调用生命周期存在大量未闭合事件；
- 220 条完成记录中有 177 条 `finish_reason=length`，占全部完成调用的 80.5%，说明截断不是边缘现象；
- 所有日志中的调用均使用 `max_tokens=8192`；响应字符数中位数约 24872，提示模型经常持续生成到输出边界；
- 已完成调用耗时 P50/P95 分别约 171.4/208.4 秒；`length` 调用 P50/P95 分别约 178.5/211.9 秒，而正常 `stop` 调用最大约 158.4 秒；
- 165 秒只覆盖 220 条完成记录中的 91 条（41.4%），240 秒覆盖 216 条（98.2%），270 秒覆盖 219 条（99.5%）；
- 82 个 Runner 题级耗时落在约 2、3、4 个 165 秒窗口附近，数量与 `invalid` 相同。由于日志不提供逐题完整调用关联，不能把它写成逐题因果证明，但这是固定 165 秒阶段超时放大 invalid 的强相关证据；
- 平均请求速率约 1.35 次/分钟，远低于 200 次/分钟，因此该批 invalid 的首要矛盾不是全局 RPM 上限。

据此，本方案不采用“只把 8192 调大”或“只把 165 秒无限放宽”的单变量修复，而是同步执行：

1. 用分层超时接受长输出的正常延迟，同时用题级 Deadline、最终化预留、后台尾调用上限和熔断控制最坏情况；
2. 将 Solver 的探索与最终合成拆成不同 Turn：探索使用较短输出并持续发布 ProgressArtifact，最终 Candidate 根据题型选择 8192 或 12288；
3. 将 `finish_reason=length` 视为不完整输出信号，禁止直接通过 Candidate 完整性门；
4. 以真实 canary 的 P50/P95、截断率、阶段超时率和 invalid 率冻结正式值，避免根据单份旧日志永久写死常数。

它尚不是真正多 Agent，原因是：

- 没有题内稳定 Agent 身份；
- 没有 Agent 自己的任务状态和邮箱；
- 没有统一 Message 和 Artifact 协议；
- Planner 不产生实际驱动任务分配的 DAG；
- Primary 的长程推理由 Host 预定最多若干轮；
- Alternative 生成后不参与作者级互审和回应；
- LemmaCurator 当前不调用模型；
- Verifier 是 Host 触发的一次性审查；
- Agent 不能自主选择继续、通信、请求审查、请求重规划或弃权；
- 当前固定 `max_model_calls=6` 甚至无法容纳强制 Router、双 Solver、Lemma、互审、Verifier 和 Final Audit 的最小闭环，会在 Agent 尚有有效进展时过早终止协作。

最终改造的重点不是增加更多类名，而是让现有固定角色成为真正的题内 Agent 实例。

---

## 4. 真正多 Agent 的最终判定标准

项目只有同时满足以下条件，才能宣称完成真正多 Agent 改造。

### 4.1 独立身份

- 每个题内 Agent 有唯一 agent_id；
- 同一角色的多个实例具有不同 ID；
- 每个模型调用绑定 agent_id、task_id 和 turn_id；
- Agent 实例只存在于当前 solve。

### 4.2 独立模型调用

- 每个参与 Agent 独立调用注入的 client.chat；
- 不得由 Host 伪造 Agent 输出；
- 不得把一个模型调用的输出复制成多个 Agent 结果；
- 独立不意味着创建不同客户端或读取不同 API Key；
- 独立指独立调用、独立 Prompt Contract、独立观察空间、独立 AgentState 和独立输出 Artifact。

### 4.3 独立观察

- RouterPlanner 只看 Problem 和公共状态；
- Solver 在首次 Candidate 发布前互相不可见；
- LemmaCurator 只看授权的 Problem、Plan、Claims、Obligations 和 Evidence；
- Peer Reviewer 只看对方公开 Candidate；
- Verifier 不读取 Solver 私有推理；
- Repair 只看授权影响闭包。

### 4.4 独立状态

- 每个 Agent 有 AgentState；
- AgentState 保存公开任务进度、Artifact 引用、消息和停止原因；
- 不保存私有思维链；
- Agent 可以多次被唤醒并延续自己的公开状态。

### 4.5 自主行动

每次 Agent Turn 必须由 Agent 自己选择一个受控 Action，例如：

- continue_reasoning；
- publish_candidate；
- request_tool_check；
- request_lemma；
- send_message；
- request_peer_review；
- challenge_candidate；
- publish_rebuttal；
- request_replan；
- request_repair；
- abstain；
- complete。

Host 可以根据权限、资源、Schema 和 Deadline 接受或拒绝 Action，但不能替 Agent 选择数学内容。

### 4.6 显式通信

- Agent 通过 MessageEnvelope 通信；
- Message 有发送者、接收者、线程、回复关系和 Artifact 引用；
- 通信必须实际触发后续 Agent Turn 或状态变化；
- 仅在 Host 内拼接字符串不算 Agent 通信。

### 4.7 多候选与交叉审阅

- 每题至少两个独立 Candidate；
- Candidate 发布前保持 Solver 隔离；
- Candidate 发布后双方必须独立调用模型审阅对方；
- 作者必须收到 PeerReview Artifact；
- 作者可以 Rebut、请求局部 Repair、请求新分支或承认失败；
- Verifier 在 Peer Review 之后独立审查。

### 4.8 长程持续性

- Agent 可以在同一题中进行多次模型 Turn，不为单个 Agent 预先切死调用份额；
- 团队共享每题 48 次逻辑调用硬上限，不再使用六次上限或固定最大推理轮数；
- 未达到硬上限时，是否继续取决于公开信息增益、开放义务、消息和时间；
- 每次 Turn 都形成状态增量或 Artifact；
- 达到 40 次后只允许消耗 8 次收敛预留；达到 48 次、重复无进展、Deadline 或 Provider 故障均可终止。

### 4.9 责任与验证

- 每个 Candidate 知道由谁产生；
- 每个 Critique 知道审查哪个版本；
- 每个 Rebuttal 回应具体 Finding；
- 每个 Repair 引用授权 Finding；
- 每个 Audit 引用最终 Candidate 版本；
- 最终 Decision 引用 Candidate、Evidence、Peer Review、Verifier 和 Audit。

---

## 5. 目标总体架构

    ReasoningAgent
      |
      | case gate: exactly max 3 active solves
      v
    MathForgeHarness
      |
      v
    SessionAgentRuntime
      |
      +-- ResourceGovernor
      |     +-- global 200 RPM limiter
      |     +-- model concurrency scheduler
      |     +-- case and agent fairness
      |     +-- stage execution timeout policy
      |     +-- output token policy
      |     +-- background tail controller
      |     +-- Deadline controller
      |     +-- provider circuit state
      |
      +-- AgentRegistry
      +-- AgentStateRegistry
      +-- TaskScheduler
      +-- SessionMailbox
      +-- SessionArtifactStore
      +-- ConversationThreadRegistry
      +-- SessionCallBudget (题级 48 次硬上限)
      +-- CallLedger
      |
      +-- Deterministic Services
      |     +-- parsing and schema
      |     +-- context ACL and compression
      |     +-- tools
      |     +-- evidence ledger
      |     +-- proof obligations
      |     +-- conflict graph
      |     +-- candidate admission
      |     +-- hard evidence gate
      |     +-- arbitration
      |     +-- formatting and trace projection
      |
      +-- LLM Agent Instances
            +-- RouterPlanner
            +-- PrimarySolver
            +-- AlternativeSolver one or more
            +-- LemmaCurator
            +-- PrimarySolver peer-review instance or mode
            +-- AlternativeSolver peer-review instance or mode
            +-- VerifierSkeptic cross_exam
            +-- RepairAgent when needed
            +-- VerifierSkeptic final_audit
            +-- optional LLMFinalizer

Host 负责安全、资源和确定性服务；Agent 负责规划、求解、通信、质询、回应、修复内容和审计判断。

---

## 6. 每题固定启动的核心 Agent 团队

每题不再根据难度减少团队。核心团队固定启动：

### 6.1 RouterPlanner

- 必须是题目的第一个认知模型调用；
- 输出 RouteArtifact 和 PlanArtifact；
- 可以在后续收到 blocked、conflict 或 replan 消息后再次调用模型；
- 不生成完整数学解答。

### 6.2 PrimarySolver

- 根据 Plan 执行一个主方法；
- 可以多轮探索；
- 可以请求 Lemma、工具检查、Peer Review 或 Replan；
- 最终发布 Candidate A。

### 6.3 AlternativeSolver

- 至少一个实例；
- 使用与 Primary 不同的表示、核心不变量、证明方向或定理链；
- 首次 Candidate 发布前看不到 Primary Candidate；
- 可以多轮探索；
- 最终发布 Candidate B。

RouterPlanner 可以创建多个 AlternativeSolver Task，但至少一个，不设置固定最大 Candidate 数。实际新增分支由进展、冲突、Deadline 和资源治理决定。

### 6.4 LemmaCurator

- 每题至少独立调用模型一次；
- 不再是 inactive deterministic template；
- 首次可根据 Problem 和 Plan 提议关键 Lemma、定义、边界条件和子目标；
- 后续可响应 Solver 的 lemma_request；
- 只能发布公开、可验证的 LemmaArtifact；
- Lemma 在有 Evidence 或 Verifier 支持前不得作为已证事实。

### 6.5 VerifierSkeptic

- 每题至少执行一次 cross_exam；
- 最终必须执行 final_audit；
- 两个模式使用不同 Agent 实例或至少不同 task_id、turn state 和观察快照；
- Final Audit 不读取 Cross Exam 的原始模型响应，只读取规范化 Artifact。

### 6.6 RepairAgent

- 仅在存在可操作局部缺陷时启动；
- 一旦启动，必须独立调用模型；
- 不能由 Host 自动拼接 Patch；
- 不能进行未授权全局重写。

### 6.7 LLMFinalizer

- 不属于数学正确性核心 Agent；
- 默认关闭；
- 若未来启用，必须独立调用模型并保持数学内容不变；
- 不影响“真正多 Agent”是否成立。

---

## 7. AgentDefinition、AgentInstance 与 AgentState

### 7.1 AgentDefinition

AgentDefinition 在 Harness 初始化时加载并只读共享：

    role
    capabilities
    allowed_modes
    accepted_task_types
    accepted_message_types
    readable_artifact_types
    writable_artifact_types
    allowed_action_types
    prompt_contract
    prompt_version
    skill_roles
    failure_policy

AgentDefinition 不包含题目状态。

### 7.2 AgentInstance

每个 solve 为每个 Agent 创建独立实例：

    agent_id
    session_id
    role
    mode
    descriptor
    state
    inbox
    active_task_id
    conversation_threads

推荐 agent_id：

    {session_id}:{role}:{mode}:{ordinal}

示例：

    session-x:RouterPlanner:plan:1
    session-x:PrimarySolver:solve:1
    session-x:AlternativeSolver:solve:1
    session-x:LemmaCurator:curate:1
    session-x:PrimarySolver:peer_review:1
    session-x:VerifierSkeptic:cross_exam:1
    session-x:VerifierSkeptic:final_audit:1

### 7.3 AgentState

AgentState 是题内公开控制状态：

    agent_id
    lifecycle_status
    active_task_id
    completed_task_ids
    current_goal_ids
    open_subgoal_ids
    open_obligation_ids
    input_artifact_ids
    output_artifact_ids
    unread_message_ids
    conversation_thread_ids
    last_action
    last_progress_digest
    information_gain_summary
    model_call_count
    session_calls_used
    session_calls_remaining
    budget_pressure
    stop_reason
    failure_code

`model_call_count` 用于观测单个 Agent 的调用分布，不设置按 Agent 切分的硬份额。`session_calls_used` 和 `session_calls_remaining` 来自题级 `SessionCallBudget`；所有 Agent 共享每题 48 次逻辑调用硬上限。

生命周期：

- created；
- ready；
- running；
- waiting_message；
- waiting_evidence；
- waiting_resource；
- completed；
- abstained；
- failed；
- cancelled。

---

## 8. Agent Turn 与自主 Action 协议

### 8.1 每次模型调用是一个 Agent Turn

Agent 被 Task 或 Message 唤醒后进行一次独立 client.chat 调用，输出 AgentTurnPayload：

    protocol_version
    task_result_type
    action
    public_state_delta
    result_payload
    outbound_intents
    progress_summary
    stop_reason

Host 生成：

- agent_id；
- task_id；
- turn_id；
- turn_kind；
- requested_max_output_tokens；
- stage_timeout_seconds；
- Artifact ID；
- Message ID；
- 时间和模型调用记录。

模型不得生成这些 Host-owned ID。

其中 `turn_kind`、`requested_max_output_tokens` 和 `stage_timeout_seconds` 由 Host 根据已校验 Task 类型与 Competition 配置注入，模型只能在允许的 Action 范围内请求下一类 Turn，不能自行绕过 Token、超时、Deadline 或收敛预留。单次输出上限只是该 Turn 的序列化边界，不是整题推理能力上限。

### 8.2 允许的 Action

#### continue_reasoning

表示：

- 当前尚未形成可提交 Candidate；
- 已产生新的公开子目标、Claim、Lemma 请求或 Evidence 需求；
- 希望下一次 Turn 延续。

必须提供：

- 新信息；
- 下一公开动作；
- 尚未解决的问题。

#### publish_candidate

发布完整 CandidateArtifact，并进入可交叉审阅状态。

#### request_tool_check

请求 Host 对真实 Claim 执行允许的确定性工具。Agent 只提供 check_type 建议和 Claim 引用，不提供未经验证的任意工具参数。

#### request_lemma

向 LemmaCurator 发送消息，说明需要的公开子目标、条件和目标义务。

#### send_message

向允许的 Agent 发送带 Artifact 引用的结构化消息。

#### request_peer_review

请求其他 Solver 审查已发布 Candidate。

#### challenge_candidate

Peer Reviewer 或 Verifier 发布 CritiqueArtifact。

#### publish_rebuttal

候选作者回应具体 Finding，可以：

- 接受；
- 反驳；
- 承认 unknown；
- 请求局部 Repair；
- 请求 New Branch；
- 请求 Replan。

#### request_replan

向 RouterPlanner 发送阻塞、冲突和已尝试方法摘要，要求更新 Plan。

#### request_repair

请求 RepairAgent 修复具体 Finding 和 Claim 影响闭包。

#### abstain

Agent 明确认为无法安全完成当前任务，不伪造 Candidate。

#### complete

当前任务目标已经完成，不再请求新 Turn。

### 8.3 Host 对 Action 的处理

Host 只做确定性验证：

- Action 是否被该角色允许；
- 引用 Artifact 是否存在且可见；
- 是否有公开信息增量；
- 是否与 Deadline 冲突；
- 是否触发全局 Rate Limit 或 Circuit Breaker；
- 是否形成消息、Task、工具请求或 Artifact。

Host 不得修改 Agent 的数学结论后假装是 Agent 决策。

---

## 9. AgentTask 协议

    AgentTask
      schema_version
      task_id
      session_id
      assigned_agent_id
      role
      mode
      objective
      input_artifact_ids
      conversation_thread_ids
      required_output_types
      allowed_actions
      allowed_tool_capabilities
      forbidden_artifact_types
      context_budget
      priority
      deadline_at
      parent_task_id
      status

### 9.1 Task 类型

- route_and_plan；
- replan；
- solve_primary；
- solve_alternative；
- continue_reasoning；
- curate_lemmas；
- answer_lemma_request；
- peer_review_candidate；
- respond_to_peer_review；
- cross_exam_candidates；
- repair_claims；
- solve_new_branch；
- final_audit；
- copy_finalize。

### 9.2 题级共享调用额度

Task 不包含按角色或按阶段分配的 `max_model_calls`。Task 可以读取题级 `session_calls_remaining` 和 `budget_pressure`，从而自主决定继续、发布候选、请求验证或结束，但不能绕过 `SessionCallBudget`。

Task 可以跨多个 Agent Turn，直到：

- Agent complete；
- Agent abstain；
- Task 被新 Plan 取代；
- 没有公开进展；
- 题级 48 次逻辑调用硬上限到达；
- Deadline 到达；
- Provider Circuit 打开；
- Host 发现协议或安全违规。

### 9.3 多轮 Task

同一 solve_primary Task 可以经历：

    Turn 1: explore and publish state delta
    Turn 2: consume tool evidence and continue
    Turn 3: receive lemma and continue
    Turn 4: publish draft candidate
    Turn 5: receive peer critique and rebut
    Turn 6: request new branch or complete

单个 Task 的 Turn 数不预设固定值，但所有 Task 共享题级 48 次逻辑调用硬上限。

---

## 10. 显式 Message 与对话线程

### 10.1 MessageEnvelope

    schema_version
    message_id
    session_id
    thread_id
    sender_agent_id
    recipient_agent_id
    message_type
    task_ref
    artifact_refs
    reply_to
    public_summary
    requested_action
    priority
    created_sequence
    expires_at

### 10.2 消息类型

- plan_published；
- task_assignment_proposed；
- progress_shared；
- lemma_requested；
- lemma_published；
- evidence_available；
- candidate_published；
- peer_review_requested；
- peer_review_published；
- rebuttal_published；
- conflict_escalated；
- replan_requested；
- repair_requested；
- repair_published；
- audit_requested；
- audit_published；
- task_abstained；
- task_failed；
- conversation_closed。

### 10.3 对话线程

每个协作问题形成 thread_id：

- plan thread；
- lemma thread；
- Candidate A review thread；
- Candidate B review thread；
- cross-exam thread；
- repair thread；
- final-audit thread。

Agent 可以在同一个 Thread 中多次回复，但每次回复必须：

- 引用前一消息；
- 引用新 Artifact 或新 Evidence；
- 提供公开增量；
- 不得重复相同 payload hash。

### 10.4 通信可见性

Trace 至少展示：

- sender role；
- recipient role；
- message type；
- thread ID 的安全摘要；
-引用 Artifact ID；
-消息是否触发新 Task；
-响应 Agent 和结果状态。

Trace 不展示私有 CoT 或完整失败模型响应。

---

## 11. Artifact Store 与候选池

### 11.1 ArtifactEnvelope

    schema_version
    artifact_id
    artifact_type
    session_id
    producer_agent_id
    producer_task_id
    producer_turn_id
    version
    parent_artifact_ids
    payload_schema
    payload
    payload_sha256
    claim_refs
    evidence_refs
    obligation_refs
    status
    created_sequence

### 11.2 Artifact 类型

- ProblemArtifact；
- RouteArtifact；
- PlanArtifact；
- ProgressArtifact；
- LemmaArtifact；
- CandidateArtifact；
- ToolRequestArtifact；
- EvidenceArtifact；
- ObligationArtifact；
- PeerReviewArtifact；
- RebuttalArtifact；
- ConflictGraphArtifact；
- CritiqueArtifact；
- RepairPatchArtifact；
- RepairResultArtifact；
- AuditArtifact；
- DecisionArtifact；
- CheckpointArtifact。

### 11.3 候选池

每题维护 CandidatePool：

    candidate_id
    author_agent_id
    method_family
    representation
    core_invariant
    proof_direction
    version
    parent_candidate_id
    status
    peer_review_ids
    verifier_finding_ids
    evidence_ids
    open_obligation_ids
    audit_id

Candidate 状态：

- draft；
- submitted；
- peer_reviewing；
- challenged；
- rebutted；
- repair_requested；
- revised；
- verified；
- incomplete；
- rejected；
- superseded；
- selected。

### 11.4 不可变与版本

- 已发布 Artifact 不可原地修改；
- Candidate Revision 形成新版本；
- Peer Review 引用精确 Candidate 版本；
- Repair 引用精确 Finding 和 Candidate 版本；
- Final Audit 只审查最终 active 版本；
- Decision 引用 selected version；
- Store 返回规范化重建对象，不暴露内部可变引用。

---

## 12. 每题完整长程协作流程

### 12.1 阶段 A：RouterPlanner 强制首调用

流程：

1. Host 解析 Problem 并发布 ProblemArtifact；
2. 创建 RouterPlanner AgentInstance；
3. 创建 route_and_plan Task；
4. RouterPlanner 独立调用模型；
5. 输出 RouteArtifact 和 PlanArtifact；
6. Host 校验 Plan DAG、角色、方法和 Artifact 引用；
7. RouterPlanner 向 Solver 和 LemmaCurator 发送 plan_published 消息。

RouterPlanner 必须输出：

- 领域与辅助领域；
- 目标形式；
- 子目标 DAG；
- 关键条件；
- Primary 方法任务；
- Alternative 方法任务；
- 预期 Lemma；
- Tool/Evidence 计划；
- Peer Review 重点；
- Verifier 风险目标；
- Replan 触发条件。

如果 Router 输出非法：

- 记录失败；
- 在 Deadline 允许时重新唤醒同一 Router 或创建新 Router Turn；
- Provider/Schema 持续失败时才回退确定性最小 Plan；
- 即使回退，也必须记录已尝试 Router Agent 调用。

### 12.2 阶段 B：LemmaCurator 初始分析

1. LemmaCurator 接收 Problem 和 Plan；
2. 独立调用模型；
3. 发布初始 LemmaArtifact；
4. 向 Primary 和 Alternative 发送 lemma_published；
5. Lemma 状态默认为 proposed；
6. Solver 可以使用其作为待证子目标，不能作为硬事实。

### 12.3 阶段 C：独立 Solver 长程探索

Primary 和 Alternative 并行或公平交错运行：

- 各自拥有独立 AgentState；
- 各自独立调用模型；
- 首次 Candidate 发布前互相不可见；
- 可以多次 continue_reasoning；
- 可以请求工具；
- 可以请求 Lemma；
- 可以请求 Router Replan；
- 可以因方法失败 abstain；
- 可以发布不同版本的 ProgressArtifact；
- 最终各自发布 CandidateArtifact。

Host 不预设三轮或六次，也不按 Solver 切固定份额；只要 Agent 有公开信息增量、题级额度尚未耗尽且资源允许，就可以继续。

### 12.4 阶段 D：候选独立性门

至少两个 Candidate 提交后，确定性检查：

- 方法族；
- 表示空间；
- 核心不变量；
- 证明方向；
- 定理集合；
- Claim Graph；
- Method Steps；
- Final Answer。

如果 Candidate 实质重复：

- 重复 Candidate 不作为独立证据；
- 给对应 Solver 发送 conflict_escalated；
- Agent 可以选择新方法继续、请求 Replan 或 abstain；
- 不因为字符串不同就认定独立。

### 12.5 阶段 E：Solver 交叉审阅

隔离解除后：

1. PrimarySolver 收到 Candidate B；
2. PrimarySolver 以 peer_review 模式独立调用模型；
3. 发布 PeerReview B-by-A；
4. AlternativeSolver 收到 Candidate A；
5. AlternativeSolver 以 peer_review 模式独立调用模型；
6. 发布 PeerReview A-by-B。

Peer Review 必须检查：

- Final Answer；
- 关键 Claim；
- 定理前提；
- 边界条件；
- 隐含假设；
- 与自己方法的冲突；
- 可构造反例；
- 未闭合义务。

Peer Reviewer 不能修改对方 Candidate，也不能产生 hard evidence。

### 12.6 阶段 F：作者回应

Candidate 作者收到 PeerReview 后独立进行 Agent Turn，发布 RebuttalArtifact：

- accept_finding；
- rebut_with_claim；
- request_tool_evidence；
- request_lemma；
- request_repair；
- request_new_branch；
- request_replan；
- concede_candidate；
- complete_response。

Rebuttal 必须逐条引用 Finding。

作者不能通过简单说“不同意”关闭 Finding。关闭需要：

- 新 Claim；
- 新 Evidence；
- 正确的定理条件；
- 修复后的 Candidate；
- 或 Verifier 判定 Finding 不成立。

### 12.7 阶段 G：Verifier Cross Exam

VerifierSkeptic 接收：

- Problem；
- Plan；
- 全部 active Candidate；
- Peer Review；
- Rebuttal；
- Evidence；
- Obligations；
- Conflict Graph。

Verifier 独立调用模型并发布 CritiqueArtifact：

- 对 Candidate 分别审查；
- 对 Peer Review 的正确性进行二次检查；
- 标记错误 Critique；
- 确定 local_repair、new_branch、replan、reject 或 continue_review；
- 记录未覆盖目标；
- 不产生 hard evidence。

### 12.8 阶段 H：Repair、New Branch 或 Replan

#### Local Repair

- Host 计算 Claim 影响闭包；
- 创建 RepairAgent；
- RepairAgent 独立调用模型；
- 发布 RepairPatch；
- 形成新 Candidate 版本；
- 确定性重新验证；
- 证据变差则回滚。

#### New Branch

核心方法错误时：

- 创建新的 Primary 或 Alternative Task；
- Router 可以先 Replan；
- Solver 独立调用模型；
- 发布新的 Candidate lineage；
- 新 Candidate 重新进入 Peer Review 和 Verifier。

#### Replan

RouterPlanner 收到：

- blocked subgoals；
- 已尝试方法；
- Conflict；
- Verifier Finding；
- open Obligations。

Router 再次独立调用模型并发布新 Plan 版本。新 Plan 不得删除已验证事实或原始条件。

### 12.9 阶段 I：Final Audit

当至少一个 Candidate 看似可提交时：

1. 创建新的 VerifierSkeptic final_audit 实例；
2. 输入最终 Candidate 版本、Evidence、Obligations、Peer Review、Rebuttal 和 Repair lineage；
3. 独立调用模型；
4. 发布 AuditArtifact；
5. 若 Audit 返回 incomplete/failed：
   - 在资源允许且有新行动时重新进入 Repair、New Branch 或 Replan；
   - 否则进入降级最终化。

### 12.10 阶段 J：确定性决策

Host 只在 Artifact 和 Evidence 基础上：

- 执行 hard evidence gate；
- 执行 proof completion policy；
- 执行词典序仲裁；
- 发布 DecisionArtifact；
- 使用 DeterministicFormatter；
- 投影公共 Trace；
- 释放所有 AgentState、Mailbox 和题内 Store。

---

## 13. 有硬上限的自适应长程推理机制

### 13.1 为什么六次上限不可用

即使每个角色只调用一次，强制 Router、LLM LemmaCurator、Primary、Alternative、双向 Peer Review、Verifier Cross Exam 和 Final Audit 已至少需要 8 次逻辑调用；这还没有计算 Solver 的多轮探索、作者回应、Repair、新分支或 Router Replan。因此，六次上限不是“偏紧”，而是与本方案要求的最小多 Agent 闭环在结构上矛盾。

### 13.2 Competition 初始调用策略

建议先以如下参数实施并实测：

    model_call_policy: adaptive_bounded
    max_logical_model_calls_per_problem: 48
    soft_call_checkpoints: [16, 28, 40]
    closure_reserve_calls: 8
    speculative_exploration_cutoff: 40

定义：

- 一次 Agent Turn 对注入的 `client.chat(...)` 发起一次调用，计为一次逻辑调用；
- 逻辑调用在实际派发给 `client.chat` 时计数，成功、模型错误或超时都消耗一次额度；
- `llm_client.py` 内部重试不重复计入题级逻辑调用，但必须由全局 RPM 的 `transport_attempt_reservation` 保守覆盖；
- 第 1 至第 40 次可用于探索和收敛；
- 第 41 至第 48 次为题级共享的收敛预留，只允许候选补全、Peer Review 回应、Verifier、Repair、必要 Replan、Final Audit 或 LLMFinalizer；
- 第 49 次逻辑调用不得派发；运行时必须使用已有 Artifact 做确定性收尾或按真实完成状态降级。

48 是待验证的 Competition 初始值，不是未经实验即可宣称最优的常数。它比旧值扩大 8 倍，能容纳完整闭环和多轮长程推理，同时在题目并发 3 时把三个题的理论题级总量限制为 144 次逻辑调用。

容量 sanity check（只用于解释数量级，不得实现为阶段配额）：完整结构至少占用 Router、Lemma、双 Solver、双向互审、Verifier Cross Exam 和 Final Audit 的 8 次；其余额度用于两个 Solver 的多轮探索、消息往返、Replan、候选回应、Repair/New Branch 和最终收敛。这样 48 次既不会把闭环压缩成 6 次，也不会把每个角色锁死在预设次数上。

### 13.3 必须移除的旧限制

Competition 路径必须移除或停用：

- `max_model_calls=6`；
- `CallAllocationPlan` 对 Router、Solver、Verifier、Repair 的固定次数切分；
- Agent/Stage 级 `remaining_calls` 和 `stage_remaining`；
- `LongHorizonPlan.planned_rounds`；
- `RoutePlan.max_reasoning_rounds` 的硬上限；
- 最多三轮 Primary 的 `for` 循环；
- 因六次预算而跳过 Router、Alternative、Repair 或 Verifier；
- `low_risk_primary_complete` 的 Candidate fan-out 短路。

保留且重建的是题级总硬上限，不是旧的六次分阶段预算。

### 13.4 SessionCallBudget 与 CallLedger

新增题内 `SessionCallBudget`：

    hard_limit = 48
    used_logical_calls
    remaining_logical_calls
    soft_checkpoints = [16, 28, 40]
    closure_reserve_calls = 8
    reserve_started
    exhausted

新增 `CallLedger`：

    call_id
    session_id
    agent_id
    task_id
    turn_id
    role
    mode
    action_category
    requested_at
    admitted_at
    completed_at
    logical_call_index
    transport_reservation
    transport_attempts_observed
    prompt_chars
    response_chars
    turn_kind
    requested_max_output_tokens
    effective_max_output_tokens
    stage_timeout_seconds
    effective_stage_timeout_seconds
    provider_elapsed_seconds
    finish_reason
    tail_state
    status
    failure_code

约束：

- `SessionCallBudget` 线程安全地执行题级硬上限；
- `CallLedger` 线程安全地记录调用事实；
- 不给单个 Agent 或固定阶段预切配额，避免 Router 提前猜错资源需求；
- 每个 Agent 都能看到标准化的 `budget_pressure`，但不能自行修改额度；
- 额度只属于当前 solve，结束后释放，不跨题累积或借用。

### 13.5 软检查点与收敛预留

软检查点不是自动停止点，而是强制进行一次确定性状态审计：

- 16 次：检查是否已有两个真正独立的 Candidate 尝试、是否存在重复探索；
- 28 次：检查开放 Obligation、冲突 Candidate、Peer Review 和 Evidence 缺口，要求 Agent 明确继续理由；
- 40 次：冻结新的投机性分支，进入 8 次收敛预留；
- 48 次：硬停止模型调用，确定性完成仲裁、格式化和 Trace 投影。

若某题在 16 或 28 次前已满足成功终止条件，应立即结束，不为“用满额度”继续调用。若 40 次时尚无合格 Candidate，预留额度优先用于产生最小可审计答案、验证和最终化，而不是继续横向扩展分支。

### 13.6 ResourceGovernor

每次 Agent 请求新 Turn 时，ResourceGovernor 按以下顺序判断：

1. 题级 `remaining_logical_calls > 0`；
2. 当前题目仍在 Deadline 内；
3. 若已进入第 41 至 48 次，Action 属于允许的收敛类别；
4. Agent 有未完成 Task，且请求与 active Plan 一致；
5. Action 产生新公开信息、处理真实消息或关闭义务；
6. Turn 类型对应的输出上限和阶段超时存在于已验证的 `StageExecutionPolicy`；
7. 题级剩余 Deadline 足以覆盖该阶段的最小执行窗口与确定性最终化预留；
8. 同一 Agent 没有尚未结束的 in-flight 或后台尾调用；
9. Provider Circuit 允许；
10. 全局模型并发和 200 RPM 允许；
11. 请求不会长期饿死其他 Case 或 Agent。

它不使用单 Agent 固定配额，不规定某阶段只能调用一次，也不把长程推理写死为三轮。

准入后应计算：

    effective_stage_timeout = min(
        configured_stage_timeout,
        remaining_problem_deadline - deterministic_finalization_reserve
    )

如果 `effective_stage_timeout` 小于该 Turn 类型的安全最小窗口，则不再派发这个长 Turn；Agent 必须改为紧凑收敛、发布已有 Candidate、abstain 或进入确定性最终化。排队等待不计入阶段执行超时，但计入题级 Deadline；阶段执行超时从真正进入 `client.chat` 时开始。

### 13.7 信息增益

一次 Turn 被认为有信息增益，如果至少发生：

- 新子目标；
- 新 Claim 或 Claim 依赖；
- 新 Lemma；
- 新 Candidate 或 Candidate 版本；
- 新 Evidence；
- 关闭一个 Obligation；
- 新 Critique 或 Rebuttal；
- 新有效 Message；
- 新 Plan；
- 明确 Abstain 或 Concede；
- Final Audit 状态改善。

仅改写措辞、重复 Artifact hash、重复同一 Message 不算进展。

### 13.8 无进展终止

达到 48 次不是唯一终止条件。以下情况也应提前终止：

- 相同 Agent 连续返回相同 Artifact hash；
- 同一对话 Thread 重复相同 Finding 和 Rebuttal；
- 没有 Claim、Evidence、Obligation 或 Candidate 状态变化；
- 所有 Agent 均 complete、abstain、failed 或 waiting without producer；
- Provider Circuit 打开且无可恢复路径；
- Deadline 或确定性 Finalization Reserve 到达。

短 stall 检测窗口用于提前止损；它不能替代题级 48 次硬上限，也不能因为单次低信息输出就过早杀死仍可恢复的长程推理。

### 13.9 Agent 自主继续

当 Agent 输出 `continue_reasoning`：

- Host 验证公开进展和题级剩余额度；
- 有进展且未触及上限时创建下一 Turn；
- 若 Agent 请求 Evidence、Lemma 或 Message，先等待对应结果再唤醒；
- Agent 可以在收到新消息后改变策略；
- Router 可以多次 Replan，Solver 可以多次继续，Verifier 可以请求继续审查未覆盖目标；
- Agent 在软检查点收到 `budget_pressure`，自主选择继续、收敛、发布 Candidate 或 abstain。

### 13.10 48 次上限的校准门

F8 必须比较 24、32、40、48 和 64 次离线回放或受控消融，报告准确率、证明完整率、调用命中上限率、P95 延迟和边际信息增益。只有在 48 次处仍有显著的“有进展但被硬停”且 64 次带来可重复净收益时，才提高正式上限；若 40 至 48 次长期没有边际收益，可以下调。无论最终校准值是多少，Competition 配置必须保留一个有限、显式、可测试的题级硬上限，绝不能静默回退到 6。

---

## 14. 并发 3、模型并发和 200 RPM

### 14.1 题目并发

正式有效题目并发必须为 3：

- user_agent.py 的 Case Gate 从配置读取 3；
- 冻结 main.py 外层虽然可能启动更多 Task，第四个 solve 在 ReasoningAgent 内等待；
- scripts/run_case_outputs.py 默认和最大均为 3；
- scripts/run_benchmark.py 默认和验证最大均为 3；
- Deadline 从真正获得 Case Gate 后开始。

### 14.2 模型并发

模型并发与题目并发不同。

由于每题存在 Router、多个 Solver、Lemma、Peer Review、Verifier 和 Repair，模型并发需要独立校准。

初始安全建议：

    model_max_concurrency = 6
    max_background_model_tails = 6

模型并发不是题级总量。Agent 在题级 48 次剩余额度内可以继续产生后续 Turn，并在全局模型队列中公平等待；排队本身不消耗题级调用额度。

最终值必须在 6、8、12、16 等候选中通过真实压力测试确定，不能直接用当前未验证的 16。

### 14.3 200 次/分钟

全局硬约束：

    任意滚动 60 秒窗口内，物理模型请求不超过 200。

正式 main.py 使用 InternChatClient 默认 retry=3。Provider 看不到内部每个 HTTP 尝试，因此 Competition 正式入口每个逻辑 client.chat 预留 3 个速率单位：

    66 个逻辑调用 x 3 = 198 个物理请求额度

第 67 个逻辑调用等待窗口释放。

自定义 Runner 明确设置 retry=1 时可以使用 reservation=1，但该值必须来自受审计入口配置，不能读取客户端私有字段。

容量关系必须在实现和测试中明确：三题同时跑满 48 次是最多 144 次逻辑调用；正式入口按每次逻辑调用保守预留 3 个物理请求额度，因此由 200 RPM 限制器分时派发，任意滚动 60 秒最多接受 66 次逻辑调用（198 个预留物理额度）。题级 48 次是“单题总量边界”，不是允许单题瞬时突破全局 200 RPM 的通行证。

### 14.4 公平调度

模型准入采用两级公平：

1. Case 级 round-robin；
2. 同一 Case 内 Agent 级 round-robin。

基本规则：

- 每个 Agent 同时最多一个 in-flight 模型调用；
- 一个长程 Solver 不能占满所有槽位；
- 三个 Case 都有 pending work 时轮转；
- Near-deadline final_audit、repair 和 answer formation 可以提高优先级；
- Optional duplicate exploration 优先级最低；
- RPM 等待和模型队列等待都计入 Deadline。

### 14.5 统一 ModelAdmissionController

准入必须原子判断：

    pending request
      -> case fairness
      -> agent fairness
      -> stage priority
      -> model concurrency capacity
      -> weighted rolling RPM
      -> Deadline
      -> provider circuit
      -> dispatch

规则：

- 未派发前取消不消耗 RPM；
- 已派发不退款；
- 后台尾调用继续占并发；
- 不使用 busy sleep；
- 使用 monotonic clock；
- fake clock 可测试；
- 记录 rate_wait 和 queue_wait。

### 14.6 分层 StageExecutionPolicy

以下是根据所给日志制定的 Competition 初始候选值，不是未经 canary 即永久冻结的常数：

| Turn 类型 | 默认 `max_tokens` | 初始阶段执行超时 | 说明 |
|---|---:|---:|---|
| Router / Replan | 2048–4096 | 90–120 秒 | 结构化规划，不要求输出完整解答 |
| Solver Progress | 4096 | 150–180 秒 | 公开增量、子目标、Claim 与下一动作 |
| Solver Candidate Standard | 8192 | 225–240 秒 | 标准答案合成；240 秒在旧日志中覆盖 98.2% 已完成调用 |
| Solver Candidate Proof | 12288 | 270 秒 | 完整证明专用；须先验证 Provider 确实支持该输出规模 |
| LemmaCurator | 4096–8192 | 180–225 秒 | 根据请求规模选择，不默认生成整份解答 |
| Peer Review / Verifier | 4096–6144 | 150–180 秒 | 聚焦 Claim、Finding 和义务，不复写完整 Candidate |
| Repair | 4096–8192 | 180–225 秒 | claim-local 修复；禁止全局重写 |
| LLMFinalizer | 2048–4096 | 90–120 秒 | 仅做必要合成；若关闭则由确定性 Formatter 完成 |

约束：

- 不再保留“所有角色统一 165 秒”的 Competition 路径；
- 上表是每类 Turn 的上界，不是保证占满的运行时间；模型正常 `stop` 后立即释放资源；
- 超时值以相同 Provider、相同并发、相同输出上限下的实测 P95 为基础，并保留约 10%–20% 抖动余量；
- Proof 12288/270 秒先走 canary；若 Provider 实际将输出硬截断在 8192，必须保持 8192 并依赖多轮 Progress + 紧凑 Proof 合成，不能仅修改本地配置自欺欺人；
- 16384 tokens / 300 秒只允许作为 F8 受控实验档，只有在证明完整率净提升、截断率与题级 P95 可接受且不挤压 Final Audit 时才能晋升；
- `finish_reason=length` 的响应即使 JSON 可解析，也只能进入 `partial` 或 `needs_compaction` 状态，不能直接标记完整 Candidate、通过证明完成门或触发最终提交。

### 14.7 超时后的后台尾调用治理

Provider 超时不代表底层 `client.chat` 已停止。为避免 165 秒窗口式失败演化为并发泄漏和重试风暴，必须：

- 将超时调用登记为 `background_tail`，继续占用模型并发和该 Agent 的单 in-flight 名额，直到真实返回或进入可审计的强制释放状态；
- 同一 Agent 在尾调用结束前不得立即重发相同 Prompt；Host 可以调度其他 Agent，但必须服从全局 `max_background_model_tails`；
- 迟到结果只进入 CallLedger 和诊断指标，若其对应 Task/Candidate 版本已冻结或被 supersede，不得静默写回活动状态；
- Tail 达到阈值时降低新探索优先级并触发 Provider Circuit，优先保留 Final Audit 和确定性最终化时间；
- 重试必须基于故障类别：`length` 采用紧凑输出/分段合成，阶段超时采用等待尾调用、缩短任务或改走已有 Artifact，禁止原样立即重试；
- solve 结束时记录未闭合尾调用数量，不把“返回了非空 fallback”误记为正常成功。

---

## 15. RouterPlanner 最终设计

### 15.1 每题首调用

Competition 中：

    enable_router = true
    router_execution = llm_required

RouterPlanner 必须是首个认知 Agent。ProblemParser 和 Schema 处理可以在它之前运行，但任何 Solver、Lemma 或 Verifier LLM 调用不得早于 Router。

### 15.2 Router 输出

RouteArtifact：

- primary_subject；
- auxiliary_subject；
- target_kind；
- response_mode；
- complexity and risk；
- selected skills；
- selected tools；
- representation candidates。
- budget profile（预计探索强度、软检查点理由和收敛风险）；

PlanArtifact：

- goals；
- subgoal DAG；
- dependency edges；
- method assignments；
- forbidden method overlaps；
- expected lemmas；
- validation targets；
- peer review questions；
- replan triggers；
- completion conditions。
- budget-sensitive stop conditions（何时转入 8 次收敛预留）；

### 15.3 Router 自主行为

Router 可以：

- 创建更多 Solver Task 提议；
- 合并重复子目标；
- 标记某方法不可行；
- 请求 LemmaCurator；
- 在收到 conflict 后 Replan；
- 在多个候选均失败后切换表示；
- 结束已无价值的分支。

Host 只验证：

- DAG 无环；
-角色合法；
-方法合法；
-不删除原始条件；
-不超过 Context 和 Deadline；
-Task 提议安全。

---

## 16. Solver 长程自治

### 16.1 公开 Working State

每个 Solver 拥有：

    ProblemFrame
    assigned goals
    active method
    public subgoal ledger
    public claim graph
    evidence refs
    lemma refs
    open obligations
    received messages
    attempted strategy summaries
    next action

不保存：

- 私有 CoT；
- 原始隐式草稿；
- 其他 Agent 未授权内容。

### 16.2 Solver 可以多次调用模型

典型长程过程：

1. explore；
2. 请求 Lemma；
3. 消费 Lemma 并 continue；
4. 请求 Tool Evidence；
5. 消费 Evidence 并 continue；
6. 发现方法冲突，request_replan；
7. 消费新 Plan；
8. publish_candidate；
9. peer_review 对方；
10. 回应对方 Critique；
11. 根据 Verifier 结果请求 Repair 或 New Branch；
12. complete 或 abstain。

这些 Turn 不按 Solver 或阶段预设固定份额；能否继续由题级 48 次硬上限、软检查点、进展门、Deadline 和全局资源共同决定。

### 16.3 Solver 独立性

首次 Candidate 发布前：

- Primary 和 Alternative 使用不同 AgentState；
- Context Snapshot 不包含对方 Candidate；
- Mailbox 不投递 candidate_published；
- Tool Evidence 只有在不泄露对方解答时才能共享；
- LemmaCurator 发布的公共 Lemma可以共享。

首次 Candidate 发布后：

- Candidate 公开给 Peer Review；
- 不公开私有推理；
- 作者和 Reviewer 使用不同 Task 和 Prompt mode。

### 16.4 Solver Token/Turn 策略

Solver 的长程推理能力来自“可持续的多轮状态推进”，而不是要求单次调用同时完成探索、验算、完整证明、结构化 JSON 和最终答案。正式路径按 Turn 类型拆分：

1. `explore` / `continue` 使用 4096-token Progress Turn，只输出新的公开步骤、Claim、依赖、失败方法摘要、未闭合义务、外部请求和下一 Action；
2. `synthesize_standard` 使用 8192-token Candidate Turn，消费已发布的 Progress、Lemma、Evidence 和 Plan，生成标准 CandidateArtifact；
3. `synthesize_proof` 使用 12288-token Candidate Turn，只在目标确实要求完整证明且 Provider canary 通过时启用；
4. `peer_review` 使用 4096–6144 tokens，只输出逐 Claim Finding、严重度、证据缺口和建议，不重复粘贴被审 Candidate；
5. `respond_to_review` / `local_repair` 使用 4096–8192 tokens，按 Finding 局部回应或修复。

为提高截断时的可恢复性，AgentTurnPayload 中的持久字段按以下顺序输出：

    action
    final_answer_or_status
    claims_and_dependencies
    open_obligations
    public_solution_steps
    outbound_intents
    progress_summary

Schema 仍保持严格，但不得在每个 Progress Turn 中要求重复整份 `solution_text`、全部历史 Claim、全部 Assumption 和全部 Theorem。历史通过 Artifact 引用和受控 Context Snapshot 读取。

若响应为 `finish_reason=length`：

- Parser 保留已验证的完整字段，但 Artifact 状态只能是 `partial`；
- Host 不原样重发同一超长 Prompt；
- 若缺的是 Candidate 序列化，可创建 `compact_synthesis` Turn，只提供已验证 Artifact 引用并要求最小完整 Contract；
- 若缺的是证明内容，先创建新的 Progress Turn 补齐指定 Obligation，再重新合成；
- 任何 `partial` Candidate 都不能通过 hard evidence gate、proof completion policy 或 final audit。

8192、12288 和 16384 是单次输出上限候选，不是每题总 Token 配额。单题总调用仍受 48 次硬上限、Deadline、并发与 200 RPM 约束；本方案不新增“每个 Solver 最多 N 次”的固定阶段配额。

---

## 17. LemmaCurator LLM Agent

### 17.1 从 Service 升级为 Agent

当前 deterministic LemmaCurator 可保留为 Schema 校验和 fallback 服务，但生产认知路径新增 LLM LemmaCurator。

LLM LemmaCurator：

- 独立 Agent ID；
- 独立 Prompt Contract；
- 独立模型调用；
- 独立 AgentState；
- 独立 Mailbox；
- 输出 LemmaArtifact。

### 17.2 能力

- 从 Plan 提取关键子引理；
- 检查定理使用前提；
- 建议必要定义；
- 识别边界、存在性、唯一性等证明义务；
- 响应 Solver 的 lemma_request；
- 对多个 Solver 的公共 Claim 提取可共享 Lemma；
- 发现 Lemma 冲突时通知 Router 和 Verifier。

### 17.3 安全边界

- proposed Lemma 不是事实；
- 未验证 Lemma 不得直接满足 Proof Obligation；
- Lemma 必须带 conditions、dependencies 和 target obligations；
- 引用 rejected Candidate 的 Lemma 必须失效或重新验证；
- LemmaCurator 不仲裁最终答案。

---

## 18. Solver 交叉审阅

### 18.1 双向 Peer Review

每题至少：

- Primary reviews Alternative；
- Alternative reviews Primary。

这是两个新的独立模型调用，不得由 Verifier 或 Host代替。

### 18.2 PeerReviewArtifact

    review_id
    reviewer_agent_id
    author_agent_id
    candidate_id
    candidate_version
    finding_items
    answer_assessment
    method_overlap_assessment
    missing_conditions
    counterexample_attempts
    unresolved_obligations
    recommended_action
    stop_reason

### 18.3 Review Finding

每个 Finding：

    finding_id
    candidate_id
    claim_id
    method_step_id
    obligation_ids
    status
    public_rationale
    missing_condition
    counterexample_summary
    severity

### 18.4 作者回应

作者必须通过新模型 Turn 生成 RebuttalArtifact：

    finding_id
    response
    action
    supporting_claim_ids
    evidence_refs
    requested_followup

交叉审阅不是自由辩论。没有新 Artifact 或 Evidence 的重复争论由 stall detector 关闭。

---

## 19. Verifier、Repair 与最终验证

### 19.1 Verifier Cross Exam

Verifier 独立于两个 Solver：

- 审查 Candidate；
- 审查 Peer Review 是否正确；
- 审查 Rebuttal 是否真正解决 Finding；
- 审查 Evidence 能力是否匹配；
- 审查 Proof Obligations；
- 建议 local repair、new branch、replan、reject 或 continue。

### 19.2 RepairAgent

RepairAgent：

- 只修授权 Claim 闭包；
- 读取 Critique 和相关 Rebuttal；
- 独立调用模型；
- 发布 CandidatePatch；
- Host 合并为新 Candidate 版本；
- 新版本确定性重新验证；
- Evidence 变差则回滚。

### 19.3 New Branch

核心方法失败不进入 Repair：

- Router Replan；
- 创建新 Solver Task；
- 独立模型调用；
- 新 Candidate 重新互审；
- 不把全局换路伪装成 Patch。

### 19.4 Final Audit

Final Audit 必须：

- 使用新的 VerifierSkeptic AgentInstance；
- 审查最终 Candidate 版本；
- 审查全部未关闭 Finding；
- 审查 Peer Review、Rebuttal 和 Repair lineage；
- 审查 required obligations；
- 输出 complete_hard、complete_audited、incomplete 或 failed；
- 不润色答案；
- 不自行修复。

如果仍有有效行动和时间，Audit 失败可以触发下一协作循环。

---

## 20. 验证证据层级

### 20.1 Hard Evidence

来源：

- 安全符号工具；
-数值残差；
-小规模枚举；
-矩阵形状；
-答案类型；
-经过能力匹配的确定性检查。

Hard fail 在仲裁前淘汰 Candidate。

### 20.2 Peer Review

- Solver 相互审阅；
- 属于 soft evidence；
- 能发现方法特有错误；
- 不能直接证明 Candidate 正确。

### 20.3 Verifier Review

- 独立 Verifier 的 Finding；
- 属于 soft evidence；
- 可以关闭 model-reviewable obligation；
- unknown 不能当 pass。

### 20.4 Completion

#### complete_hard

- 所有必要义务有能力匹配的 hard evidence；
- 无 hard fail；
- Final Audit 完整。

#### complete_audited

- 所有必要义务有真实 Claim；
- Peer Review、Rebuttal、Verifier 和 Final Audit 已覆盖；
- 无必要义务 fail 或 unknown；
- 不是形式化机器证明。

#### incomplete

- 存在未闭合必要义务；
- 存在未处理 Finding；
- 或 Audit unknown。

#### failed

- hard fail；
- 反例；
- 核心结论错误；
- 所有 Candidate 被拒绝。

---

## 21. 终止策略：题级硬上限与提前收敛并存

### 21.1 成功终止

满足：

- 至少一个 active Candidate；
- hard evidence gate 通过；
- required obligations 达到 response_mode 要求；
- Peer Review Thread 已关闭；
- Verifier Finding 已处理或明确 unresolved；
- Final Audit 完成；
- Deterministic Arbitration 可选出 Candidate。

### 21.2 收敛终止

- 所有 Agent complete、abstain 或 failed；
- 所有 Conversation Thread closed；
- 没有 pending Evidence、Message 或 Task；
- 连续协作周期没有 Artifact、Evidence、Obligation 或 Candidate 状态变化。

### 21.3 资源终止

- 题级 48 次逻辑调用硬上限到达；
- Hard Deadline；
- Deterministic Finalization Reserve；
- Provider Circuit 持续打开；
- Rate Limit 等待已无时间形成有效响应；
- Context 无法安全压缩。

### 21.4 协议终止

- 重复 Artifact hash；
- 循环引用；
- Agent 持续输出非法 Action；
- 跨 Session 引用；
- 未授权 Artifact 访问；
- 重复无增量 Message。

### 21.5 数字上限的边界

使用：

- 每题最多 48 次逻辑调用；
- 第 40 次后进入 8 次收敛预留；
- 第 49 次拒绝派发并进入确定性收尾。

不使用：

- 每个 Agent 各自最多 N 次的刚性切分；
- 每个阶段最多 N 次的预分配；
- 最多 N 轮推理的固定流程。

因此，实际调用总数通常由成功收敛、无进展、Deadline 和 Agent 决策在 48 次之前决定；48 只作为最后的题级安全边界。

---

## 22. Context、Memory、Checkpoint 与隐私

### 22.1 题内持久状态

在一个 solve 内持久：

- AgentState；
- Task；
- Message；
- Artifact；
- Conversation Thread；
- CandidatePool；
- Evidence；
- Obligations；
- CallLedger。

### 22.2 跨题状态

不持久：

- AgentState；
- Mailbox；
- Candidate；
- Rebuttal；
-私有对话；
-动态写入知识。

长期知识库在评测中只读。

### 22.3 Checkpoint

每个关键 Artifact 发布后可生成题内 Checkpoint：

- active Plan；
- Agent 生命周期；
- open Tasks；
- Candidate IDs；
- Evidence refs；
- open obligations；
- open conversations；
- Deadline 摘要。

Checkpoint 用于题内恢复、降级和 Debug，不用于跨题学习。

### 22.4 私有推理

系统只保存：

- 公开数学步骤；
- 公开 Claim；
- 公开状态增量；
- 公开 Critique；
- 公开 Rebuttal；
- 简短 progress summary。

不保存或传输私有 Chain-of-Thought。

---

## 23. Prompt Contract 最终改造

### 23.1 通用字段

所有认知 Agent Contract 新增：

    protocol_version
    allowed_modes
    accepted_task_types
    accepted_message_types
    readable_artifact_types
    writable_artifact_types
    allowed_actions
    output_turn_schema
    abstain_policy
    progress_policy
    communication_policy

### 23.2 通用输出

每次模型调用输出 AgentTurnPayload，而不是无控制语义的自由 JSON：

    action
    public_state_delta
    result_payload
    outbound_intents
    progress_summary
    stop_reason

Candidate、Finding、Lemma、Rebuttal、Repair 仍复用现有严格 payload Schema。

### 23.3 RouterPlanner

从 classify and budget a problem 升级为：

> route, decompose, assign independent strategies, define validation targets, and revise the plan after public feedback.

Competition 中不再 inactive 或 optional。

### 23.4 PrimarySolver

支持模式：

- explore；
- continue；
- synthesize；
- peer_review；
- respond_to_review；
- new_branch。

### 23.5 AlternativeSolver

支持相同模式，但继续执行 Primary Candidate 首次发布前隔离。

新增独立性字段：

- representation；
- core_invariant；
- proof_direction；
- distinguishing_steps。

### 23.6 LemmaCurator

删除 inactive_review_template 的生产语义。

支持：

- initial_curate；
- answer_lemma_request；
- reconcile_lemmas；
- review_lemma_conditions。

### 23.7 VerifierSkeptic

模式：

- cross_exam；
- review_peer_findings；
- final_audit；
- continue_uncovered_targets。

### 23.8 RepairAgent

支持：

- local_repair；
- abstain_no_safe_patch。

禁止：

- global rewrite；
- unrelated Claim 修改；
- 无 Finding 引用的修复。

### 23.9 输出预算与截断 Contract

每个 Prompt 编译结果必须携带并可审计：

    turn_kind
    max_output_tokens
    stage_timeout_seconds
    required_fields_priority
    length_recovery_mode

`prompt_compiler.py` 不得再把 Primary/Alternative 的 minimal、standard、tool、proof 和 progress 全部压成同一个 8192 上限。配置层是允许上界，Contract/Turn 类型选择本次额度；两者不一致时取更安全的已验证值并在 CallLedger 记录，不能静默声称已启用更大上限。

Prompt 必须要求紧凑、引用已有 Artifact、先输出不可丢失字段，并禁止为了“看起来完整”重复上下文。`finish_reason=length`、缺少优先字段或 JSON 尾部截断时，Turn 状态必须为 partial/invalid_contract，由确定性恢复策略决定 compact synthesis、补充 Progress、降级或停止。

---

## 24. 配置最终设计

Competition 配置需要升级 Schema。

建议核心字段：

    schema_version: 2.0
    profile: competition
    status: candidate-unvalidated

    case_max_concurrency: 3
    model_max_concurrency: 6
    model_requests_per_minute: 200
    rate_limit_window_seconds: 60.0
    transport_attempt_reservation: 3
    max_background_model_tails: 6
    max_inflight_calls_per_agent: 1
    deterministic_finalization_reserve_seconds: 60

    stage_execution_policy:
      router: {max_tokens: 4096, timeout_seconds: 120}
      replan: {max_tokens: 4096, timeout_seconds: 120}
      solver_progress: {max_tokens: 4096, timeout_seconds: 180}
      solver_candidate_standard: {max_tokens: 8192, timeout_seconds: 240}
      solver_candidate_proof: {max_tokens: 12288, timeout_seconds: 270}
      lemma_curator: {max_tokens: 8192, timeout_seconds: 225}
      peer_review: {max_tokens: 6144, timeout_seconds: 180}
      verifier: {max_tokens: 6144, timeout_seconds: 180}
      repair: {max_tokens: 8192, timeout_seconds: 225}
      finalizer: {max_tokens: 4096, timeout_seconds: 120}

    finish_reason_length_policy: partial_needs_compaction
    timeout_retry_policy: wait_tail_or_replan
    experimental_proof_max_tokens: 16384
    experimental_proof_timeout_seconds: 300

    model_call_policy: adaptive_bounded
    max_logical_model_calls_per_problem: 48
    soft_call_checkpoints: [16, 28, 40]
    speculative_exploration_cutoff: 40
    closure_reserve_calls: 8
    enable_router: true
    router_llm_required: true
    minimum_solver_agents: 2
    enable_llm_lemma_curator: true
    enable_peer_cross_review: true
    enable_agent_rebuttal: true
    enable_verifier: true
    enable_repair: true
    enable_final_audit: true
    enable_agent_mailbox: true
    enable_artifact_store: true

    enable_finalizer: false
    enable_rag: false

迁移期如果必须保留旧字段，则设置 `max_model_calls: 48`，并要求它与 `max_logical_model_calls_per_problem` 相等；两者冲突时配置加载必须失败，不能静默选取，也绝不能回退为 6。Schema 稳定后删除旧字段，只保留语义明确的新字段。

现有 `primary_max_tokens`、`alternative_max_tokens` 等扁平字段在迁移期只能作为角色级 Provider 安全上界，不能继续决定所有 Solver Turn 的实际输出值。实际值必须由 `stage_execution_policy` 的具体 `turn_kind` 选择；如果角色上界低于对应 Turn 值，配置加载或 canary 必须明确报出降级原因，CallLedger 记录 `requested` 与 `effective` 两个值，禁止配置写着 12288、实际仍静默使用 8192。

上述阶段值的初始状态均为 `candidate-unvalidated`。F8 必须在真实 Provider 上验证输出上限是否生效，并按同一角色、同一 Turn 类型的 P95 与 10%–20% 余量校准；不得用 Router 的延迟分布校准 Proof，也不得用单题串行数据替代三题并发压力数据。

保留 Deadline、Context、Trace、Tool、Evidence 等现有配置。题级 Deadline 必须足以容纳实际并发调度，但任何单阶段超时都不能覆盖或延长题级 Deadline。

---

## 25. 代码改造范围

### 25.1 永不修改

- main.py；
- llm_client.py。

### 25.2 新增 Agent Runtime

    mathforge/agent_runtime/__init__.py
    mathforge/agent_runtime/protocol.py
    mathforge/agent_runtime/instance.py
    mathforge/agent_runtime/actions.py
    mathforge/agent_runtime/task_scheduler.py
    mathforge/agent_runtime/mailbox.py
    mathforge/agent_runtime/conversations.py
    mathforge/agent_runtime/artifact_store.py
    mathforge/agent_runtime/candidate_pool.py
    mathforge/agent_runtime/coordinator.py
    mathforge/agent_runtime/resource_governor.py
    mathforge/agent_runtime/session_call_budget.py
    mathforge/agent_runtime/call_ledger.py

### 25.3 配置与资源治理

修改：

    user_agent.py
    mathforge/config.py
    config/competition.json
    mathforge/harness/provider.py
    mathforge/harness/model_policy.py
    mathforge/harness/priority_scheduler.py
    mathforge/harness/deadline.py

重构或兼容迁移：

    mathforge/harness/allocation.py
    mathforge/harness/budget.py

最终目标：

- 旧 `CallBudget(max_calls=6)` 迁移为题级 `SessionCallBudget(hard_limit=48)`；
- CallAllocationPlan 不再预分配阶段次数；
- ResourceGovernor 在题级剩余额度内负责动态准入和收敛预留；
- StageExecutionPolicy 负责按 Turn 类型选择 `max_tokens` 和阶段执行超时，并由剩余 Deadline 裁剪；
- Provider 对 background tail、迟到结果与故障分类有显式生命周期；
- CallLedger 负责记录，SessionCallBudget 负责硬拒绝第 49 次调用。

### 25.4 Runtime

修改：

    mathforge/runtime.py
    mathforge/harness/session.py
    mathforge/harness/schemas.py
    mathforge/harness/stages.py
    mathforge/harness/state.py
    mathforge/harness/reasoning_state.py
    mathforge/harness/adaptive_fanout.py
    mathforge/harness/orchestration.py

关键变化：

- MathForgeHarness 退化为 facade；
- SessionAgentRuntime 驱动事件循环；
- 删除固定 planned_rounds；
- 删除 low-risk fan-out short circuit；
- Candidate 至少两个；
- 所有角色调用通过 Task 和 AgentInstance；
- runtime.py 不再直接按固定顺序拼接所有 Prompt。

### 25.5 Agent

修改：

    mathforge/agents/router_planner.py
    mathforge/agents/solver.py
    mathforge/agents/lemma_curator.py
    mathforge/agents/verifier.py
    mathforge/agents/repair.py
    mathforge/agents/finalizer.py
    mathforge/agents/prompt_compiler.py
    mathforge/agents/registry.py
    mathforge/agents/skill_selector.py

建议新增：

    mathforge/agents/turn_parser.py
    mathforge/agents/peer_review.py
    mathforge/agents/rebuttal.py

### 25.6 验证

修改：

    mathforge/verification/cross_review.py
    mathforge/verification/methods.py
    mathforge/verification/completion.py
    mathforge/verification/arbitration.py
    mathforge/verification/repair_scope.py
    mathforge/harness/repair.py

新增：

    mathforge/verification/conflict_graph.py
    mathforge/verification/peer_review_policy.py
    mathforge/verification/audit_policy.py
    mathforge/verification/rebuttal_policy.py

### 25.7 Context、Memory、Trace

修改：

    mathforge/context/role_views.py
    mathforge/context/snapshots.py
    mathforge/context/compressor.py
    mathforge/memory/blackboard.py
    mathforge/memory/policies.py
    mathforge/output/judge_trace.py
    mathforge/output/loop_health.py

### 25.8 Prompt

修改全部固定角色 Contract：

    prompts/router_planner/contract.md
    prompts/primary_solver/contract.md
    prompts/alternative_solver/contract.md
    prompts/lemma_curator/contract.md
    prompts/verifier_skeptic/contract.md
    prompts/repair/contract.md
    prompts/finalizer/contract.md

### 25.9 Runner 与文档

    scripts/run_case_outputs.py
    scripts/run_benchmark.py
    scripts/propose_competition_config.py
    README.md
    docs/CONFIGURATION_SOURCES.md
    CHANGELOG.md

---

## 26. 实施阶段总览

实施按阶段提交，每个阶段一份 Commit、测试和 CHANGELOG。

    F0  Baseline and governance
    F1  Case concurrency, 200 RPM, stage execution policy, ResourceGovernor and CallLedger
    F2  Protocol, ArtifactStore, Mailbox and Agent lifecycle
    F3  Mandatory Router and dynamic Plan
    F4  Autonomous long-horizon Solver, typed Token/Turn contracts and LLM LemmaCurator
    F5  CandidatePool, peer cross-review and rebuttal
    F6  Verifier, Repair/New Branch and Final Audit
    F7  Proof semantics, runtime decomposition, trace and compatibility cleanup
    F8  Concurrency stress, live evaluation, ablation and configuration freeze

---

## 27. Phase F0：基线与治理

### 目标

- 固化最终方案；
- 解决审查前已删除的 tests/test_phase0_0730_baseline.py；
- 记录当前提交、配置、Prompt、Skill、数据和模型 identity；
- 定义真正多 Agent DoD；
- 将上一版六调用方案标记为 superseded；
- 明确固定角色都使用独立模型调用；
- 明确 Competition 的初始题级硬上限为 48，而不是 6；
- 固化上一版测评日志中的请求数、完成数、length、耗时、invalid 与 RPM 统计，并记录日志提交与当前基线不一致的限制；
- 将“分层阶段超时 + Progress/Candidate 分类型 Token”登记为待 F1/F4/F8 验证的正式候选，不提前标记 validated。

### 代码变化

- 不改变运行行为；
- 只更新治理文档、ADR、测试基线和 CHANGELOG。

### 测试

- 干净 HEAD 完整 pytest；
- verify_baseline_files.py；
- AST/compileall；
- Config、Prompt 和 Skill manifest；
- baseline registry。
- 日志统计脚本或等价可复核查询，结果与 3.2 节一致。

### 验收

- 工作树状态清晰；
- 基线可复现；
- 没有把旧 6-call 报告当成最终架构；
- 没有把旧日志的强相关关系误写成逐题因果证明，也没有忽略其对 165 秒/8192 策略的否定证据。

---

## 28. Phase F1：资源治理与重建题级 Call Budget

### 目标

- 题目并发改为 3；
- 增加 200 RPM；
- 增加 weighted transport reservation；
- 新增 ResourceGovernor；
- 新增 SessionCallBudget；
- 新增 CallLedger；
- Competition 将旧六次限制替换为 48 次题级逻辑调用硬上限；
- 增加 16/28/40 软检查点和 8 次收敛预留；
- 将统一 165 秒改为按 Turn 类型分层的阶段执行超时；
- 增加 background tail 生命周期和同 Agent 单 in-flight 约束；
- 保留 Deadline 和模型并发。

### 实施步骤

1. 配置 Schema 支持 `adaptive_bounded`、48 次硬上限、软检查点和收敛预留；
2. user_agent 从配置读取 case_max_concurrency=3；
3. Runner 默认/最大并发改为 3；
4. Provider 使用统一 ModelAdmissionController；
5. 旧 CallBudget 迁移为题级 SessionCallBudget；
6. 新运行路径不调用 CallAllocationPlan；
7. ResourceGovernor 根据探索/收敛 Action 类别执行 40 次边界；
8. CallLedger 记录调用，SessionCallBudget 原子计数；
9. 增加 StageExecutionPolicy，按 Turn 类型选择输出上限、阶段执行超时及安全最小窗口；
10. 阶段超时由题级剩余 Deadline 和确定性最终化预留裁剪；
11. Provider 登记 background tail，禁止同 Agent 原样立即重试和迟到结果静默写回；
12. Trace 输出 `calls_used`、`calls_remaining`、`budget_phase`、`turn_kind`、`finish_reason`、`requested/effective_max_output_tokens`、`stage/effective_stage_timeout_seconds`、`tail_state` 和 `stop_reason`。

### 核心测试

- 三个 solve 同时进入，第四个等待；
- Deadline 从 Case Gate 后开始；
- weight=3 时 66 个逻辑调用可派发，第 67 个等待；
- weight=1 时第 201 个等待；
- RPM 窗口滚动正确；
- 未派发取消不消耗额度；
- Agent 多次调用超过旧 6 次仍可继续；
- 12 次、20 次有信息增量的 Fake Agent Turn 不因旧阈值失败；
- 第 40 次后新投机分支被拒绝，Verifier/Repair/Final Audit 仍可使用预留；
- 第 48 次可派发，第 49 次不得进入 client.chat；
- 题级计数在并发 Agent 请求下原子且不超过 48；
- 8192-token Candidate 在 200 秒正常返回时不会再被固定 165 秒提前判死；
- Router 超过其独立 120 秒策略时正确超时，不能继承 Candidate 的 240 秒；
- 队列等待只计入题级 Deadline，不提前消耗阶段执行超时；
- 剩余 Deadline 不足时不派发 270 秒 Proof Turn，并保留确定性最终化时间；
- 阶段超时后同一 Agent 不会立即重复派发，后台尾调用继续占用并发并可被回收；
- 迟到结果不能覆盖已冻结或 superseded 的 Candidate 版本；
- Deadline 到达仍会终止；
- Provider Circuit 仍有效。

### 验收

- Competition 不会在第 6 次错误终止；
- 每题逻辑调用不超过 48，且触顶后仍返回真实、可序列化结果；
- 不存在把缺失配置静默回退为 6 的路径；
- 不突破 200 RPM；
- 不突破题目并发 3；
- Competition 中不存在所有阶段统一 165 秒的路径；
- 后台尾调用不泄漏、不突破并发，也不触发重试风暴；
- 无无限 busy loop。

---

## 29. Phase F2：协议、Artifact、Mailbox 与 Agent 生命周期

### 目标

- AgentDefinition；
- AgentInstance；
- AgentState；
- AgentTask；
- AgentTurnPayload；
- MessageEnvelope；
- Conversation Thread；
- ArtifactEnvelope；
- SessionArtifactStore；
- Call 与 Message lineage。

### 迁移策略

先运行 Shadow Protocol：

- 旧流程继续产生结果；
- 每个阶段同步生成 Shadow Artifact；
- 比较旧 Trace 和新事件；
- 不立即改变 Candidate 选择。

稳定后切换 Authoritative Protocol：

- 阶段间只传 artifact_id；
- 从 Store 重建 payload；
- 旧 Blackboard 降级为兼容层。

### 测试

- Artifact 不可变；
- hash 稳定；
- parent 存在；
- 跨 Session 引用拒绝；
- Agent 只能读写授权类型；
- Message 去重；
- reply_to 合法；
- Conversation 可关闭；
- Agent 状态机合法；
- solve 后清空全部题内状态；
- 三题并发无交叉。

### 验收

- 每次模型调用有 agent_id、task_id、turn_id；
- 每个 Agent 输出有 Artifact；
- 每个通信有 Message；
- Trace 可重建因果链。

---

## 30. Phase F3：强制 RouterPlanner 与动态 Plan

### 目标

- 每题第一认知调用是 RouterPlanner；
- Router 独立调用模型；
- RouteArtifact；
- PlanArtifact；
- 子目标 DAG；
- Agent Task 提议；
- Replan。

### 删除

- Competition enable_router=false；
- 跳过 Router 的正常路径；
- 仅依赖 RouterRuleEngine 的生产路由；
- low-risk route shortcut。

### 保留

- RouterRuleEngine 作为 Router Agent 失败后的确定性 fallback；
- Schema 校验；
- Context ACL；
- Prompt Contract。

### 测试

- 任何 Solver call 之前必有 Router call；
- Router call 与 Solver call 的 agent_id 不同；
- Router Plan 实际改变 Solver Task；
- DAG 循环被拒绝；
- 非法方法被拒绝；
- Router blocked 后可再次调用；
- Replan 产生新 Plan 版本；
- 新 Plan 保留原始条件和已验证事实；
- Router failure fallback 可用且 Trace 真实。

### 验收

- 每题都真实经过 Router Agent；
- Planner 不再只是标签生成器；
- Plan 对后续调用有因果影响。

---

## 31. Phase F4：自主长程 Solver 与 LLM LemmaCurator

### 目标

- Primary 多轮自主 Turn；
- Alternative 多轮自主 Turn；
- 首次 Candidate 前隔离；
- LemmaCurator 独立 LLM Agent；
- Agent Action；
- Lemma、Tool、Replan 消息；
- 无 fixed planned_rounds。
- Solver 使用多轮短 Progress + 分类型 Candidate 合成，不再全模式统一 8192。

### 实施步骤

1. AgentTurnPayload parser；
2. Solver 输出 action；
3. ResourceGovernor 根据进展创建下一 Turn；
4. ProgressArtifact 替代固定 ReasoningState for-loop；
5. LemmaCurator Contract 激活；
6. Lemma request/reply Thread；
7. Solver Tool Request 通过 Host；
8. Stall detector；
9. Candidate publication；
10. PromptCompiler 按 Turn 类型选择 4096/8192/12288 输出上限；
11. `finish_reason=length` 进入 partial/compact-synthesis 恢复路径；
12. Proof 12288/270 秒先做 Provider canary，16384/300 秒只保留实验开关。

### 测试

- Solver 连续产生 10 个有信息增量 Turn，且题级额度仍充足时系统持续运行；
- 无 max_reasoning_rounds 拒绝；
- continue_reasoning 形成新 Turn；
- 相同 hash 重复停止；
- LemmaCurator 每题至少一次独立调用；
- Solver request_lemma 唤醒 LemmaCurator；
- Lemma 消息唤醒 Solver；
- 未验证 Lemma 不满足义务；
- Primary canary 不进入 Alternative Prompt；
- Alternative 失败不污染 Primary；
- 两个 Solver 均可 abstain；
- Progress Turn 不重复要求完整 solution_text，且输出上限为 4096；
- 标准 Candidate 为 8192，完整证明 Candidate 为 12288，两者 Prompt Contract 可区分；
- `finish_reason=length` 的可解析 JSON 仍不能被标记为完整 Candidate；
- compact_synthesis 只消费已验证 Artifact，不原样重发超长上下文；
- Provider 不支持 12288 时自动保持 8192 + 多轮 Progress，且 Trace 明确记录降级。

### 验收

- 长程推理由 Agent 在题级剩余额度内决定继续；
- Host 不预设轮数；
- LemmaCurator 是真实 LLM Agent；
- 每题至少两个 Candidate 尝试；
- 单次 Token 上限不再被误当成整题推理上限；
- 长证明的完整率提升不能以显著增加 invalid、截断或挤掉 Final Audit 为代价。

---

## 32. Phase F5：候选池、交叉审阅与 Rebuttal

### 目标

- CandidatePool；
- 至少两个独立 Candidate；
- 结构独立性门；
- Primary reviews Alternative；
- Alternative reviews Primary；
- PeerReviewArtifact；
- RebuttalArtifact；
- 显式 Review Thread。

### 实施步骤

1. Candidate 状态机；
2. Method Signature 增加 representation/invariant/direction；
3. Candidate 发布后解除隔离；
4. 创建两个 peer_review Task；
5. Peer Reviewer 独立调用模型；
6. 向 Candidate 作者发送 Review；
7. 作者独立调用模型回应；
8. Thread close/reopen 规则；
9. Conflict Graph 吸收 Peer Review。

### 测试

- 两个 Candidate 都有不同 author_agent_id；
- 两个 Candidate 都来自独立模型调用；
- Review A-by-B 和 B-by-A 都存在；
- Peer Review 不由 Host 生成；
- Review 引用真实 Claim；
- 作者收到 Message；
- Rebuttal 引用 Finding；
- 无新内容的循环争论停止；
- 实质重复 Candidate 不计作独立候选；
- Candidate Concede 后状态更新。

### 验收

- 每题都有双向 Solver 交叉审阅；
- 通信对后续 Candidate/Verifier 有实际影响；
- 候选独立性可测量。

---

## 33. Phase F6：Verifier、Repair/New Branch 与 Final Audit

### 目标

- Verifier cross_exam；
- Peer Review 二次审查；
- CritiqueArtifact；
- RepairAgent；
- New Branch；
- Replan；
- Final Audit；
- 多轮验证闭环。

### 实施步骤

1. Verifier 输入 CandidatePool、Review、Rebuttal、Evidence；
2. cross_exam Agent Turn；
3. actionability classification；
4. local repair Task；
5. new branch Task；
6. Router replan Task；
7. repair re-verification；
8. new Candidate 回到 Peer Review；
9. final_audit Agent；
10. Audit 失败可重新进入闭环；
11. DecisionArtifact。

### 测试

- Verifier 是独立调用；
- Verifier 检查 Peer Review；
- 错误 Peer Review 可被驳回；
- Repair 引用真实 Critique；
- RepairAgent 独立调用模型；
- Repair 不越权；
- Evidence 下降回滚；
- 核心方法错误进入 New Branch；
- New Branch 有新 author/task/call；
- Final Audit 使用新 Verifier 实例；
- Final Audit 只看最终 Candidate；
- Audit incomplete 可触发下一循环；
- Deadline 到达安全降级。

### 验收

- Candidate、Peer Review、Rebuttal、Verifier、Repair 和 Audit 因果闭合；
- 未审查 Repair 不会提交；
- 全局错误不伪装成局部 Patch。

---

## 34. Phase F7：Proof、Runtime、Trace 与兼容清理

### 目标

- complete_hard/complete_audited/incomplete/failed；
- runtime.py 拆分；
- 旧 CallAllocation 删除；
- 旧固定轮次删除；
- 旧 Blackboard 写路径删除；
- Trace 从 Agent 事件投影；
- Formal entry 兼容。

### Runtime 拆分

建议：

    mathforge/runtime.py              facade
    mathforge/runtime/session_flow.py session lifecycle
    mathforge/runtime/agent_flow.py   agent event loop
    mathforge/runtime/review_flow.py  peer and verifier loops
    mathforge/runtime/final_flow.py   audit, decision, formatting

### Proof 测试

- proof_full 缺失步骤不能 complete；
- Peer Review 全 pass 但 Audit unknown 仍 incomplete；
- hard fail 一定 failed；
- complete_audited 必须覆盖所有必要义务；
- repaired proof 必须 Final Audit；
- best available 非空但 Trace degraded；
- frozen main status 限制有明确 Trace 字段。

### Trace 测试

- agent_created；
- task_assigned；
- model_turn_started/completed；
- message_sent/delivered；
- artifact_published；
- peer_review_completed；
- rebuttal_completed；
- verifier_completed；
- repair committed/rolled_back；
- final_audit_completed；
- decision_committed；
- agent_stopped。

### 验收

- runtime.py 不再是唯一流程巨函数；
- 没有剩余六次上限或按阶段切死次数的 Competition 路径；
- 只保留统一的题级 48 次硬上限和收敛预留；
- Trace 无私有 CoT、绝对路径或原始异常；
- Public contract 保持非空 final_response 和 list trace。

---

## 35. Phase F8：真实测试、消融与冻结

### 目标

- 并发 3；
- 200 RPM；
- 全 Agent 长程协作；
- 88 题完整运行；
- 多次配对实验；
- 更新 Evidence Registry；
- 配置达到门禁后才 validated。

### 新消融组

| 组 | 能力 |
|---|---|
| C0 | Mandatory Router + Primary + Alternative |
| C1 | C0 + LLM LemmaCurator |
| C2 | C1 + Solver Peer Review |
| C3 | C2 + Rebuttal |
| C4 | C3 + Verifier Cross Exam |
| C5 | C4 + Repair/New Branch |
| C6 | C5 + Final Audit |
| C7 | C6 + fully autonomous bounded long-horizon loop |

在 C0–C7 架构消融之外，增加正交的超时/Token 策略矩阵：

| 组 | 超时与输出策略 | 用途 |
|---|---|---|
| T0 | 所有主要阶段 165 秒、Solver 全模式 8192 | 仅作为旧行为对照，不得冻结为正式配置 |
| T1 | 分层超时、Solver 全模式 8192 | 单独测量超时策略收益 |
| T2 | 分层超时、Progress 4096 + Standard Candidate 8192 | 推荐基础候选 |
| T3 | T2 + Proof Candidate 12288/270 秒 | 验证完整证明收益与 Provider 能力 |
| T4 | T2 + Proof Candidate 16384/300 秒 | 只做受控 canary，不默认进入 Competition |

所有组都：

- 每题先 Router；
- 至少两个 Solver；
- 每题使用相同的 48 次逻辑调用硬上限和软检查点；
- 题目并发 3；
- 全局 200 RPM；
- 相同 Deadline；
- 失败题进入分母。

### 指标

正确性：

- 全题准确率；
- 输出覆盖率；
- proof 完整率；
- 人工审查通过率。

Agent 自主性：

- continue_reasoning 率；
- Agent 自主 request_lemma/tool/replan/review 率；
- Agent abstain 率；
- 有效信息增量/Turn；
- 无进展终止率。

通信：

- Message 数；
- 有效 Message 比例；
- Message 触发 Task 比例；
- Peer Review 覆盖率；
- Rebuttal 关闭 Finding 比例；
- Thread 循环率。

候选：

- 平均 Candidate 数；
- 独立 Candidate 比例；
- 错误相关系数；
- New Branch 成功率；
- Candidate supersede 率。

验证：

- Peer Review precision/recall；
- Verifier precision/recall；
- Repair 净修复率；
- Repair 修坏率；
- Final Audit 拦截率；
- Final Audit 误杀率。

资源：

- 每题逻辑调用分布和 48 次上限命中率；
- Agent 各自调用分布；
- P50/P95/最大调用次数；
- 16/28/40 软检查点后的边际信息增益；
- 收敛预留使用率和第 49 次拒绝计数；
- P50/P95/最大耗时；
- 按 Turn 类型统计 P50/P95/最大 Provider 执行耗时；
- `finish_reason=stop/length/other` 分布，特别报告 Candidate 和 Proof 的 length 率；
- 分阶段 timeout 率、late-success 率和未配对调用率；
- 请求 Token 上限、实际响应长度和 Token 档位利用率；
- RPM wait；
-模型队列 wait；
- Provider failure；
- Deadline termination；
- Background tails 峰值、存续时间、结束时未闭合数和同 Agent 重试阻断次数；
- deterministic fallback 使用率及其最终被判 invalid/incorrect/correct 的分布。

### 冻结门

- 100% 输入有合法输出；
- 活跃题目不超过 3；
- 任意 60 秒物理请求不超过 200；
- 每题首个认知调用是 Router；
- 每题 Core Agent 都有独立模型调用；
- 每题至少两个独立 Candidate；
- 每题有双向 Solver Peer Review；
- Verifier Cross Exam 和 Final Audit 均存在；
- 无跨题状态泄漏；
- 无未审查 Repair；
- 每题逻辑调用不超过已冻结的有限上限，初始候选值为 48；
- 第 41 至 48 次只用于收敛类别，第 49 次不派发；
- Competition 不使用跨角色统一 165 秒；每个 Turn 类型都有经过三题并发 canary 的 P95 校准证据；
- 关键收敛调用的 `finish_reason=length` 率低于 5%，非故障注入场景的阶段 timeout 率低于 2%；
- solve 释放时不存在未登记的后台尾调用，且尾调用不会突破并发或触发同 Agent 重试风暴；
- Proof 12288 只有在 Provider 确认支持且相对 T2 带来可重复的证明完整率净收益时启用；16384 默认关闭；
- deterministic fallback 率低于 5%，并在冻结前以低于 2% 为目标；fallback 必须单独标记，不能计入正常成功；
- 当前提交有 active baseline；
- 新多 Agent 组件有可重复收益或明确可靠性收益。

---

## 36. 测试文件规划

建议新增：

    tests/test_agent_protocol.py
    tests/test_agent_actions.py
    tests/test_agent_artifact_store.py
    tests/test_agent_mailbox.py
    tests/test_agent_conversations.py
    tests/test_agent_lifecycle.py
    tests/test_agent_resource_governor.py
    tests/test_model_rate_limit.py
    tests/test_stage_execution_policy.py
    tests/test_provider_tail_lifecycle.py
    tests/test_solver_output_budget.py
    tests/test_length_recovery.py
    tests/test_adaptive_call_budget.py
    tests/test_mandatory_router.py
    tests/test_llm_lemma_curator.py
    tests/test_solver_independence.py
    tests/test_candidate_pool.py
    tests/test_solver_peer_review.py
    tests/test_agent_rebuttal.py
    tests/test_verifier_cross_exam.py
    tests/test_repair_new_branch.py
    tests/test_final_audit.py
    tests/test_multi_agent_causality.py
    tests/test_multi_agent_concurrency.py
    tests/test_agent_trace_projection.py
    tests/test_long_horizon_stall_detection.py

### 必须覆盖的特殊用例

1. 第七次模型调用仍能正常发生；
2. 同题二十次有信息增量调用不因旧六次阈值失败；
3. 第 40 次后投机分支停止、收敛类调用仍可用；
4. 第 48 次可派发、第 49 次不进入 `client.chat`；
5. Router 一定最先；
6. LemmaCurator 一定独立调用；
7. Primary/Alternative 首次提交前隔离；
8. 双向 Peer Review；
9. Rebuttal 引用 Finding；
10. Verifier 驳回错误 Peer Review；
11. Repair 失败回滚；
12. New Branch 重新进入互审；
13. Final Audit 失败触发下一循环；
14. 无进展停止；
15. Deadline 停止；
16. 第四题等待；
17. RPM 第 201 个物理额度等待；
18. solve 结束状态释放；
19. Router、Progress、Standard Candidate、Proof、Review 和 Repair 使用各自的 Token/超时策略；
20. 200 秒返回的 8192 Candidate 不被旧 165 秒阈值提前判死；
21. 剩余 Deadline 不足时拒绝长 Proof Turn，但仍能确定性最终化；
22. 超时后的后台尾调用阻止同 Agent 原样立即重试，并持续计入模型并发；
23. 迟到成功不能覆盖已冻结或 superseded Artifact；
24. `finish_reason=length` 的可解析输出仍为 partial，不能通过 Candidate/Proof 完整性门；
25. compact_synthesis 不复制全部历史上下文，并能从 Artifact 恢复最小完整 Candidate；
26. 12288/16384 配置在 Provider 不支持时有显式降级和 Trace，不静默伪装为已生效；
27. 三题并发压力下分别统计各 Turn 类型 P95，而不是只测单题串行。

---

## 37. 风险与缓解

### 风险 1：提高 Call Cap 后成本和延迟增加

缓解：

- 仍有每题 48 次题级硬上限（正式值可由 F8 校准）；
- 仍有 16/28/40 软检查点和 8 次收敛预留；
- 仍有 200 RPM；
- 仍有模型并发；
- 仍有 Deadline；
- 每 Agent 一次只允许一个 in-flight call；
- Case 和 Agent 公平调度；
- 信息增量门和阶段边界；
-重复 hash 和 stall 检测；
- Provider Circuit。

### 风险 2：所有题都运行全团队导致延迟增加

这是最新需求的直接结果，不通过跳过 Agent 缓解。采用：

- Solver 并行；
- 公平队列；
- 消息触发唤醒；
- 无任务 Agent 不空轮询；
- 确定性工具异步执行；
- Context 增量加载；
- Finalization Reserve。

### 风险 3：同模型 Agent 错误相关

缓解：

- 独立调用；
- 独立 State；
- 首次 Candidate 隔离；
- 不同方法和表示；
- Solver 互审；
- 独立 Verifier；
- 最终 Audit；
- 错误相关消融。

### 风险 4：通信变成无效辩论

缓解：

- Message 必须引用 Artifact；
- Peer Review 必须引用 Claim；
- Rebuttal 必须引用 Finding；
- 重复 hash 拒绝；
- 每个 Thread 有关闭条件；
- 没有新证据或状态变化不继续。

### 风险 5：Agent 自主性被 Host 重新吞噬

缓解：

- 下一步由 Agent Action 提议；
- Host 只做允许/拒绝；
- Trace 记录 Action；
- Planner 的 Task 提议必须实际调度；
- Agent 可自主 continue、request、abstain；
- 评测 Agent Action 的实际影响率。

### 风险 6：LLM Lemma 错误传播

缓解：

- Lemma 默认 proposed；
- 不作为 hard evidence；
- 条件和依赖必填；
- Solver 使用时必须创建 Claim；
- Verifier 和工具重新检查；
- 来源 Candidate 被拒绝时 Lemma 失效。

### 风险 7：公共 Trace 过大

缓解：

- Store 保存完整题内 Artifact；
- Trace 只投影摘要；
- Message 只展示类型和引用；
- 不输出完整失败 Candidate；
- 不输出原始模型响应；
- 保留现有字节和事件限制。

### 风险 8：阶段超时过短或过长

过短会把正常长输出误判为失败并堆积后台尾调用；过长会挤压 Peer Review、Final Audit 和确定性最终化。缓解：

- 按 Turn 类型设置不同值，不再跨角色统一 165 秒；
- 用同 Provider、三题并发下的 P95 加 10%–20% 余量校准；
- 有效超时受剩余 Deadline 和最终化预留裁剪；
- 同 Agent 单 in-flight，Tail 有界并接入 Circuit；
- 迟到结果版本校验，禁止覆盖已冻结状态；
- timeout 率、late-success 和尾调用存续时间进入冻结门。

### 风险 9：简单提高 Solver Tokens 反而扩大延迟和截断

仅将 8192 提到 12288/16384 可能让模型输出更冗长、阶段更慢，并不能保证 JSON 闭合或证明正确。缓解：

- 探索固定使用更短的 4096-token Progress Turn；
- 标准 Candidate 保持 8192，只有完整证明使用 12288 canary；
- Prompt 引用 Artifact，不重复整份历史；
- 关键字段优先输出，`length` 一律视为 partial；
- 通过 compact synthesis 或指定 Obligation 补全恢复，不原样重试；
- 16384 默认关闭，仅在证明完整率净收益超过延迟、截断和 Final Audit 损失时晋升。

---

## 38. 明确不做

- 不修改 main.py；
- 不修改 llm_client.py；
- 不创建其他在线模型客户端；
- 不读取 API Key；
- 不读取客户端私有字段；
- 不使用原生函数调用假设；
- 不恢复旧的六次单题模型调用上限；
- 不给每个 Agent 或阶段预切固定调用份额；
- 不设置固定最大推理轮数，但保留题级有限硬上限；
- 不跳过 Router；
- 不把 LemmaCurator 继续伪装成 Agent 但只运行确定性函数；
- 不用 Host 生成 Peer Review；
- 不用一个模型输出复制成多个 Agent 输出；
- 不保存私有 CoT；
- 不增加跨题可写记忆；
- 不构建分布式网络消息队列；
- 不用角色数量代替实测收益。

---

## 39. 最终 Definition of Done

### 39.1 强制路由

- [ ] 每题第一个认知模型调用属于 RouterPlanner；
- [ ] Router 独立调用模型；
- [ ] Router 输出 PlanArtifact；
- [ ] Plan 实际决定 Solver 和验证 Task；
- [ ] Router 可以被 replan 消息再次唤醒。

### 39.2 独立 Agent

- [ ] RouterPlanner 独立调用模型；
- [ ] PrimarySolver 独立调用模型；
- [ ] AlternativeSolver 独立调用模型；
- [ ] LemmaCurator 独立调用模型；
- [ ] Peer Reviewer 独立调用模型；
- [ ] VerifierSkeptic 独立调用模型；
- [ ] RepairAgent 启动时独立调用模型；
- [ ] Final Audit 使用独立 Verifier 实例；
- [ ] 没有 Agent 输出由 Host 伪造。

### 39.3 自主性

- [ ] Agent 每 Turn 输出 Action；
- [ ] Agent 可以自主 continue_reasoning；
- [ ] Agent 可以 request_lemma；
- [ ] Agent 可以 request_tool_check；
- [ ] Agent 可以 request_peer_review；
- [ ] Agent 可以 request_replan；
- [ ] Agent 可以 abstain；
- [ ] Action 对后续 Task 有实际影响；
- [ ] Host 不替 Agent生成数学内容。

### 39.4 通信

- [ ] Agent 通过 MessageEnvelope 通信；
- [ ] Message 有 sender、recipient、thread、reply_to；
- [ ] Message 引用 Artifact；
- [ ] 通信可以唤醒 Agent；
- [ ] 双向 Solver Peer Review 完成；
- [ ] 作者 Rebuttal 回应真实 Finding；
- [ ] 通信因果链可由 Trace 验证。

### 39.5 候选与审阅

- [ ] 每题至少两个独立 Candidate；
- [ ] Candidate 首次发布前 Solver 隔离；
- [ ] 独立性不仅检查方法字符串；
- [ ] Primary 审查 Alternative；
- [ ] Alternative 审查 Primary；
- [ ] Verifier 审查 Candidate、Peer Review 和 Rebuttal；
- [ ] New Branch 重新进入互审。

### 39.6 长程推理

- [ ] Competition 题级逻辑调用硬上限显式为 48（或经 F8 校准后的有限值），不是 6；
- [ ] 没有 fixed planned_rounds；
- [ ] Agent 可进行超过旧六次上限的模型 Turn；
- [ ] 不给单个 Agent 或阶段切死调用份额；
- [ ] 16/28/40 软检查点和 8 次收敛预留生效；
- [ ] 第 49 次请求不会进入 `client.chat`；
- [ ] CallLedger 记录，SessionCallBudget 执行硬边界；
- [ ] ResourceGovernor 由进展、Deadline、RPM、并发和预算阶段治理；
- [ ] Solver Progress、Standard Candidate 和 Proof Candidate 的输出上限分别配置，未统一写死为 8192；
- [ ] 长程能力由多轮 ProgressArtifact 延续，而不是依赖无限增大单次输出；
- [ ] `finish_reason=length` 不会被当成完整 Candidate 或完整证明；
- [ ] 无进展可终止；
- [ ] Deadline 可终止；
- [ ] 没有无限空转。

### 39.7 验证与修复

- [ ] hard evidence 仍优先；
- [ ] Peer Review 为 soft；
- [ ] Verifier Finding 为 soft；
- [ ] Repair claim-local；
- [ ] Repair 后重新验证；
- [ ] Evidence 下降回滚；
- [ ] 全局错误进入 New Branch；
- [ ] Final Audit 审查最终版本；
- [ ] proof completion 状态真实。

### 39.8 资源与安全

- [ ] 题目并发最多 3；
- [ ] 任意滚动 60 秒物理请求最多 200；
- [ ] 模型并发有界；
- [ ] 每 Agent 最多一个 in-flight call；
- [ ] Router、Progress、Standard Candidate、Proof、Review、Repair 和 Finalizer 使用分层阶段执行超时；
- [ ] 不存在所有阶段统一 165 秒的 Competition 路径；
- [ ] 有效阶段超时受剩余 Deadline 与最终化预留裁剪；
- [ ] background tail 有界、可观测、继续占并发且阻止同 Agent 重试风暴；
- [ ] 迟到结果不能覆盖已冻结或 superseded Artifact；
- [ ] 三 Case 公平；
- [ ] Agent 间公平；
- [ ] 无跨题状态泄漏；
- [ ] Trace 无私有 CoT；
- [ ] main.py、llm_client.py 未修改。

### 39.9 评测

- [ ] 干净工作树完整测试通过；
- [ ] 88 题全部落盘；
- [ ] C0 至 C7 消融完成；
- [ ] 调用次数分布、软检查点和硬上限命中率均进入报告；
- [ ] 按 Turn 类型报告执行耗时 P50/P95、length 率、timeout 率、late-success 和 Token 档位利用率；
- [ ] 关键收敛调用 length 率低于 5%，非故障注入阶段 timeout 率低于 2%；
- [ ] fallback 单独标记且使用率低于 5%，冻结目标低于 2%；
- [ ] 12288 Proof 已验证 Provider 支持且有净收益，16384 仍默认关闭或有独立晋升证据；
- [ ] 不出现第 49 次实际模型派发；
- [ ] active baseline 与当前提交匹配；
- [ ] Competition 只有通过门禁后改为 validated。

---

## 40. 最终实施优先级

建议严格按以下顺序实施：

1. F0：基线和治理；
2. F1：并发 3、200 RPM、ResourceGovernor、48 次题级 Call Budget、分层阶段超时与后台尾调用治理；
3. F2：Agent、Task、Action、Message、Artifact 基础协议；
4. F3：每题强制 RouterPlanner；
5. F4：自主长程 Solver、LLM LemmaCurator、Progress/Candidate 分类型 Token Contract 与 length 恢复；
6. F5：CandidatePool、双向 Peer Review 和 Rebuttal；
7. F6：Verifier、Repair/New Branch、Final Audit；
8. F7：Proof、Runtime 和 Trace 收敛；
9. F8：真实并发测试、消融和配置冻结。

在扩大 Agent 扇出或启用更大的 Proof Token 档位前，先完成 F1 的调用生命周期治理；否则更多 Agent 只会放大固定超时、后台尾调用和重试压力。不能先修改 Prompt 再补 Runtime，也不能只增加 Agent 名称。真正多 Agent 的判断依据是：

- 独立模型调用；
- 独立状态；
- 自主 Action；
- 显式 Message；
- 不可变 Artifact；
- 多候选；
- 双向交叉审阅；
- 验证、修复和最终审计闭环；
- 长程推理不受六次或固定轮次限制，但受显式题级有限硬上限和收敛预留约束；
- 长程 Solver 采用多轮 Progress + 分类型 Candidate 合成，且阶段超时与输出规模成对校准；
- 在并发 3 和 200 次/分钟下稳定运行。

完成 F0 至 F7 后，项目可以合理称为：

> 每题强制由 RouterPlanner 启动，多个独立 LLM Agent 通过题内任务、消息、候选、交叉审阅、验证和修复进行长程协作，并由确定性 Host 在全局资源与证据约束下完成最终决策的真正多 Agent 数学推理系统。

完成 F8 且获得有效实测证据后，才能进一步声称：

> 该真正多 Agent 架构已在三题并发、全局 200 次/分钟、每题 48 次（或经 F8 校准后的有限）逻辑调用硬上限的正式约束下，取得可重复的正确率、证明完整性或可靠性净收益。
