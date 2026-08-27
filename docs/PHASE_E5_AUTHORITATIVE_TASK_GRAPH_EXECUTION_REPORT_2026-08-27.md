# E5 Authoritative TaskGraph / Scheduler Execution Report

日期：2026-08-27
阶段：E5（Authoritative TaskGraph / Scheduler）
仓库：`math_agent`

## 目标与范围

本阶段按实施计划完成 E5-T01 至 E5-T08。目标是让 TaskGraph 成为模型认知工作
的唯一生产调度权威，保证每个模型调用都有可追踪的任务身份，并在重规划、取消、
超时和动态扩图时阻止旧结果污染当前会话。

## 已实施内容

1. `mathforge/runtime_flows/scheduler_flow.py`
   - 新增 `GraphState`、`GraphExecutor`、`GraphExpansion`、`PublishFence`、
     `SchedulerTaskBinding`、`NodeDispatch` 与 `NodeOutcome`。
   - 支持 `pending/ready/running/completed/failed/skipped/cancelled` 等终态，
     依赖检查、波次执行、动态扩图、plan version 取消和未启动节点收束。
   - 每个波次产生 generation 与 wave generation；不满足栅栏的晚到结果只进入
     脱敏 telemetry，不写入值表或下游状态。
   - `SchedulerFlow` 保留兼容入口，但在严格竞争配置下其未绑定 fallback 会被
     Provider 拒绝，不能形成模型调用旁路。
2. `mathforge/harness/provider.py`、`mathforge/harness/budget.py`、
   `mathforge/config.py` 与三个配置文件
   - 新增 `require_scheduler_binding` 配置（competition=true，safe/balanced=false）。
   - Provider 在调用客户端前校验 `scheduler_task_id/plan_version/agent_id` 绑定，
     并把图身份、波次和绑定状态写入模型调用分配记录。
3. `mathforge/runtime.py`
   - Router、Primary/Alternative Solver progress 和 Candidate synthesis 迁移到
     GraphExecutor wave；动态的 lemma/tool/replan 等 action 通过 GraphExpansion
     物化为节点。
   - 图节点状态、准入、裁剪、完成和重规划事件均从真实 `NodeExecution` 生成。
   - 旧的 verification/finalization 工作仍通过单节点 GraphExecutor 包装，未在
     本阶段进行整段迁移。
4. `mathforge/agent_runtime/runtime.py`、`mathforge/agents/solver.py`
   - 建立 replan participant barrier。Host 只发布新 plan 和参与者集合，不代替
     Agent ACK；ACK 必须来自真实 Solver Turn 的公开 marker，且版本/决策必须匹配。
   - paused branch 的旧 generation 被取消，兼容分支从 Router 边界重新扩展。
5. `SchedulerFlow.admit_closure` 与 `critical_path_admitted`
   - 以任务实际 stage policy 的 P95 及配置的 model-start/finalization reserve
     检查剩余模型窗口；repair closure 使用统一的原子闭包准入接口。

## E5 不变量测试

新增 `tests/test_phase_e5_authoritative_task_graph.py`，覆盖：

- 依赖波次、Primary/Alternative 并发、任务绑定与 state 隔离；
- GraphExpansion 与依赖违规 fail-closed；
- 未执行节点的终态收束；
- PublishFence 对伪造 generation/metadata 和晚到结果的拒绝；
- plan version 更新时取消不兼容任务且不产生下游值；
- strict Provider 缺失绑定拒绝及旧 SchedulerFlow fallback 行为；
- critical path P95、finalize reserve 与 model-start margin 的严格准入；
- replan ACK 仅由真实 Solver Turn 记录，且所有 ACK 版本匹配。

同时修复了 E4 截断恢复在状态版本回滚后的 progress 节点 ID 重复问题，确保恢复
后会继续执行新的图节点而不是提前进入 Candidate synthesis。

## 本地验证证据（诊断性）

以下结果来自仓库内的单元测试、Fake/Scripted Client 和静态校验，仅证明工程不变量；
它们不是官方平台数学正确率或真实模型证据：

- `pytest -q tests/test_phase_e5_authoritative_task_graph.py`：10 passed；
- E5 相关回归集合：61 passed；
- 修复后的 E1 stale-plan 与 E4 truncation 回归：2 passed；
- 最近一次完整回归：970 passed；
- 强制校验命令：`python -m compileall .`、`pytest -q`、
  `python scripts/verify_baseline_files.py`；
- 治理校验：`verify_content_reviews.py`、`verify_build_provenance.py`、
  `validate_submission.py` 与 `validate_release.py --strict` 在报告提交前重新执行。

## 外部证据与发布状态

本阶段没有运行真实官方 FULL competition run，也没有宣称真实模型准确率、P95、
成本或数学正确性已达标。当前 release governance 继续保持
`candidate-unvalidated`，content review 继续 `pending-human`；真实模型时间线、
逐案输出、proof double review、C0-C7 ablation 和 provenance freeze 仍是后续阶段的
必需证据。任何 Fake/Scripted Client、旧日志或本地模拟均不升级为发布基线。

## 变更与指纹

本阶段使用一个独立提交；提交哈希、配置/Prompt/Skill/source 指纹及最终测试终端
输出在提交后写入本报告对应的治理记录。`AGENTS.md` 的已有用户修改未纳入本阶段
提交。
