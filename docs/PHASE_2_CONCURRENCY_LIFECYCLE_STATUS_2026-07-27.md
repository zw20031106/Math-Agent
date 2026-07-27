# Phase 2 并发、超时与资源生命周期实施状态

日期：2026-07-27  
范围：P2-01 至 P2-06

## 结论

Phase 2 已完成。正式共享 `ReasoningAgent` 实例仍使用 Competition
`model_max_concurrency=1`，本阶段没有在缺少真实 P95 数据时提高并发。

## 已实施

1. Case、模型排队、模型执行和确定性终结使用相互独立的预算字段。
2. semaphore acquire 使用
   `min(stage timeout, queue budget, remaining before terminal reserve)`。
3. stage timeout 从开始排队时计时；每次调用分别记录 queue、execution 和
   total elapsed。
4. 失败码区分 `model_concurrency_wait_exceeded`、
   `model_response_deadline_exceeded` 和 `model_provider_circuit_open`。
5. timed-out Python thread 被明确记录为 background tail，不宣称强制取消。
   active tail 达到配置上限后 provider circuit-open，后续请求不再创建线程。
6. tail 全部完成后 circuit 才确定性恢复；晚到登记只保留 call index、完成状态
   和耗时，并受固定集合上限约束。
7. Terminalizer 开始时冻结 Session；返回前冻结 Budget 和 Trace。晚到回调不再
   持有或修改每题 Budget、Session、Candidate、Evidence 或 Proof Obligation。
8. Competition deadline profile 为：

   - outer platform limit：1,200 秒；
   - Harness hard deadline：1,150 秒；
   - deterministic finalize reserve：50 秒；
   - runner persistence reserve：50 秒；
   - model queue budget：15 秒；
   - model start margin：100 秒。

## 验收覆盖

- queue wait 超预算快速失败且 slot 可复用；
- 角色 timeout 不因排队额外扩展；
- queue/execution/total metrics 可一致核对；
- tail 上限、circuit trip、fast failure 和 reset 可复现；
- 100 次 follow-up 请求不扩张 background thread；
- tail 未完成时 Session weakref 已可回收；
- Session、Budget、Trace 终态后拒绝内部写入；
- 2、4、8 个 runner thread 共享 Harness 时 Session 隔离、模型并发有界；
- 所有并发结果完成 JSON round-trip；
- deadline 边界使用 fake clock，不依赖分钟级 sleep。

## 明确限制

Python thread 无法安全强杀。若官方 Client 永不返回，占用的 daemon thread
会存活到进程退出；本实现通过 semaphore、tail limit 和 circuit-open 将数量
限制为配置上限，并阻止其污染已返回结果。

Competition 的最终并发值和 deadline 分位数仍须在 Phase 6 使用官方模型实测
P50/P95 后确认。
