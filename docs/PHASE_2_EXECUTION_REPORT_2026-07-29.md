# Phase 2 Transport、优先级调度与动态预算内核执行报告

> 日期：2026-07-29  
> 阶段结论：代码与离线门禁完成；真实 Intern-S 4 题 canary 未在本阶段调用  
> 冻结文件：`main.py`、`llm_client.py` 未修改

## 1. 完成范围

本阶段按照 0729 融合实施方案完成以下整改：

1. 正式 Client 保持单次传输尝试，本地 `FastRetryClient` 默认也固定为一次；
2. Primary 获得最多一次 Harness 级恢复机会；
3. 恢复机会可用于可重试 Transport 故障，或 Candidate 契约修正，但不会叠加；
4. 身份/权限、读取超时、响应形状等非恢复类错误不盲目重试；
5. 新增全局模型调用优先调度器，优先级为：
   `Primary > Verifier > Repair > Alternative > Lemma > Router > Finalizer`；
6. 同优先级按进入队列顺序处理，避免题间长期饥饿；
7. 超时后的后台模型线程在真实返回前继续占用物理 permit；
8. Competition 模型物理并发上限保持为 4；
9. 未获得 permit 的请求退还调用配额，并在调用记录中标记
   `dispatched=false`；
10. 模型调用记录区分可见调用、真实派发、传输尝试和响应契约拒绝；
11. Competition 默认关闭 LLM Router，使用确定性 Router；
12. 新增 `CallBudgetSnapshot` 与 `FanoutDecision` 基础数据结构；
13. Public Trace 的 Transport 汇总增加 `actual_dispatches` 和安全根因错误码；
14. 控制台输出改为非关键路径，输出流故障不影响已经写入的单题 JSON；
15. L0/L1/L2 preflight 仍保持每次运行一次，不逐题重复。

## 2. 关键行为

### 2.1 Primary 恢复边界

- `rate_limited`、`provider_5xx`、`network_connect_failure`：
  Primary 可使用一次保留调用；
- Candidate Schema 拒绝：可使用一次零温契约修正；
- 两类恢复共享同一个两次 Candidate envelope；
- `auth_or_permission_failure` 等非恢复错误只派发一次；
- 第二次调用失败后保留第一失败的安全分类，不暴露原始异常或响应。

### 2.2 物理并发

`PriorityCallScheduler` 管理真正的在途模型调用。模型线程超时后，调用方可以结束，
但 permit 直到该线程真实返回时才释放。因此后台 tail 不能造成物理调用数突破 4。

### 2.3 预算记账

预算先保留、派发时再标记 `dispatched=true`。排队超时、Circuit 拒绝、Deadline
准入拒绝等未派发请求会退还阶段配额。Trace 同时报告尝试记录数与
`actual_dispatches`，不再把排队拒绝误算成真实模型调用。

## 3. 主要文件

| 文件 | 结果 |
|---|---|
| `mathforge/harness/priority_scheduler.py` | 新增阶段优先、同级 FIFO 的全局物理调用调度器 |
| `mathforge/harness/provider.py` | 真实派发回调、后台 tail 保留 permit、调度健康快照 |
| `mathforge/harness/budget.py` | `dispatched` 记账、预算快照 |
| `mathforge/harness/allocation.py` | `CallBudgetSnapshot`、`FanoutDecision` |
| `mathforge/agents/solver.py` | Primary 单次 Harness 恢复 envelope |
| `mathforge/harness/trace_summary.py` | 真实派发数与根因错误码汇总 |
| `scripts/run_case_outputs.py` | Local retry=1、安全控制台输出 |
| `config/competition.json` | 确定性 Router 为 Competition 默认路径 |

## 4. 验收证据

- Primary 第一次 503、第二次成功：通过；
- Primary 身份错误不重试：通过；
- Candidate 契约修正与 Transport 恢复不叠加：通过；
- 未派发请求不消耗调用预算：通过；
- Alternative 先排队时，后到 Primary 仍优先：通过；
- 8 个并发请求的物理在途峰值为 4：通过；
- 后台 tail 未完成时 permit 不释放：通过；
- Circuit 打开后快速拒绝，tail 完成后恢复：通过；
- Phase 0 Primary recovery 严格 XFAIL 已删除并转为 PASS；
- Sanitized 4 题 Transport/Candidate replay：通过。

全量门禁：

```text
python -m compileall -q .                  passed
pytest -q                                  517 passed, 6 xfailed
python scripts/verify_baseline_files.py     passed
python scripts/validate_submission.py       passed（仅保留既有冻结警告）
python scripts/verify_build_provenance.py   passed
```

剩余 6 个严格 XFAIL 均已明确分配给 Phase 4 或 Phase 6，不属于本阶段漏项。

## 5. 未执行项

本阶段没有使用用户 API，也没有发起真实 Intern-S 请求。原因是本轮没有注入正式
Client/API 授权，而且先执行离线故障注入可以避免在逻辑未稳定时消耗真实配额。
因此“真实 4 题 canary”仍是提交前外部验证门槛，不在本报告中伪报为已通过。

## 6. 阶段结论

Phase 2 的代码目标和离线验收已经完成。当前 `max_model_calls=6` 表示 Harness
可见的真实派发硬上限，正常路径目标仍为 1–3 次。后台 tail、排队拒绝和本地重试
不再静默放大真实物理调用数。
