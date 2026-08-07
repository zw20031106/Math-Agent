# Math-Agent 真正多 Agent 架构审查与整改实施方案

> 状态：Superseded Design History
> 被取代方案：`MATH_AGENT_TRUE_MULTI_AGENT_FINAL_ARCHITECTURE_AND_IMPLEMENTATION_PLAN_2026-08-02.md`
> 说明：本文保留用于审查追溯，其中“每题六次调用”不再是目标架构或实施约束
> 文档日期：2026-08-01
> 审查基线：b5a743426a85c7d843215dec590497a61f0067f2
> 审查范围：正式入口、MathForgeHarness、固定角色、Prompt Contract、上下文与记忆、候选生成、验证修复、证明完成、并发与限流、测试和评测证据
> 文档性质：只读审查后的实施设计；本文件不代表代码已经整改完成

---

## 1. 执行摘要

当前项目不是简单的单 Prompt 系统，也不是只有名称不同的伪 Agent：

- PrimarySolver 与 AlternativeSolver 具有不同方法族和不同观察空间；
- AlternativeSolver 在生成候选时看不到 PrimarySolver 的解答正文；
- VerifierSkeptic 能审查结构化 Candidate、Claim、Evidence、Proof Obligation 和冲突目标；
- RepairAgent 已具备局部修复、版本化、重新验证和证据下降回滚；
- Harness 已有题内 Session、调用预算、Deadline、硬证据门、确定性工具、仲裁和 Trace。

但当前仍应定性为：

> 由单一中央 Harness 编排的、同一模型驱动的多角色数学推理流水线。

它尚不满足本项目“真正多 Agent”的最低条件，核心缺口不是 Agent 名称不足，而是：

1. 没有题内稳定 Agent 身份和独立 AgentState；
2. 没有显式 AgentTask、Message 和不可变 Artifact 协议；
3. Planner 的输出没有形成真正决定后续任务的 Task DAG；
4. Solver、Verifier、Repair 之间没有可追踪的消息级闭环；
5. Harness 同时承担了过多生命周期和开放式流程决策；
6. proof_full 的完成状态和成功语义不一致；
7. 当前题目并发是 4，不符合并发 3 的约束；
8. 只有模型并发门，没有 200 次/分钟滚动限流；
9. 当前 Competition 配置没有与当前提交匹配的有效准确率和消融证据。

本方案的目标不是继续增加角色名称，而是将现有固定角色升级为真正的题内 Agent 实例：

> 确定性 Host Agent Runtime
> + 固定角色的任务级 Agent 实例
> + 题内 Mailbox
> + 不可变 Artifact Store
> + 显式 Critique、Repair、Audit 因果闭环
> + 证据驱动的确定性最终决策

整改必须遵守以下硬约束：

- main.py 和 llm_client.py 永远不修改；
- 仅通过注入的 client.chat 接口访问模型；
- 每个 solve 创建全新 Session 和全新 Agent 实例；
- 题目最大并发为 3；
- 模型请求最高为 200 次/分钟；
- 每题最多 6 次逻辑模型调用；
- 固定角色集合保持不变；
- 工具、证据门、预算、并发、仲裁、格式化和 Trace 保持确定性；
- RepairAgent 继续只做 Claim-local 修复；
- 评测期间不增加跨题可写长期记忆；
- 不在 Trace、Message 或 Artifact 中保存私有思维链。

---

## 2. 审查基线与证据边界

### 2.1 本轮只读检查结果

- 冻结基线脚本通过；
- 230 个 Python 文件完成 AST 解析；
- 当前工作树测试结果为 654 passed；
- git diff --check 通过；
- Competition 配置状态仍为 candidate-unvalidated；
- evaluation_evidence_registry.json 的 active_baseline_id 仍为空。

### 2.2 当前工作树注意事项

审查开始前已经存在：

    D tests/test_phase0_0730_baseline.py

该删除不是本轮造成的。本方案实施前必须由仓库所有者决定是否恢复；在它未恢复前，不能把当前 654 个测试视为干净 HEAD 的完整测试门禁。

### 2.3 用户给定约束优先级

两份参考 Markdown 文件只作为审查假设，不是事实源。以下约束以本次用户说明为准：

- 同时处理的题目数最多为 3；
- 模型调用最高限制为 200 次/分钟。

凡是 README、旧报告、配置或测试中与这两个数字冲突的内容，都必须整改。

---

## 3. 当前架构的真实定性

### 3.1 当前主流程

当前 MathForgeHarness.solve 大致执行：

    Problem
      -> ProblemParser
      -> deterministic Router / optional RouterPlanner
      -> CallAllocationPlan
      -> PrimarySolver
      -> optional AlternativeSolver fan-out
      -> Candidate admission
      -> tools and hard evidence
      -> proof obligations
      -> optional local repair
      -> conflict matrix
      -> one VerifierSkeptic batch
      -> optional repair and re-verification
      -> ProofCompletionGate
      -> deterministic arbitration
      -> deterministic formatter
      -> final response and trace

这个流程已经有多个认知角色，但所有角色都由中心函数直接调用。角色没有独立任务队列、稳定题内身份或消息生命周期。

### 3.2 当前已经做对的部分

以下能力必须保留，不能在多 Agent 重构中退化：

- 每个 solve 创建独立 MathSession；
- CallBudget 的消费是线程安全的；
- 共享模型客户端通过有界模型调用门保护；
- AlternativeSolver 的上下文在 Primary Candidate 生成前构建；
- RoleContextView 和 MemoryBlackboard 已有角色权限边界；
- CandidateSolution、EvidenceRecord、ProofObligation、CandidatePatch 已有严格 Schema；
- Verifier 的 Finding 必须引用真实 Candidate、Claim 或 Obligation；
- 模型审查只产生 soft evidence；
- hard evidence 在仲裁前执行淘汰；
- Repair 使用影响闭包、重新验证和回滚；
- 词典序仲裁优先于加权分数；
- 确定性 Formatter 为默认路径；
- Trace 有大小和隐私约束；
- 长期知识库在评测路径中只读。

### 3.3 当前不属于真正多 Agent 的部分

按严格多 Agent 判据，当前缺少：

| 维度 | 当前状态 | 目标 |
|---|---|---|
| 身份 | 只有角色名和 Candidate ID | 每个题内实例有 agent_id 和 descriptor |
| 目标 | 主要存在于 Prompt Contract | 写入 AgentTask 和 AgentState |
| 观察 | 已有 RoleContextView | 升级为 Artifact 引用和 ACL |
| 状态 | 主要是共享 MathSession | 每个 Agent 有题内可审计状态 |
| 行动 | 输出 Candidate/Finding/Patch | 统一映射为 AgentAction 和 Artifact |
| 通信 | Host 直接传参 | 题内 MessageEnvelope 和 Mailbox |
| 委派 | Host 固定调用顺序 | Planner 产生 Task DAG，Host 校验后调度 |
| 因果 | 有部分隐式因果 | Message、Task、Artifact 和 Decision 全链路引用 |
| 自主性 | Host 决定所有下一步 | Agent 可完成、阻塞、弃权或请求受控后续动作 |
| 冲突解决 | 有冲突矩阵和单次 Verifier | Cross Exam、Repair/New Branch、Final Audit |
| 责任追踪 | 多套 ID，缺少统一 lineage | 统一 Artifact lineage 和 Agent 责任 |
| 终止 | Harness 阶段机 | Harness 阶段机 + Agent 生命周期机 |

