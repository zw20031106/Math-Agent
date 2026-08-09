# Math-Agent Phase 9 Scheduler / Runtime 执行报告

## 1. 范围与结论

本阶段按 2026-08-09 最终实施计划完成以下七项工作：

1. TaskNode DAG；
2. critical path P95；
3. parallel solver wave；
4. parallel review wave；
5. atomic closure admission；
6. runtime phase extraction；
7. call accounting by role/action/task。

实现不修改 `main.py` 或 `llm_client.py`，不改变根目录
`ReasoningAgent.solve(problem, metadata)` 的公开契约。

## 2. TaskNode DAG 与关键路径

`mathforge.runtime_flows.scheduler_flow` 新增只读 TaskNode、TaskGraph 和
SchedulerFlow 服务。TaskNode 显式携带：

```text
role / action / task_id / dependencies / priority
expected_p50 / expected_p95 / token_cap / closure_value
optional / parallel_group
```

TaskGraph 在构造时拒绝重复节点、未知依赖、自依赖和有向环。关键路径 P95
使用 DAG 最长路径计算，因此同一 solver/review parallel group 只计入该 wave
的最长分支，不把并行工作错误相加。

生产 Runtime 在 EffectiveExecutionPlan 分发后构造题级 Scheduler DAG，并在
内部 Trace 记录 graph、节点、关键路径 P95、发布阈值和阈值判定。DAG 包含
Router、Primary/Alternative、双向 Review、Verifier、Repair、Reverify、Final
Audit 和 deterministic finalization 的依赖关系。

## 3. 并行 wave

自主长程 Solver 主路径的最终 Candidate synthesis 由受限 parallel solver
wave 执行；PrimarySolver 与 AlternativeSolver 保持独立上下文、独立 Agent
身份和单 Agent inflight=1。双向 Solver Review 同样在两个目标 Candidate
均可用后作为 parallel review wave 执行。

每个 wave 的局部 worker 数最多为 2；所有实际模型调用仍先经过全局
ModelCallGate，因此不能绕过：

```text
case concurrency = 3
model concurrency <= 6
RPM <= 200
same Agent inflight <= 1
```

## 4. 原子闭包准入

Repair → Reverify 在开始前形成一个不可拆分的 ClosureAdmission。该准入一次
检查完整节点集合、调用容量和基于 stage P95 的剩余时间。任何
`solver_progress` 等 speculative action 混入 closure 都会以
`speculative_action_in_closure` 拒绝；调用或时间只能覆盖部分闭包时也不会
启动事务。Transaction identity 由公开节点和预算快照确定性生成，服务不保存
跨题可变状态。

## 5. 调用核算

Provider 为每条物理调用记录补充：

```text
agent_role
action_category
task_id
scheduler_task_id
status
dispatched
```

CallLedger 提供按 role/action/task/status 的确定性聚合，并区分 recorded calls
与真正 dispatched calls，避免把未派发的排队拒绝误记为有效模型调用。

## 6. 验收证据

专项测试覆盖：

- 并行 wave 的真实重叠和 worker 上限；
- DAG 未知依赖与环拒绝；
- 并行关键路径不重复计时；
- speculative work 不能进入 closure；
- 不足以覆盖 Repair + Reverify 时原子拒绝；
- role/action/task/status 调用核算；
- competition 配置保持 3 case、6 model、200 RPM、单 Agent inflight 1。

阶段提交前按仓库治理要求执行：

```text
python -m compileall .
pytest -q
python scripts/verify_baseline_files.py
python scripts/verify_content_reviews.py
python scripts/verify_build_provenance.py
python scripts/validate_submission.py
```

## 7. 边界

本阶段的 P95 是冻结的健康服务初始估计，不是新一轮真实题集统计。是否满足
最终发布延迟阈值仍须由 Phase 11 的 C0-C7 + FULL 基准证据验证；在此之前
competition status 继续保持 `candidate-unvalidated`。
