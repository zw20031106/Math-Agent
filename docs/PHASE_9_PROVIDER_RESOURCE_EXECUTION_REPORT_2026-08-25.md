# Math-Agent Phase 9：Provider、超时与资源治理执行报告

## 1. 执行结论

Phase 9 已按 2026-08-24 整改计划落地。重点修复了“阶段超时后继续等待整道题剩余时间”这一错误前提，并把题级取消、Provider 物理调用、调度 wave 和迟到结果的生命周期连成一个可验证闭环。

本阶段不修改 `main.py` 或 `llm_client.py`，不改变 `ReasoningAgent.solve(problem, metadata)` 的公开契约。competition 有效资源边界为：题目并发 3、模型并发 6、200 RPM、单 Agent 同时最多 1 个调用、每次物理调用按最多 3 次尝试加权预留。

## 2. Provider 与超时

### 2.1 阶段超时是真实返回边界

`ModelCallGate` 在 `stage_timeout_seconds` 到期后只等待配置的
`provider_tail_grace_seconds=0.1` 秒，不再使用
`deadline.remaining_for_model_call()` 作为隐式 late wait。因而 Router 配置
180 秒时，调用者至多看到 180 秒加 100 ms 的边界竞争，而不会被题级硬截止
前的剩余时间吞掉。

边界后的物理线程仍必须完成或失败，但它只能作为 per-case tail 被记录，不能
把结果重新写入已经结束的 solve。

### 2.2 Tail 隔离与上限

迟到 registry 按 `case_id` 隔离，条目数受 `late_result_registry_max_entries`
限制；competition 的同时活动 tail 上限收紧为 6，与模型并发一致。完成题目时
Provider 只在无活动 tail 时释放该 case 的健康记录，避免晚到回调污染下一题。

## 3. 调度取消与 generation fence

所有生产 Solver exploration、candidate synthesis 和 peer-review wave 都把
本题 `CancellationToken` 传入 `SchedulerFlow`。wave 超时会：

1. 取消本题 token；
2. 对仍在运行/排队的 task 提升 generation，立即使旧 generation 失效；
3. 返回 `accepted=false` 的超时/取消结果；
4. `ThreadPoolExecutor.shutdown(wait=False, cancel_futures=True)` 进入
   `finally`。

因此，迟到 worker 即使在 Provider 层完成，也不能提交新的 Candidate、Review
或状态迁移。

## 4. 资源释放

Provider 的 admission lease 在无 deadline、dispatch 失败、commit 失败、线程
创建失败和 worker 执行路径均有释放保障；worker 本身在 `finally` 中释放调度
槽、Agent inflight 槽和 RPM reservation。tail 回调在 session 已冻结时也会被
安全丢弃，而不再反向修改公开结果。

## 5. Stage P95 校准

使用仓库外部已归档的 88 题 canary 汇总作为校准证据：Primary 执行耗时 P95
为 147.18 秒，Alternative 为 139.37 秒，Verifier 为 150.61 秒。标准/紧凑
Solver 取 180 秒的约 20% 抖动余量，Verifier 取同一 180 秒包络，Repair 在
只有一个可用样本（72.08 秒）的情况下暂取 90 秒。Proof 没有足够同类型样本，
因此保留 240 秒的安全预留，不使用 Router 或普通 Solver 的分布替代 Proof
分布。该状态仍是 `candidate-unvalidated`，Phase 11 需要用当前 Provider、
三题并发和当前输出 cap 做正式 canary 再冻结。

## 6. 验收证据

专项回归覆盖：

- 阶段超时不再等待题级剩余时间；
- late tail 的 case 隔离和有界 registry；
- wave 超时的 token 取消与 generation fence；
- executor、Provider lease 和物理 tail 的释放路径；
- 3/6/200/3 的 competition 资源边界；
- 32K 标准、40K Proof 输出 cap 保持；
- P95 校准对队列预算与原子闭包预留的影响。

提交前必须执行：

```text
python -m compileall .
pytest -q
python scripts/verify_baseline_files.py
python scripts/verify_content_reviews.py
python scripts/verify_build_provenance.py
python scripts/validate_submission.py
```

只有 Phase 11 的真实 FULL/C0–C7、invalid/timeout/P95/成本门和证明人工双评
通过后，competition 才能从 `candidate-unvalidated` 改为 `frozen`。