当前严格评分约为 2.4/5。完成本方案 M0 至 M6 后，目标应达到至少 4/5。

---

## 4. 对参考整改方案的独立校准

### 4.1 应保留的判断

- 当前本质是中央 Harness 多角色流水线；
- 不能通过增加类名和 Prompt 数量宣称多 Agent；
- 需要显式任务、通信、Artifact 和 lineage；
- 六次调用不允许所有角色每题固定运行；
- Critique 必须引用真实 Claim 和证据；
- 修订后必须重新验证；
- Harness 仍应是确定性安全运行时；
- 新架构必须用消融实验证明收益。

### 4.2 不能直接照搬的建议

#### 不新增 PlannerAgent、CrossExaminerAgent、ReviserAgent、ProofAuditorAgent

仓库规定了固定角色：

- RouterPlanner
- PrimarySolver
- AlternativeSolver
- LemmaCurator
- VerifierSkeptic
- RepairAgent
- optional LLMFinalizer

因此采用角色模式而不是新角色名：

- RouterPlanner 的 plan 模式承担认知规划；
- VerifierSkeptic 的 cross_exam 模式承担定向质询；
- VerifierSkeptic 的 final_audit 模式承担最终证明审计；
- RepairAgent 继续承担局部修复；
- 全局错误通过新的 PrimarySolver 或 AlternativeSolver Task 生成新 Candidate。

#### 不把 RepairAgent 改成任意全局 Reviser

Repair 的 Claim-local、版本化、重新验证、回滚是仓库硬约束。全局换路应创建新的 Candidate lineage，不能把整条方法替换伪装成旧 Candidate 的局部版本。

#### 不在 Competition 中增加跨题可写记忆

真正多 Agent 不等于必须跨题持久化。Competition 要求每题状态隔离并在 solve 后释放。Checkpoint 可以是题内 Artifact，不能变成跨题共享的可写记忆。

#### 不先建设通用分布式 Event Bus

本项目是单进程、六模型调用、单题最长约十五分钟的同步运行时。第一版只需要：

- 题内有界 Mailbox；
- 不可变 ArtifactStore；
- 确定性 Task Scheduler；
- 单调事件序号。

不需要网络队列、数据库、服务发现或跨进程分布式事务。

#### 不把 hard evidence 当作任意数学证明的唯一完成来源

确定性工具无法为所有抽象数学证明提供 hard evidence。应区分：

- hard-complete；
- audited-complete；
- incomplete；
- failed。

否则大量完整但无法工具化验证的证明会被机械判失败。

---

## 5. 真正多 Agent 的项目内定义

本项目只有同时满足以下条件，才能称为真正多 Agent：

1. 每个参与角色在每道题中都有唯一 agent_id；
2. Agent 由只读 AgentDefinition 和题内 AgentInstance 组成；
3. 每个 AgentInstance 有自己的目标、任务、状态、观察范围和停止原因；
4. Agent 只通过 AgentTask 接受工作；
5. Agent 输出必须形成版本化 Artifact；
6. Agent 间协作必须通过 MessageEnvelope 和 Artifact 引用发生；
7. Planner 的输出必须实际改变 Solver 方法分配和验证计划；
8. AlternativeSolver 在提交候选前不能看到 PrimarySolver 的 Candidate；
9. Verifier 的 Critique 必须实际触发 Repair、New Branch、Reject 或 Audit 决策；
10. Repair 只能修改授权影响闭包；
11. Final Audit 必须观察修订后的最终 Artifact，而不是修订前摘要；
12. Host 不生成开放式数学内容；
13. Host 对任务、权限、预算、Schema、证据和终止拥有最终确定性控制；
14. 所有 Agent 状态在 solve 结束后释放；
15. 全部因果链能够投影为不泄露私有推理的公共 Trace。

仅满足“有多个角色类”“并行调用两次模型”或“使用同一个 Blackboard”不能通过验收。

---

## 6. 目标总体架构

    ReasoningAgent
      |
      | case admission: max 3
      v
    MathForgeHarness facade
      |
      v
    SessionAgentRuntime
      +-- AgentRegistry
      +-- AgentTaskScheduler
      +-- SessionMailbox
      +-- SessionArtifactStore
      +-- AgentStateRegistry
      +-- ModelAdmissionController
      +-- Deterministic Services
      |     +-- parsing
      |     +-- context and ACL
      |     +-- tools
      |     +-- evidence
      |     +-- proof obligations
      |     +-- conflict graph
      |     +-- arbitration
      |     +-- formatting
      |     +-- trace projection
      |
      +-- Agent Instances
            +-- RouterPlanner instance
            +-- PrimarySolver instance
            +-- AlternativeSolver instance(s)
            +-- LemmaCurator instance
            +-- VerifierSkeptic cross-exam instance
            +-- RepairAgent instance
            +-- VerifierSkeptic final-audit instance
            +-- optional LLMFinalizer instance

MathForgeHarness 保留稳定公共入口。新的 SessionAgentRuntime 负责题内 Agent 生命周期，底层继续复用现有 Provider、Parser、Tool、Evidence、Proof 和 Formatter。

---

## 7. Host 与 Agent 的职责边界

### 7.1 Host 必须保留

- Problem 解析和 Schema 校验；
- Agent 注册与实例创建；
- Task 和 Message Schema 校验；
- Artifact ID、版本和 hash 生成；
- Artifact ACL 和可见性过滤；
- 题目并发与模型并发；
- 200 次/分钟速率限制；
- 单题调用预算和阶段预算；
- Deadline 和取消；
- 确定性工具执行；
- EvidenceLedger；
- Proof Obligation 生成；
- Conflict Graph 的确定性构建；
- Candidate admission；
- hard evidence gate；
- Repair 影响闭包计算；
- 确定性仲裁；
- Formatter、Fallback、Trace；
- 非法 Agent 输出拒绝；
- Agent 超时、失败和弃权后的降级。

### 7.2 Host 不应继续承担

- 为中高风险题编写开放式子目标分解；
- 生成数学解答正文；
- 为 Alternative 伪造不同方法；
- 替 Verifier 给出语义 Critique；
- 将不完整证明宣称为完整；
- 编写 Repair 内容；
- 用加权分数覆盖硬证据；
- 隐式拼接任意自由文本模拟 Agent 通信；
- 在没有 Agent Artifact 的情况下宣称某角色已参与。

### 7.3 Host 可以采用确定性 fallback

下列情况允许确定性 fallback：

- RouterPlanner 不可用时使用 RouterRuleEngine；
- Planner 输出非法时生成最小安全 Plan；
- Agent 超时或失败时取消其未派发 Task；
- 没有修复预算时保留最后一个未被硬证据否定的 Candidate；
- LLMFinalizer 失败时使用 DeterministicFormatter；
- 所有 Candidate 失败时使用 FallbackSolver。

Fallback 必须在 Trace 中显式记录，不能伪装成对应认知 Agent 成功。

---

## 8. Agent 定义、实例和状态

### 8.1 只读 AgentDefinition

AgentDefinition 在 Harness 初始化时创建并只读共享：

    AgentDefinition
      role
      capabilities
      allowed_task_types
      readable_artifact_types
      writable_artifact_types
      prompt_contract_name
      prompt_contract_version
      skill_roles
      default_failure_policy

它替代重复加载和重复构造 Prompt 角色信息，不保存题目状态。

### 8.2 题内 AgentInstance

