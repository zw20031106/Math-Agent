# MathForge 整改阶段 1 执行报告

日期：2026-07-29  
阶段目标：止血，消除候选 fanout、后台尾单、截止窗口和模型身份造成的主要空答路径。

## 一、完成项

### P1 + F1(a)：对齐外层并发与候选 fanout

- `config/competition.json` 的模型并发由 1 调整为 3，使单题最多三个候选可以真实派发。
- `.env.example`、README 和配置文档明确规定正式 Docker/本地冻结入口设置
  `LOCAL_MAX_CONCURRENCY=1`，避免八个题目争抢同一个候选级模型闸门。
- `scripts/validate_submission.py` 在未设置该环境变量时给出明确部署警告。

### F2：单个超时尾单不再毒化整条链路

- `max_background_model_tails` 由 1 调整为 4。
- 超时请求转入独立尾单记账后立即释放主模型并发 permit；后台线程完成时不会重复释放。
- 单个尾单只把 Provider 标记为 `degraded`，不会立即 `circuit_open`。
- 达到配置的尾单阈值时仍保留熔断保护，防止无限生成后台线程。

### F3：有效模型答案在 finalize cutoff 到达时仍然保留

- 删除 Solver 在成功取得响应后仅因 `must_finalize()` 而抛弃答案的路径。
- Runtime 在 fanout 后进入确定性定稿窗口时记录被禁用的可选工作，但保留已生成候选继续执行。
- Provider 已保证非空，删除 Solver 中重复且不可达的空响应检查。

### P2：修正模型身份真实性

审查报告建议正式入口强制读取 `INTERN_MODEL`，但该做法与正式注入契约及
“官方不会注入该环境变量”的运行条件冲突，因此按同一整改目标采用以下实现：

- 正式 `ReasoningAgent` 继续只依赖注入的 `client.chat(...)`。
- 正式入口不再伪报 `intern-s2-preview-397b`，而是记录
  `requested_model=unreported`、`request_source=official_client_injected`。
- 本地 benchmark/case runner 继续通过 `require_exact_intern_model()` 强制校验
  `INTERN_MODEL=intern-s2-preview-397b`，并仅在该路径记录精确请求模型。
- 不访问 Client 私有字段，不创建第二模型客户端。

## 二、验证结果

阶段定向回归：

```text
73 passed
```

覆盖范围：

- 并发、排队、尾单、熔断与 permit 回收；
- 有效 Candidate 到点保留；
- 正式入口无 `INTERN_MODEL`/API 环境仍可运行；
- 正式与本地模型身份边界；
- Competition 配置契约；
- Submission 验证与部署警告。

离线正式入口 smoke：

```text
Formal entry offline smoke passed.
```

## 三、阶段结论

阶段 1 已完成。现在单个 Provider 超时不会占住唯一 permit 并立即熔断后续
Verifier/Repair；fanout 具备三个真实并发槽；已经返回的有效候选不会因为刚好进入
定稿窗口而被主动丢弃；正式入口也不再记录无法证明的 397B 身份。

## 四、部署要求与遗留项

- 正式 Docker 必须设置 `LOCAL_MAX_CONCURRENCY=1`；这是冻结 `main.py` 无法在参赛代码内替代的外层运行参数。
- 配置仍为 `candidate-unvalidated`，尚未经过阶段 4 的全量回归和真实模型压力验证。
- 调用预算退款、上下文估算和预留语义属于阶段 2，尚未在本报告中宣称完成。
- `main.py`、`llm_client.py` 保持冻结，未修改。
