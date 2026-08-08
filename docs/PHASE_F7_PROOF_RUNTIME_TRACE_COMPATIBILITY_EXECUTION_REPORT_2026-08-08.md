# Phase F7 Proof、Runtime、Trace 与兼容清理实施报告

## 结论

Phase F7 已完成。Competition 路径现在只使用统一题级资源治理，不再通过
`CallAllocationPlan` 为 Router、Solver、Verifier 或 Repair 切分固定调用份额，也不再
预设 Solver 推理轮数。题级模型调用硬上限仍为 48 次，探索截止点为第 40 次，最后
8 次保留给验证、修复、复核和最终审计；全局并发题数仍为 3，Provider 仍执行
200 RPM 准入。

正式入口 `main.py` 与 `llm_client.py` 保持冻结且未修改。

## 1. Proof 四态语义

最终证明状态只允许以下四种：

- `complete_hard`：必要证明义务均有可接受的硬证据，且不存在硬失败；
- `complete_audited`：独立 Final Audit 与 Candidate ID/版本严格匹配，覆盖全部必要
  义务且没有开放 Finding；
- `incomplete`：存在可返回的最佳候选，但证明形状、证据覆盖或最终审计尚不完整；
- `failed`：出现可致命硬失败，或匹配版本的 Final Audit 明确失败。

Peer Review、Rebuttal 和 Verifier 意见属于软证据，不能单独把 Candidate 提升为完成。
`proof_full` 至少需要非空结论和两条非空公开证明步骤。Repair 产生新 Candidate 版本后，
旧 Audit 自动失效；只有对新版本执行并通过 Final Audit 才能恢复完成状态。

## 2. Runtime 拆分

`mathforge/runtime.py` 继续作为兼容 facade 和现有阶段编排入口，新增
`mathforge/runtime_flows/` 承担独立、可测试的确定性责任：

- `session_flow.py`：保证 `final_response` 非空且 `trace` 为列表；
- `agent_flow.py`：从 Agent Protocol 快照投影公开生命周期和通信事件；
- `final_flow.py`：合并硬证据、证明义务、Repair 版本和 Final Audit，生成唯一最终
  Proof 状态。

这三项服务由正式 `solve()` 路径直接调用，不是旁路或仅测试实现。后续阶段如继续
拆分较大的 peer-review、verification closure 方法，只能做结构性迁移，不得改变 F7
已经冻结的事件和证明状态契约。

## 3. 删除的旧控制路径

- 删除 `mathforge/harness/allocation.py` 及 `CallAllocationPlan`；
- 删除 `CallBudget.set_allocation_plan()`、阶段配额及旧 `legacy_staged` 策略；
- 删除 `LongHorizonPlan`、`LongHorizonPolicy` 和 `planned_rounds` 固定循环；
- 删除 runtime 对旧 Blackboard 的全部写入；角色上下文改为读取会话内公开元数据；
- 删除旧 `call_allocation_*` Trace 名称，改为 `resource_plan_created` 和
  `resource_plan_updated`；
- 删除只验证固定轮次/旧阶段分配的测试，改为验证自主 Action、统一资源准入和闭环
  预留。

ResourceGovernor 根据已经消耗的 Router、Primary 和 Alternative 调用计算未来可启动
动作；Repair 与其 Reverification 作为原子闭环预留，避免只启动 Repair 却没有资源
复核。

## 4. Agent 事件与公开 Trace

Judge Trace 现在从每题 Agent Protocol 投影以下公开事件：

- `agent_created`、`task_assigned`；
- `model_turn_started`、`model_turn_completed`；
- `artifact_published`；
- `message_sent`、`message_delivered`；
- `peer_review_completed`、`rebuttal_completed`；
- `verifier_completed`；
- `repair_committed`、`repair_rolled_back`；
- `final_audit_completed`、`decision_committed`；
- `agent_stopped`。

投影仅携带 ID、类型、状态、父子关系和公开摘要，不投影 Artifact payload、raw model
response、私有推理、绝对路径或原始异常。紧凑 Trace 仍优先保留解答、关键验证、
仲裁和终态；生命周期事件按有界最新样本进入公开结果。

## 5. Formal entry 兼容边界

`ReasoningAgent.solve(problem, metadata)` 仍返回 JSON 可序列化 mapping，且保证非空
`final_response` 和 list-valued `trace`。Trace 的 `formal_entry_compatibility` 明确记录：

- `main.py`、`llm_client.py` 是冻结基线；
- Harness 的四态 Proof 状态在 Trace 内表达；
- 官方 `main.py` 的顶层 `status` 仍由冻结入口包装逻辑拥有，不能在本阶段越权修改。

因此内部证明状态不会被伪装成官方入口顶层状态，两层边界可以被测评日志直接区分。

## 6. 验收覆盖

F7 回归测试覆盖：

1. `proof_full` 缺少公开步骤时保持 `incomplete`；
2. Peer Review 全通过但没有 Final Audit 时仍为 `incomplete`；
3. 硬失败始终得到 `failed`；
4. `complete_audited` 必须覆盖所有必要证明义务；
5. Repair 后必须存在 Candidate 版本匹配的 Final Audit；
6. Agent 生命周期、通信和 Repair commit/rollback 均可投影；
7. Trace 不泄露 Artifact payload；
8. 固定轮次和阶段分配实现已经删除；
9. 正式输出始终满足非空答案和列表 Trace；
10. 并发会话的公开元数据保持隔离。

提交前执行以下门禁：

```text
python -m compileall .
pytest -q
python scripts/verify_baseline_files.py
python scripts/validate_submission.py
```

F7 完成后，F8 才负责真实 88 题运行、C0-C7 消融、并发 3/200 RPM 实测和最终配置
冻结；F7 不声明这些外部实测结果已经完成。