每个 solve 创建独立实例：

    AgentInstance
      descriptor
      state
      inbox
      produced_artifact_ids
      consumed_task_ids

agent_id 推荐格式：

    {session_id}:{role}:{mode}:{ordinal}

例如：

    8f2a...:PrimarySolver:solve:1
    8f2a...:AlternativeSolver:solve:1
    8f2a...:VerifierSkeptic:cross_exam:1
    8f2a...:VerifierSkeptic:final_audit:1

同一个固定角色可以在同一道题中有不同模式和实例，但不能引入固定角色集合以外的新模型角色。

### 8.3 AgentState

AgentState 只保存可审计的公共控制状态，不保存私有思维链：

    agent_id
    role
    mode
    lifecycle_status
    active_task_id
    completed_task_ids
    input_artifact_ids
    output_artifact_ids
    pending_message_ids
    used_model_calls
    open_obligation_ids
    last_event_sequence
    stop_reason
    failure_code

生命周期状态：

- created
- ready
- running
- waiting
- completed
- abstained
- failed
- cancelled

允许的状态迁移必须由确定性状态机校验。

---

## 9. AgentTask 协议

Agent 不能被 Host 通过任意函数参数直接驱动。所有认知工作必须先形成 AgentTask：

    AgentTask
      schema_version
      task_id
      session_id
      assigned_agent_id
      role
      mode
      objective
      input_artifact_ids
      required_output_type
      allowed_tool_capabilities
      forbidden_artifact_types
      model_call_allowance
      max_context_chars
      deadline_seconds
      priority
      parent_task_id
      status

### 9.1 Task 类型

- route
- plan
- solve_primary
- solve_alternative
- continue_reasoning
- curate_lemma
- cross_exam
- repair_claims
- solve_new_branch
- final_audit
- finalize_copy

### 9.2 Task 创建权限

- Host 可以创建任何经过策略允许的 Task；
- RouterPlanner 可以在 PlanArtifact 中提议 Solver 和验证 Task；
- VerifierSkeptic 可以在 CritiqueArtifact 中提议 repair_claims 或 solve_new_branch；
- RepairAgent 不能自行扩大修复范围；
- Solver 不能直接创建另一个 Solver；
- Agent 的提议只有经 Host 验证预算、角色、依赖和 Deadline 后才成为正式 Task。

### 9.3 Task 完成条件

Task 只有在以下条件满足时才完成：

- 输出 Artifact Schema 合法；
- producer_agent_id 与 assigned_agent_id 一致；
- 输入 Artifact 引用真实且可见；
- 输出类型与 required_output_type 一致；
- 没有越权引用 forbidden_artifact_types；
- 模型调用未超预算；
- AgentState 已记录 stop_reason。

---

## 10. Message 与 Mailbox 协议

### 10.1 MessageEnvelope

    MessageEnvelope
      schema_version
      message_id
      session_id
      sender_id
      recipient_id
      message_type
      artifact_refs
      task_ref
      reply_to
      public_rationale
      priority
      created_sequence
      expires_at

### 10.2 允许的消息类型

- task_assigned
- artifact_available
- review_requested
- critique_available
- repair_requested
- repair_completed
- new_branch_requested
- audit_requested
- audit_completed
- task_abstained
- task_failed
- task_cancelled

### 10.3 Mailbox 规则

- Mailbox 仅存在于当前 Session；
- 每个 Agent 只能读取发给自己的消息；
- 消息只携带 Artifact 引用和短公共说明；
- 禁止携带私有思维过程；
- Mailbox 有最大消息数和最大序列化字符数；
- 重复 message_id 必须拒绝；
- 过期消息不得重新激活已结束 Agent；
- failed Candidate 的 Artifact 不得通过消息重新变为 active；
- solve 结束后 Mailbox 清空。

### 10.4 为什么需要轻量 Mailbox

真正多 Agent 要求协作行为有显式发送者、接收者和因果关系。当前 Host 直接把 Python 对象拼到下一个 Prompt，无法证明：

- 谁提出了 Critique；
- 谁接收了 Repair Request；
- 修订回应的是哪个 Finding；
- Final Audit 审查的是哪个版本。

轻量 Mailbox 用于解决这一责任链问题，不用于构建分布式系统。

---

## 11. Artifact 协议

### 11.1 ArtifactEnvelope

现有 CandidateSolution 等数学 Schema 继续作为 payload，不重新复制一套字段。

    ArtifactEnvelope
      schema_version
      artifact_id
      artifact_type
      session_id
      producer_agent_id
      producer_task_id
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

| 类型 | Payload |
|---|---|
| problem | ProblemIR |
| route | RoutePlan |
| plan | AgentPlan |
| candidate | CandidateSolution |
| evidence_batch | EvidenceRecord 列表 |
| obligation_batch | ProofObligation 列表 |
| lemma_batch | LemmaCard 列表 |
| conflict_graph | ConflictGraph |
| critique | CritiqueArtifact |
| repair_patch | CandidatePatch |
| repair_result | RepairResult |
| audit | AuditArtifact |
| decision | DecisionArtifact |
| checkpoint | 题内公共状态摘要 |

### 11.3 不可变规则

1. Artifact 发布后不可原地修改；
2. 新版本必须生成新 artifact_id；
3. 新版本必须引用父 Artifact；
4. payload 在写入时深拷贝、严格序列化并计算 hash；
5. 读取 Candidate 时从规范化 payload 重建对象，不能返回 Store 内部可变引用；
6. Evidence transaction 状态变化形成新 Evidence Artifact；
7. Repair 回滚保留被拒绝版本，但其状态为 rejected；
8. hard-failed Artifact 不得重新标记为 active；
9. DecisionArtifact 必须引用最终 Candidate、Audit 和 Evidence；
10. Trace 从 Artifact 和 Message 事件投影，不直接复制模型原始响应。

### 11.4 迁移注意

现有 CandidateSolution、Claim 和 ProofObligation 是可变 dataclass，当前运行时会原地更新验证状态。不能一次性替换。

采用两步迁移：

1. Shadow Artifact：先在每个旧阶段结束后生成不可变快照，不改变旧行为；
2. Authoritative Artifact：测试稳定后，阶段间只传 artifact_id，并通过 from_dict 重建对象。

---

## 12. 固定角色的真正 Agent 化设计

### 12.1 RouterPlanner

身份：

- role：RouterPlanner
- mode：route 或 plan

输入：

- ProblemArtifact；
- 确定性 ProblemIR；
- 调用和时间预算摘要；
- 不得看到任何 Candidate。

输出：

- RouteArtifact；
- 中高风险题可输出 PlanArtifact。

PlanArtifact 至少包含：

- subgoal DAG；
- 每个子目标的必要条件；
- Primary 和 Alternative 的方法族分配；
- 禁止的重复方法；
- 预期证明义务；
- 工具验证建议；
- 冲突审查重点；
- 停止和换路条件。

自主性：

- 可以判断无需多个候选；
- 可以声明路由不确定；
- 可以提出两个真正不同的方法；
- 不能直接调用 Solver；
- 不能改变总调用上限。

调用策略：

- 低风险题使用 RouterRuleEngine，不消耗模型调用；
- 中高风险且确定性路由置信度不足时才消耗一次模型调用。

### 12.2 PrimarySolver

身份：

- role：PrimarySolver
- mode：solve、explore、continue 或 new_branch

输入：

