# Phase F1 资源治理与题级 Call Budget 实施报告

日期：2026-08-07  
依据：`MATH_AGENT_TRUE_MULTI_AGENT_FINAL_ARCHITECTURE_AND_IMPLEMENTATION_PLAN_2026-08-02.md` 第 28 节

## 结论

Phase F1 已完成资源底座改造，但本阶段不宣称项目已经完成“真正多 Agent”。F2 及后续阶段仍需实现 AgentDefinition、Artifact、Mailbox、强制 Router、自主循环、候选交叉审阅与最终闭环。

## 已实现范围

- `case_max_concurrency` 由 Competition 配置驱动并固定上限为 3；Runner 默认值和可接受最大值同步为 3。
- Provider 统一通过 `ModelAdmissionController`，同时治理模型并发、同 Agent 单 in-flight 和加权滚动 RPM。
- Competition 使用 `model_max_concurrency=6`、`model_requests_per_minute=200` 和 `transport_attempt_reservation=3`；未派发的预留可退款，已派发调用不退款。
- 每题使用 `SessionCallBudget` 的 48 次逻辑调用硬上限；16/28/40 为软检查点，第 40 次之后拒绝新的投机探索，并保留 8 次给 Candidate 收敛、Verifier、Repair、Replan、Final Audit 或最终化。
- adaptive 路径不安装或执行 `CallAllocationPlan` 的阶段固定配额；旧 profile 继续走 legacy 路径，避免破坏历史消融契约。
- 新增 `CallLedger`，记录逻辑调用序号、是否派发、Turn 类型、请求/实际输出上限、阶段/实际超时、传输尝试、完成状态、后台尾状态和停止原因。
- StageExecutionPolicy 按 Router、Progress、Standard Candidate、Proof Candidate、Lemma、Peer Review、Verifier、Repair、Finalizer 区分 Token、阶段执行超时和安全最小起始窗口。
- 排队时间只消耗题级 Deadline，不从已准入 Turn 的阶段执行超时中扣除；剩余安全窗口不足时不会派发长 Proof Turn。
- 超时调用登记为 background tail，并继续占用物理并发和对应 Agent 的 in-flight 名额，直到底层调用真实返回；迟到结果不会写回已返回 Session。

## 核心配置

| 项目 | Competition 值 |
|---|---:|
| 题目并发 | 3 |
| 模型物理并发 | 6 |
| 全局 RPM | 200 |
| 单次逻辑调用传输预留权重 | 3 |
| 每题逻辑调用硬上限 | 48 |
| 软检查点 | 16 / 28 / 40 |
| 收敛预留 | 8 |
| 同 Agent 最大在途调用 | 1 |

## 验证覆盖

- 三题同时进入、第四题等待的 Case Gate 契约。
- weight=3 时前 66 次可预留且第 67 次等待；weight=1 时前 200 次可预留且第 201 次等待。
- RPM 滚动窗口释放和未派发退款。
- 超过旧六次阈值的长程调用不会被旧上限终止；第 48 次可用，第 49 次被原子拒绝。
- 64 个并发预算请求中恰有 48 个成功，不发生计数越界。
- 第 40 次后投机分支被拒绝，8 次 closure 调用仍可继续。
- Standard/Proof Candidate 分别使用 8192/12288 Token 与 240/270 秒策略；Router 使用独立 120 秒策略。
- 排队等待与阶段执行计时分离。
- 同 Agent 的 background tail 未结束时不能原样立即重发；不同 Agent 可在全局并发允许时并行。
- Judge Trace 暴露资源决策字段，但不暴露私有推理、绝对路径或原始异常。

## 后续阶段边界

F1 只提供可安全承载多 Agent 的资源治理层。当前 Router 仍是既有路由协议，Agent 间的 typed Mailbox、Artifact 版本、可恢复生命周期和自主调度属于 F2–F7，不在本阶段提前实现。
