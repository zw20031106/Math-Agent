# MathForge Phase 2 执行报告

日期：2026-07-30  
阶段：并发、公平和 Deadline  
结论：工程实现与离线验收通过；真实 Intern 服务容量标定待使用官方注入客户端采样

## 1. 执行范围

本阶段严格对应审查计划 Phase 2：

1. 保持物理模型峰值并发不超过 4，引入阶段 aging 和 case
   round-robin；
2. 将固定队列等待改为“剩余 Deadline - 阶段 p95”的可行性预算；
3. 防止 Verifier 在尚有 Primary/Alternative 等待时抢占答案形成资源；
4. 为 Repair/Reverify 增加调用次数与剩余时间的双重原子门；
5. 冻结并发 1/2/4 的真实容量判定阈值和可执行比较工具。

没有修改不可变文件 `main.py`、`llm_client.py`，没有创建新模型客户端，
也没有读取 API Key 或模型环境变量。

## 2. 已实施内容

### 2.1 公平并发调度

- `PriorityCallScheduler` 继续以一个共享容量控制物理调用峰值；
- 每个 `solve()` 创建的 session 将自己的匿名 case 标识绑定到
  `CallBudget`，只用于进程内公平调度，不进入公开路径或模型 Prompt；
- 同一阶段内按 case 的最近服务次序轮转，避免一个题连续占用全部槽位；
- Primary/Router 保持最高优先级，Alternative 在 Verifier 之前；
- 等待阶段每 10 秒获得一次 aging，最多提升两级，避免低优先级永久饥饿；
- 调度快照新增按阶段排队数、最老等待时间和累计 admission 数。

### 2.2 Deadline 可行性队列预算

为 Router、Primary、Alternative、Verifier、Repair、Lemma 和 Finalizer
冻结第一版健康服务 p95 估计。每次调用的有效队列预算按以下原则计算：

```text
effective_queue =
  min(configured_queue_cap,
      0.4 * stage_p95,
      max(0, remaining_model_time - stage_p95))
```

因此，配置中的 15 秒只作为上限，不再无条件等待 15 秒；当剩余时间不足以
覆盖阶段 p95 时，只允许无等待的即时槽位获取。每次调用记录以下可解释字段：

- `stage_p95_seconds`
- `effective_queue_budget_seconds`
- `configured_output_tokens`
- `stage_output_cap_tokens`
- 实际上下文分配和输出 token 上限

### 2.3 Repair/Reverify 时间原子门

原实现只检查 Repair 和 Verifier 是否各剩余一次调用。现在同时计算：

```text
repair p95 + repair queue reserve
+ verifier p95 + verifier queue reserve
```

只有调用预算、阶段预算、探索窗口和剩余模型时间同时满足时，才启动这对
模型调用。Trace 的 `repair_actionability_gate` 新增：

- `atomic_time_pair_available`
- `required_pair_seconds`
- `remaining_model_seconds`

时间不足只会跳过可选修复，不会淘汰已经存在的安全候选。

### 2.4 真实容量验收工具

新增 `scripts/compare_capacity_profiles.py`，读取并发 1、2、4 的真实运行画像，
执行预先冻结的验收门：

- 物理峰值并发不超过 4；
- 健康服务候选形成率不低于 95%；
- 并发 4 相比并发 1 的答案产出率下降不超过 5%；
- 并发 4 相比并发 1 的答案正确率下降不超过 5%。

该脚本只分析持久化画像，不构造外部客户端，符合官方注入客户端边界。

## 3. 验收结果

| 验收项 | 结果 | 证据 |
|---|---:|---|
| 物理峰值并发 ≤ 4 | 通过 | 40 个健康并发请求压力测试，观测峰值 ≤ 4 |
| 健康服务计划候选形成率 ≥ 95% | 离线通过 | 健康模拟服务 40/40 形成，100% |
| case round-robin | 通过 | 同阶段 `case-a, case-a, case-b` 入队后按 `a,b,a` 服务 |
| Verifier 不抢占未形成答案分支 | 通过 | 早到 Verifier 仍在 Alternative 之后 admission |
| aging 防永久饥饿 | 通过 | 等待超过两档后可与答案阶段竞争 |
| 动态队列可行性预算 | 通过 | 覆盖宽松、临界和不足 p95 三类 Deadline |
| Repair/Reverify 时间原子门 | 通过 | 低于 266 秒拒绝、达到 266 秒允许（60 秒队列上限测试画像） |
| 900 秒内完成且无新无界任务 | 工程门通过 | 保留 850 秒内部硬截止和有界 tail；本阶段未新增后台任务 |
| 并发 1/2/4 真实服务退化 | 待真实采样 | 比较器和 5% 冻结容差已就绪，未伪造在线结果 |

## 4. 测试与校验

```text
pytest -q
582 passed in 140.87s

python -m compileall .
passed

python scripts/verify_baseline_files.py
Official immutable baseline files verified.

python scripts/validate_submission.py
Submission validation passed.

python scripts/scan_secrets.py .
Secret pattern scan passed.
```

专项 Phase 2 回归覆盖 8 个新增不变量；与既有 concurrency lifecycle、
budget、orchestration、deadline、repair 和 proof 测试组合执行 61 项全部通过。

## 5. 未伪造的外部验收项

真实 Intern 服务的容量和正确率取决于官方注入客户端、服务时延与测试集答案。
本阶段没有收到执行真实模型测试的请求，因此未使用历史 API Key，也没有把模拟
结果标记为真实标定。取得并发 1/2/4 的三个 `profile_live_runs.py` 输出后可运行：

```powershell
python scripts/compare_capacity_profiles.py `
  --concurrency-1 <profile-c1.json> `
  --concurrency-2 <profile-c2.json> `
  --concurrency-4 <profile-c4.json> `
  --output <phase2-capacity-result.json>
```

只有该输出的 `passed` 为 `true`，Phase 2 的“真实容量验收门”才可标记为完成。