- ProblemArtifact；
- PlanArtifact 中分配给自己的 Task；
- Problem Obligation Artifact；
- 授权 Skill；
- 题内公开 ReasoningState；
- 不得看到私有失败响应。

输出：

- CandidateArtifact 或 Progress Artifact；
- 显式 stop_reason；
- unresolved obligations。

状态：

- 当前方法族；
- 已完成子目标；
- 未完成义务；
- 已使用调用数；
- 已产生 Artifact。

自主性：

- 在分配的方法族内决定公开推导；
- 可以 completed、blocked 或 abstained；
- blocked 时只能说明公开缺口，不能输出私有思维链；
- 不能读取 Alternative 的候选后再伪装成独立解。

### 12.3 AlternativeSolver

身份：

- role：AlternativeSolver
- mode：solve 或 new_branch

独立性要求：

- 只能看到 Problem、Plan 中自己的方法任务、Problem Obligations 和允许的 Skills；
- 可以看到 Primary 的方法标签以避免重复；
- 不能看到 Primary solution_text、Claims、final_answer 或 Evidence；
- 在自己 Candidate 发布前，Mailbox 不投递 Primary CandidateArtifact。

结构差异要求：

- 表示空间不同，或；
- 核心不变量不同，或；
- 证明方向不同，或；
- 主要定理链不同。

仅改变 method 字符串不能通过独立性门。

### 12.4 LemmaCurator

当前生产实现是确定性 Claim-to-Lemma 服务。建议保留这种实现：

- 创建题内 AgentInstance 和任务记录；
- 消费经过验证的 Claim Artifact；
- 输出 Lemma Artifact；
- execution_mode 记录为 deterministic；
- 不为满足“Agent 名称”额外消耗模型调用。

如果未来确实需要 LLM LemmaCurator，必须有单独消融证明它比确定性版本有稳定净收益。

### 12.5 VerifierSkeptic：cross_exam

输入：

- Problem、条件和响应模式；
- Candidate Artifacts；
- Claim Graph；
- Evidence；
- Proof Obligations；
- Conflict Graph；
- 明确 Review Target。

输出 CritiqueArtifact：

    critique_id
    target_candidate_ids
    finding_items
    covered_review_target_ids
    uncovered_review_target_ids
    recommended_action
    confidence
    stop_reason

每个 Finding 必须包含：

- candidate_id；
- claim_id 或 answer target；
- obligation_ids；
- review_target_ids；
- pass、fail 或 unknown；
- 公开理由；
- 缺失条件；
- 公开反例摘要；
- 建议 local_repair、new_branch、reject 或 no_action。

Verifier 不得：

- 把 unknown 当 pass；
- 产生 hard evidence；
- 修改 Candidate；
- 使用不存在的 Claim ID；
- 隐藏未覆盖 Review Target。

### 12.6 RepairAgent

输入：

- CritiqueArtifact；
- 被授权 CandidateArtifact；
- Host 计算的影响闭包；
- 相关 Evidence；
- 原始条件。

输出：

- RepairPatchArtifact；
- 或 Abstain。

必须保证：

- 只修改授权 Claim 闭包；
- 引用具体 Finding；
- 保留未授权 Claim；
- 产生新 Candidate 版本；
- 重新验证后才能成为 active；
- Evidence 下降、硬失败残留或依赖不完整时回滚。

若 Critique 判定核心方法错误，Host 不创建 repair_claims Task，而是创建 solve_new_branch Task。

### 12.7 VerifierSkeptic：final_audit

Final Audit 使用同一固定角色，但必须是新的题内 AgentInstance：

- 不接收 Cross Exam 的原始模型响应；
- 只接收规范化 Critique、最终 Candidate、Repair lineage、Evidence 和 Obligations；
- 目标是判断最终候选是否满足当前 response_mode；
- 不负责润色；
- 不负责再次修复。

输出 AuditArtifact：

    audited_candidate_id
    audited_version
    coverage
    unresolved_essential_obligations
    hard_failures
    verdict
    evidence_tier
    public_rationale

verdict：

- complete_hard
- complete_audited
- incomplete
- failed

### 12.8 LLMFinalizer

- 默认不实例化；
- 不进入 Competition 六调用核心路径；
- 只有在真实配对消融证明格式收益且数学内容零变化时才能启用；
- 失败时始终回退 DeterministicFormatter。

---

## 13. 标准交互闭环

### 13.1 中高风险题

    Host -> RouterPlanner: plan task
    RouterPlanner -> ArtifactStore: PlanArtifact
    Host -> PrimarySolver: primary task
    Host -> AlternativeSolver: blind alternative task
    PrimarySolver -> ArtifactStore: Candidate A
    AlternativeSolver -> ArtifactStore: Candidate B
    Host -> deterministic services: tools, evidence, obligations, conflict graph
    Host -> VerifierSkeptic cross_exam: review task
    VerifierSkeptic -> ArtifactStore: CritiqueArtifact
    Host -> RepairAgent or Solver new branch: remediation task
    Repair/Solver -> ArtifactStore: revised or new Candidate
    Host -> deterministic services: re-verification
    Host -> VerifierSkeptic final_audit: audit task
    VerifierSkeptic -> ArtifactStore: AuditArtifact
    Host -> deterministic arbitration: DecisionArtifact
    Host -> formatter: final response

### 13.2 因果关系要求

- PlanArtifact 的方法分配必须出现在 Solver Task；
- Candidate 必须引用产生它的 Task 和 Plan；
- Critique 必须引用 Candidate 版本；
- Repair 必须引用 Critique Finding；
- repaired Candidate 必须引用旧 Candidate 和 RepairPatch；
- Audit 必须引用最终 Candidate 版本；
- Decision 必须引用 Audit、Evidence 和所选 Candidate；
- Trace 中每条多 Agent 关键事件都能回溯到上述引用。

---

## 14. 六次模型调用下的调度

### 14.1 低风险题

推荐：

1. PrimarySolver
2. 可选 VerifierSkeptic final_audit

调用数：1 至 2。

跳过：

- LLM RouterPlanner；
- Alternative；
- Repair；
- LLM Finalizer。

确定性工具不计模型调用。

### 14.2 中风险题

推荐：

1. PrimarySolver
2. AlternativeSolver
3. VerifierSkeptic cross_exam
4. RepairAgent，仅在有可操作局部缺陷时
5. VerifierSkeptic final_audit

调用数：

- 无缺陷：3 至 4；
- 有局部修复：5。

保留一个调用作为运输失败、全局新分支或长程继续的弹性额度。

### 14.3 高风险计算题

推荐：

1. RouterPlanner plan
2. PrimarySolver
3. AlternativeSolver
4. VerifierSkeptic cross_exam
5. RepairAgent 或 Solver new_branch
6. VerifierSkeptic final_audit

### 14.4 proof_full

推荐：

1. RouterPlanner plan
2. PrimarySolver proof
3. AlternativeSolver independent proof
4. VerifierSkeptic cross_exam
5. RepairAgent 或 Solver new_branch
6. VerifierSkeptic final_audit

如果第 5 次调用没有发生：

- 第 6 次仍用于 Final Audit；
- 不应为了用满预算而增加第三个未经审查的 Candidate。

### 14.5 调用降级优先级

预算或时间不足时，按以下顺序删除低价值工作：

1. LLMFinalizer；
2. 额外 Primary continuation；
3. 第二个 Alternative；
4. LLM RouterPlanner，回退确定性 Router；
5. 非必要 Cross Exam。

不得删除：

- Primary；
- Repair 后的重新验证；
- proof_full 的最终完成状态判定；
- 确定性最终格式化。

Repair 和 Final Audit 应作为原子预算对：

- 有预算完成 repair + audit 才启动 Repair；
- 否则保留原 Candidate，不提交未审查 Patch。

---

## 15. 题目并发 3 与模型 200 次/分钟

### 15.1 四个不同的限制

必须分别配置和观测：

| 限制 | 目标 |
|---|---:|
| 活跃题目数 | 3 |
| 单题逻辑模型调用 | 6 |
| 同时物理模型调用 | 初始建议 6，需实测校准 |
| 任意滚动 60 秒物理请求 | 200 |

不能把四个限制都写成 3，也不能用模型并发 16 代替 RPM 限流。

### 15.2 配置建议

Competition 配置新增：

    case_max_concurrency: 3
    model_requests_per_minute: 200
    transport_attempt_reservation: 3
    rate_limit_window_seconds: 60.0

初始校准：

    model_max_concurrency: 6
    max_background_model_tails: 6

model_max_concurrency 为 6 的原因：

- 每题最多两个 Alternative；
- 三题同时进入 Alternative fan-out 时，理论并行分支为 6；
- 如果模型并发也设为 3，其他分支可能在 15 秒排队预算内失败。

当前 16 没有与现配置匹配的有效实测证据，不应直接冻结。

### 15.3 物理请求不可见问题

正式 main.py 创建的 InternChatClient 默认内部 retry 为 3。Provider 只能看到一次 client.chat，无法看到内部每一次 HTTP 尝试，也不能读取客户端私有字段。

因此正式入口应对每次逻辑调用预留三个速率单位：

- 一个逻辑调用最大按 3 个物理请求计费；
- 66 个逻辑调用对应最多 198 个物理请求；
- 第 67 个逻辑调用必须等待窗口释放。

自定义运行器明确构造 retry=1 时，可以使用 reservation=1。该值必须来自受审计入口配置，不能通过反射读取客户端内部状态。

### 15.4 ModelAdmissionController

建议用一个统一准入控制器替换“先信号量、后 sleep”的组合：

    request arrives
      -> enqueue by stage priority and case fairness
      -> remove expired timestamps
      -> check model concurrency capacity
      -> check weighted 60-second quota
      -> check case Deadline
      -> atomically reserve capacity and rate units
      -> dispatch

规则：

- 未派发前超时不消耗速率额度；
- 已派发后额度不退款；
- 后台尾调用继续占并发槽；
- Rate Limit 等待计入模型队列时间；
- Answer formation 优先于可选探索；
- 三个 Case 间轮转公平；
- 不使用忙等；
- 使用 monotonic clock；
- 测试中可注入 fake clock。

### 15.5 多进程边界

进程内控制器只能保证同一 ReasoningAgent/进程的 200 RPM。如果官方平台并行启动多个进程并共享同一个配额，需要外部共享限流。当前正式 runner 是单进程共享一个 ReasoningAgent，因此第一阶段按单进程实现。

---

## 16. 验证、冲突与修复

### 16.1 Conflict Graph

当前 Conflict Matrix 应升级为图结构，但保留确定性构建：

节点：

- Candidate；
- Claim；
- Proof Obligation；
- Evidence；
- Method Step；
- Final Answer；
- Assumption。

边：

- depends_on；
- supports；
- contradicts；
- verifies；
- fails；
- addresses；
- derived_from；
- repairs；
- supersedes。

冲突类型：

- answer conflict；
- theorem-condition conflict；
- assumption conflict；
- claim contradiction；
- obligation coverage conflict；
- method representation collision；
- proof direction duplication；
- evidence mismatch。

Host 只负责提取冲突目标；语义质询由 VerifierSkeptic 完成。

### 16.2 Cross Exam 覆盖门

对每个高风险 Review Target：

- 必须有 Finding；
- Finding 必须覆盖目标中的每个 Candidate；
- pass 必须引用支持 Claim；
- fail/unknown 必须给出公开理由；
- 未覆盖目标写入 uncovered_review_target_ids；
- proof_full 存在未覆盖必要目标时，不能得到 complete_audited。

### 16.3 局部 Repair

沿用当前强项：

- failed Claim 影响闭包；
- Candidate 新版本；
- 重新验证；
- Evidence 质量比较；
- hard failure 检查；
- Final Answer 依赖检查；
- 原子接受或回滚。

新增：

- RepairPatch 引用 Critique Finding；
- Repair Task 明确授权范围；
- RepairAgent 可以 abstain；
- RepairResult 形成 Artifact；
- Audit 只看被接受版本。

### 16.4 全局换路

下列条件不应局部修复：

- 核心方法前提不成立；
- Candidate 的表示空间错误；
- Final Answer 与多个独立硬检查冲突；
- 关键 Claim 图大面积失效；
- Critique 建议 global_method_failure；
- Repair 影响闭包覆盖绝大多数关键 Claim。

Host 创建 solve_new_branch Task：

- 分配给 PrimarySolver 或 AlternativeSolver；
- 使用未尝试方法族；
- 新 Candidate 的 parent 指向 Problem/Plan，不指向旧 Candidate 修订版本；
- 旧 Candidate 保持 rejected 或 superseded。

---

## 17. Proof 完成状态与公共结果

### 17.1 目标状态

#### complete_hard

- 所有 required obligations 已满足；
- 每个义务都有能力匹配的 hard evidence；
- 没有 active hard fail；
- Final Audit 覆盖完整。

#### complete_audited

- 所有必要义务都有真实 Claim 映射；
- Cross Exam 和 Final Audit 均覆盖；
- 没有 fail 或 unknown 的必要义务；
- Evidence 强度可能包含独立模型审查；
- 不得描述为形式化或机器证明完成。

#### incomplete

- 存在缺失必要步骤；
- 存在未覆盖或 unknown 的必要义务；
- 可以返回 best available 非空答案；
- Trace 必须明确 degraded。

#### failed

- 存在 hard fail；
- 必要结论被反例否定；
- Candidate Schema 或依赖图不可接受；
- 没有可用 Candidate。

### 17.2 response_mode 策略

| response_mode | 最低可接受完成状态 |
|---|---|
| answer_only | 无 hard fail，答案通过适用验证 |
| worked_solution | 无 hard fail，关键推导无未处理 fail |
| proof_full | complete_hard 或 complete_audited |

incomplete 可以作为合同要求的非空 best available 返回，但不能在内部 Trace 中声称证明完成。

### 17.3 冻结 main.py 的限制

main.py 会把任何非空 final_response 写为 success，并忽略 ReasoningAgent 内部 status。因此：

- ReasoningAgent 内部必须返回准确 status；
- Judge Trace 必须包含 verification_status；
- 正式 main 输出的 status 不能被用作 proof 完成的唯一事实源；
- 不修改 main.py；
- 如果比赛要求公共 status 严格表示 proof 完成，必须向组织方确认冻结契约。

---

## 18. Context、Memory 与隐私

### 18.1 保留 RoleContextView

现有 RoleContextView 是可复用资产。升级后它从 ArtifactStore 生成：

- 只加载 Task.input_artifact_ids；
- 根据 AgentDefinition 做 Artifact ACL；
- 按 Claim 和 Obligation 聚焦；
- 继续执行字符和 Token 预算；
- 继续剔除原始私有失败响应。

### 18.2 Alternative 隔离

在 Alternative Candidate 发布前：

- 不允许读取 Candidate A；
- 不允许读取 Primary Claims；
- 不允许读取 Primary final_answer；
- 不投递 candidate_available 消息；
- 只允许看到 Primary 的方法族标签和禁止方法集合。

应增加单元测试，在恶意 Primary Candidate 中植入 canary，断言 Alternative Prompt 不包含该 canary。

### 18.3 题内 Checkpoint

Checkpoint Artifact 只保存：

- 当前 Plan；
- active Candidate IDs；
- hard Evidence refs；
- open Obligations；
- Task/Agent 状态；
- 已使用预算；
- 最终答案候选。

不保存：

- 私有 CoT；
- 原始失败模型响应；
- API 信息；
- 本地绝对路径；
- 跨题可写知识。

Checkpoint 仅用于题内降级和 Debug Journal。solve 结束后内存状态释放。

### 18.4 Trace 投影

公共 Trace 从以下事件投影：

- agent_created；
- task_assigned；
- artifact_published；
- message_delivered；
- evidence_recorded；
- critique_completed；
- repair_committed 或 repair_rolled_back；
- final_audit_completed；
- decision_committed；
- agent_stopped。

Trace 不包含：

- 完整失败 Candidate；
- 原始模型响应；
- 私有推理文本；
- 未授权 Artifact payload；
- 本地绝对路径；
- 原始异常。

---

## 19. Prompt Contract 整改

现有 Prompt Contract 不推倒重写，新增 Agent Runtime 字段：

    task_modes
    accepted_message_types
    readable_artifact_types
    writable_artifact_types
    output_artifact_type
    abstain_policy
    escalation_policy
    protocol_version

### 19.1 RouterPlanner

新增：

- plan 模式；
- 子目标 DAG；
- 方法分配；
- 验证目标；
- 换路条件；
- 不得生成解答正文。

### 19.2 PrimarySolver

新增：

- Task ID 和 Plan Artifact 引用；
- blocked/abstain 的公开控制字段；
- 关键表示和核心不变量；
- 每个公共步骤关联 Claim；
- 禁止请求未经 Host 允许的工具。

### 19.3 AlternativeSolver

新增：

- 明确独立性维度；
- representation、invariant、proof_direction 元数据；
- 重复方法时允许 abstain；
- 禁止引用 Primary Candidate Artifact。

### 19.4 VerifierSkeptic

拆为同一 Contract 的两种 mode：

- cross_exam；
- final_audit。

两个 mode 使用不同 objective、输入 Artifact 和输出 Schema。

### 19.5 RepairAgent

新增：

- critique_id；
- finding_ids；
- authorized_claim_ids；
- abstain；
- no_safe_patch；
- 禁止输出全局改写。

### 19.6 Skill

每个 Skill 逐步增加：

- prerequisites；
- negative_triggers；
- abandon_conditions；
- required_check_capabilities；
- benchmark_case_ids；
- measured_uplift；
- known_failure_modes。

没有实测收益的字段不得伪造，可先为空并保持 Skill 为 candidate。

---

## 20. 文件级改造设计

### 20.1 永不修改

- main.py
- llm_client.py

### 20.2 新增 Agent Runtime

建议新增：

    mathforge/agent_runtime/__init__.py
    mathforge/agent_runtime/protocol.py
    mathforge/agent_runtime/instance.py
    mathforge/agent_runtime/artifact_store.py
    mathforge/agent_runtime/mailbox.py
    mathforge/agent_runtime/coordinator.py

职责：

- protocol.py：AgentDefinition、AgentTask、MessageEnvelope、ArtifactEnvelope；
- instance.py：AgentState、AgentInstance、生命周期状态机；
- artifact_store.py：题内不可变 Artifact、版本、hash、lineage、ACL；
- mailbox.py：题内消息投递、去重、容量和权限；
- coordinator.py：确定性任务循环和 Agent 调度。

### 20.3 修改 Harness

    user_agent.py
    mathforge/config.py
    config/competition.json
    mathforge/runtime.py
    mathforge/harness/provider.py
    mathforge/harness/priority_scheduler.py
    mathforge/harness/allocation.py
    mathforge/harness/session.py
    mathforge/harness/schemas.py
    mathforge/harness/stages.py
    mathforge/harness/state.py

关键变化：

- case concurrency 改为配置驱动的 3；
- Provider 增加共享滚动限流；
- CallAllocationPlan 支持 cross_exam、repair/new_branch、final_audit；
- MathSession 持有 SessionAgentRuntime；
- runtime.py 逐步退化为 facade 和阶段组合；
- 不在共享 Harness 上保存题目级 Agent 状态。

### 20.4 修改角色适配器

    mathforge/agents/router_planner.py
    mathforge/agents/solver.py
    mathforge/agents/verifier.py
    mathforge/agents/repair.py
    mathforge/agents/lemma_curator.py
    mathforge/agents/finalizer.py
    mathforge/agents/prompt_compiler.py
    mathforge/agents/registry.py

角色类继续负责 Prompt、模型响应解析和角色语义；AgentInstance Wrapper 负责身份、Task、Mailbox 和 Artifact。

### 20.5 修改验证

    mathforge/verification/cross_review.py
    mathforge/verification/methods.py
    mathforge/verification/completion.py
    mathforge/verification/arbitration.py
    mathforge/harness/repair.py

建议新增：

    mathforge/verification/conflict_graph.py
    mathforge/verification/audit_policy.py

### 20.6 修改 Context 与 Memory

    mathforge/context/role_views.py
    mathforge/context/snapshots.py
    mathforge/memory/blackboard.py
    mathforge/memory/policies.py

MemoryBlackboard 在迁移后只保留兼容层；新写入逐步转移到 SessionArtifactStore。

### 20.7 修改 Runner 和文档

    scripts/run_case_outputs.py
    scripts/run_benchmark.py
    README.md
    docs/CONFIGURATION_SOURCES.md
    CHANGELOG.md

自定义 Runner 必须从配置读取题目并发最大值，不能继续接受 4。

---

## 21. 分阶段实施计划

每个阶段独立提交，严格按顺序实施。

### Phase M0：治理与基线冻结

目标：

- 固化本方案；
- 解决被删除的 baseline 测试文件；
- 记录当前 HEAD、配置、Prompt、Skill 和数据 hash；
- 新增“真正多 Agent”Definition of Done；
- 明确 LemmaCurator 的 deterministic execution_mode；
- 明确 proof status 与冻结 main 的边界。

不改变：

- 模型调用顺序；
- Candidate 选择；
- Prompt 内容。

验收：

- 干净工作树完整测试通过；
- baseline registry 可复现；
- verify_baseline_files.py 通过。

### Phase M1：并发 3 与 200 RPM

目标：

- case_max_concurrency=3；
- 自定义 Runner 最大并发=3；
- ModelAdmissionController；
- weighted rolling 60-second quota；
- Competition 正式入口按 3 次 transport reservation；
- 模型并发从 16 调整为待校准值，初始建议 6。

新增测试：

- 三题同时运行，第四题等待；
- 66 个 weight=3 调用可派发，第 67 个等待；
- 200 个 weight=1 调用可派发，第 201 个等待；
- 等待超时不消费额度；
- 三个 Case 公平；
- 后台尾调用不突破并发；
- Deadline 内无忙等。

### Phase M2：Proof 与终态语义

目标：

- complete_hard、complete_audited、incomplete、failed；
- incomplete 不再内部映射为普通 primary 完成；
- salvage 明确 degraded；
- Root ReasoningAgent status 和 Trace 一致；
- 记录 main.py 强制 success 的限制。

新增测试：

- proof_full 缺失必要步骤不能 complete；
- Final Audit unknown 不能 complete_audited；
- hard fail 一定 failed；
- best available 保持非空但 Trace degraded；
- Repair 后必须重新 Audit。

### Phase M3：Shadow Artifact 与 Runtime 拆分

目标：

- 新增协议 Schema；
- 每个旧阶段结束后发布 Shadow Artifact；
- Artifact hash 和 lineage 可重放；
- Trace 同时记录旧事件和 Artifact 事件；
- 把 runtime.py 拆成清晰阶段服务；
- 结果、调用数和候选选择保持不变。

验收：

- 行为等价 Golden Test；
- Artifact 序列确定；
- 同输入固定客户端得到相同 Decision；
- Store 不暴露可变内部引用；
- 非法 parent 和跨 Session 引用被拒绝。

### Phase M4：AgentInstance、Task 与 Mailbox

目标：

- 每个 solve 创建题内 AgentRegistry；
- 固定角色实例化；
- 旧角色调用全部通过 AgentTask；
- MessageEnvelope 和 Mailbox；
- AgentState 生命周期；
- Agent 结束后状态冻结。

验收：

- 每次模型调用可追到 agent_id 和 task_id；
- Agent 不能读取未授权 Artifact；
- Alternative 看不到 Primary Candidate；
- Message 发送者和接收者真实；
- solve 结束清空 Mailbox；
- 三题并发无 AgentState 泄漏。

### Phase M5：Planner 和独立 Solver

目标：

- RouterPlanner plan 模式；
- PlanArtifact 和 Task DAG；
- Primary、Alternative 实际使用各自方法分配；
- Alternative 结构独立性门；
- Planner 失败确定性降级。

验收：

- Planner 输出的方法分配真实进入 Solver Task；
- 相同方法重命名无法通过独立性门；
- Alternative Prompt canary 隔离；
- 低风险题不浪费 Planner 调用；
- Planner 非法输出不会破坏主路径。

### Phase M6：Cross Exam、Repair/New Branch、Final Audit

目标：

- VerifierSkeptic cross_exam；
- CritiqueArtifact；
- local repair 与 global new branch 分流；
- Repair Message 闭环；
- VerifierSkeptic final_audit；
- Decision 引用 Audit。

验收：

- Critique 引用真实 Claim；
- 未覆盖目标被显式记录；
- Repair 回应真实 Finding；
- Repair 不得越权修改；
- 全局错误创建新 Candidate，不伪造 Patch；
- Final Audit 观察最终版本；
- 未经 Final Audit 的 Repair 不可提交。

### Phase M7：Prompt、Skill 与 Trace 收敛

目标：

- Prompt Contract 增加协议字段；
- 不同 mode 的输入输出严格区分；
- Skill 增加前提、负触发和退出条件；
- Trace 完全从 Task、Message、Artifact、Evidence 和 Decision 投影；
- 删除已经不再使用的兼容写路径。

验收：

- Prompt manifest 和版本更新；
- 所有角色只看到授权 Artifact；
- Trace 不含 raw response、私有 CoT 或绝对路径；
- 旧 Blackboard 只剩明确兼容用途；
- public result 大小仍满足限制。

### Phase M8：消融、压力测试与配置冻结

目标：

- 三并发、200 RPM 下执行真实 88 题；
- 多次配对消融；
- 更新 evidence registry；
- 只有达到门禁才把 Competition 标记为 validated；
- 没有稳定收益的组件保持关闭。

---

## 22. 测试设计

### 22.1 新增测试文件建议

    tests/test_agent_protocol.py
    tests/test_agent_artifact_store.py
    tests/test_agent_mailbox.py
    tests/test_agent_lifecycle.py
    tests/test_multi_agent_causality.py
    tests/test_agent_observation_isolation.py
    tests/test_agent_runtime_concurrency.py
    tests/test_model_rate_limit.py
    tests/test_six_call_agent_schedule.py
    tests/test_cross_exam_repair_audit.py
    tests/test_proof_terminal_semantics.py
    tests/test_agent_trace_projection.py

### 22.2 协议测试

- Artifact 不可变；
- 相同 payload hash 稳定；
- parent 必须存在；
- 跨 Session 引用失败；
- Agent 只能写允许类型；
- Task 输出类型不符时拒绝；
- Message recipient 不匹配时拒绝；
- 重复 Message 去重；
- 过期 Task 取消；
- Agent 完成后不能重新运行。

### 22.3 因果测试

- PlanArtifact 改变 Solver 方法；
- Candidate Artifact 来自对应 Solver Task；
- Conflict Target 触发 Critique；
- Critique 触发 Repair 或 New Branch；
- Repair Artifact 引用 Finding；
- Audit 引用 Repair 后 Candidate；
- Decision 引用 Audit；
- 删除任一父 Artifact 后验证失败。

### 22.4 独立性测试

- Primary Candidate 插入 canary，Alternative Prompt 不含 canary；
- Alternative 不读取 Primary final_answer；
- 相同方法族、相同 Claim 拓扑被标记 duplicate；
- 表示、核心不变量和证明方向至少一个不同；
- 两个 Solver 异常互不覆盖；
- Alternative 失败不污染 Primary AgentState。

### 22.5 并发测试

- 一个 ReasoningAgent 同时接收 6 个 solve；
- 活跃 Session 最大为 3；
- 每个 Session ID 唯一；
- Artifact、Message、Budget、Evidence 不跨题；
- 模型并发不超过配置；
- RPM 不超过 200；
- 长尾模型线程继续受控；
- 每题 Deadline 从真正进入 case gate 后开始。

### 22.6 故障注入

- Planner 非法 JSON；
- Primary timeout；
- Alternative transport failure；
- Verifier 漏掉 Review Target；
- Repair 越权；
- Repair 修坏正确答案；
- Final Audit timeout；
- Artifact hash 不匹配；
- Mailbox 容量耗尽；
- Rate Limit 等待超过 Deadline；
- Formatter 异常；
- Trace 序列化超限。

每种故障都必须有确定性终态和非空 final_response。

---

## 23. 消融与评测设计

### 23.1 不沿用旧 A0 至 A10 作为有效证据

旧配置可以保留作历史兼容，但当前没有与现提交匹配的重复实测结果。新架构建议建立新的配对消融：

| 组 | 能力 |
|---|---|
| B0 | deterministic route + Primary |
| B1 | B0 + blind Alternative |
| B2 | B1 + Cross Exam |
| B3 | B2 + local Repair/Reverify |
| B4 | B3 + conditional RouterPlanner |
| B5 | B4 + Final Audit |
| B6 | B5 + Agent Task/Artifact Runtime 完整闭环 |

B6 相对 B5 的主要目标是可靠性、可审计性和状态隔离；不要预设它必然直接提高单题准确率。

### 23.2 运行要求

- 同一数据集；
- 同一模型；
- 同一 Prompt/Skill 版本；
- 同一调用预算；
- 同一并发 3；
- 同一 200 RPM；
- 同一 Deadline；
- 每组至少多次重复，或采用严格配对；
- 完整保存 commit/config/model/dataset hash；
- 失败题也必须进入分母。

### 23.3 指标

正确性：

- 全体题准确率；
- 结果覆盖率；
- proof_full 完整率；
- 人工 Proof Audit 抽检；
- 类型感知评分率。

Agent 贡献：

- Alternative 独立有效率；
- Solver 错误相关系数；
- Cross Exam precision/recall；
- Finding 覆盖率；
- Repair 触发率；
- Repair 净修复率；
- Repair 修坏率；
- New Branch 成功率；
- Final Audit 拦截率和误杀率。

运行质量：

- 平均和 P95 调用数；
- P50/P95/最大延迟；
- Provider 成功率；
- Queue wait；
- RPM wait；
- Timeout；
- Fallback；
- Background tail；
- Trace 完整率；
- 题间泄漏事件数。

### 23.4 冻结门

Competition 配置只有同时满足以下条件才能改为 validated：

- 100% 输入均有合法输出；
- 三并发无状态泄漏；
- 任意滚动 60 秒不超过 200 次物理请求；
- 每题逻辑调用不超过 6；
- 没有未审查 Repair 被提交；
- proof 状态语义通过抽检；
- Provider/Queue 失败率达到预先登记门限；
- 当前提交和配置有 active baseline；
- 关键新增 Agent 能力有可重复净收益或明确可靠性收益。

---

## 24. 风险与缓解

### 风险 1：为了 Agent 化而过度增加调用

缓解：

- 角色固定；
- 低风险题跳过 Planner、Alternative 和 Cross Exam；
- LemmaCurator 保持确定性；
- LLMFinalizer 默认关闭；
- 每个新认知步骤必须从六次预算中替换旧调用。

### 风险 2：显式协议增加 Prompt 复杂度

缓解：

- ArtifactEnvelope 由 Host 管理，不要求模型完整输出；
- 模型继续输出现有 Candidate/Finding/Patch payload；
- Agent Adapter 将模型输出封装为 Artifact；
- 协议元数据不重复写入模型上下文。

### 风险 3：同一模型导致角色错误相关

缓解：

- Alternative 输入盲化；
- 方法、表示、不变量、证明方向结构约束；
- 不同温度和不同 Prompt Contract；
- 独立 Final Audit 实例；
- 通过配对错误相关指标验证，而不是只看角色名。

### 风险 4：Mailbox 退化为自由文本辩论

缓解：

- Message 只携带 Artifact 引用和短公共说明；
- 固定消息类型；
- 字符上限；
- 禁止私有 reasoning；
- Host 校验所有消息。

### 风险 5：Artifact 数量和 Trace 过大

缓解：

- Store 保存完整题内 Artifact，公共 Trace 只投影摘要；
- Artifact payload 有类型级大小上限；
- Candidate 失败正文不进入公共 Trace；
- 重复 Evidence 合并；
- Checkpoint 只保存引用。

### 风险 6：严格 proof 门导致大量失败

缓解：

- 区分 complete_hard 和 complete_audited；
- 对 proof_full 建立人工抽检集；
- incomplete 仍返回非空 best available，但不得虚假声明完成；
- 通过消融校准误杀率。

### 风险 7：限流降低吞吐并挤压 Deadline

缓解：

- 题目并发固定为 3；
- 模型并发与 RPM 独立校准；
- Rate 等待纳入 Deadline；
- 优先派发答案形成阶段；
- 可选 Agent Task 在队列压力下提前取消；
- 使用历史调用时长进行压力建模。

---

## 25. 明确不做的事情

本次真正多 Agent 整改不包括：

- 修改 main.py；
- 修改 llm_client.py；
- 新建其他在线模型客户端；
- 读取 API Key；
- 读取客户端私有字段；
- 假设原生工具调用；
- 引入 PlannerAgent 等新固定角色名；
- 引入跨题可写记忆；
- 把私有思维链存入 Artifact；
- 构建分布式消息队列；
- 为每道题强制运行所有 Agent；
- 用角色数量代替准确率证据；
- 在没有实测消融时冻结 Competition 配置。

---

## 26. Definition of Done

### 26.1 架构

- [ ] 每个模型角色在题内具有 agent_id；
- [ ] 每次调用绑定 AgentTask；
- [ ] 每个角色有独立 AgentState；
- [ ] 每个认知输出形成 Artifact；
- [ ] Agent 通信通过 MessageEnvelope；
- [ ] Planner 输出实际决定后续任务；
- [ ] Alternative 保持输入盲化；
- [ ] Critique、Repair、Audit 形成完整 lineage；
- [ ] Host 不生成开放式数学内容；
- [ ] solve 后释放全部题内 Agent 状态。

### 26.2 正确性

- [ ] hard evidence 继续优先于加权分数；
- [ ] Repair 继续 claim-local；
- [ ] Repair 后重新验证；
- [ ] Evidence 下降自动回滚；
- [ ] 全局错误生成新 Candidate；
- [ ] Final Audit 审查最终版本；
- [ ] proof_full 不完整时不会内部宣称完成；
- [ ] Fallback 和 salvage 状态真实。

### 26.3 资源

- [ ] 活跃题目最多 3；
- [ ] 每题逻辑模型调用最多 6；
- [ ] 任意滚动 60 秒物理请求最多 200；
- [ ] 模型并发符合配置；
- [ ] 无未受控后台尾调用；
- [ ] Deadline 和排队时间统一计量。

### 26.4 安全与可观测

- [ ] Agent 只能读取授权 Artifact；
- [ ] 无跨题状态泄漏；
- [ ] Trace 不含私有 CoT；
- [ ] Trace 不含本地绝对路径；
- [ ] Trace 不含原始异常；
- [ ] 每个最终结论可追到 Candidate、Evidence、Audit 和 Agent；
- [ ] 配置、Prompt、Skill、模型、数据和代码 hash 可复现。

### 26.5 评测

- [ ] 干净工作树全部测试通过；
- [ ] 88 题全部落盘；
- [ ] 当前提交有有效 baseline；
- [ ] B0 至 B6 配对消融完成；
- [ ] 关键 Agent 能力存在稳定净收益；
- [ ] Competition 状态只有在达到门禁后改为 validated。

---

## 27. 最终建议

真正多 Agent 改造应采用“协议和因果链优先、角色数量克制”的路线。

最高优先级顺序：

1. 先闭合题目并发 3 和 200 次/分钟；
2. 修复 proof 与终态语义；
3. 将现有结构化对象包装为 Shadow Artifact；
4. 拆分过长 Runtime；
5. 引入题内 AgentInstance、Task 和 Mailbox；
6. 将现有固定角色迁移到 Agent Runtime；
7. 建立 Cross Exam、Repair/New Branch、Final Audit 闭环；
8. 完成三并发真实消融后再冻结配置。

不建议从大规模重命名和目录重写开始。现有 Candidate、Evidence、Proof、Repair、Context 和 Prompt Contract 已经是高价值基础，应在其外建立真正的 Agent 生命周期和通信协议，而不是重写数学推理内核。

完成 M0 至 M6 后，项目可以合理称为：

> 由确定性 Host Runtime 约束、具有独立题内身份和状态、通过显式任务、消息和不可变工件协作，并以证据和最终审计闭环决策的多 Agent 数学推理系统。

完成 M8 且取得有效配对证据后，才能进一步声称：

> 真正多 Agent 架构已经在并发 3、每题六次调用和 200 次/分钟约束下，为当前 Math-Agent 带来可重复的准确率或可靠性净收益。
