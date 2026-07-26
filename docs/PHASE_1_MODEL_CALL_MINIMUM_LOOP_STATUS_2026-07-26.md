# Phase 1 模型调用最小闭环实施状态

日期：2026-07-26

## 1. 实施结论

Phase 1 的工程项已经接入真实运行路径：

1. 批量执行前必须依次通过 L0、L1、L2，非空文本不能冒充预检成功。
2. 单次 HTTP 等待上限改为 125 秒，对齐官方约 120 秒输出边界。
3. Provider 按角色限制单次等待和输出预算。
4. Transport、空响应、截断 JSON、Schema 违约使用独立安全错误码。
5. Solver、Repair、Finalizer 产生的 Candidate 都经过同一完整性门禁。
6. 底层 Client 在自定义 Runner 中只尝试一次；外层只对明确且快速的可重试
   故障重试一次，所有尝试进入 Metrics。
7. 连续 Provider 故障达到阈值后停止调度后续批次，并在 Manifest 中记录
   `provider_circuit_open`。

冻结的 `main.py`、`llm_client.py` 未修改，也没有创建第二个在线模型客户端。

## 2. 三级预检

| 层级 | 检查 | 失败行为 |
|---|---|---|
| L0 | `INTERN_MODEL` 必须精确为 `intern-s2-preview-397b`，且官方 Client 可构造 | 不发题目请求，Manifest 记录安全错误码 |
| L1 | 模型必须精确返回可解析的 `{"status":"ok"}` | 非空自然语言、空响应和错误结构均失败 |
| L2 | 缩短版 `1+1` 数学 Prompt 返回完整 Candidate | 必须经 Candidate Parser、确定性 Formatter、Trace v2 和四字段公共输出验证 |

Manifest Schema 升至 1.1，保存每级状态、耗时、输出上限和 Transport 尝试数。
L2 失败时 Harness 和批量题目均不会启动。

## 3. 角色资源策略

| 角色 | 输出上限 | 单次 Host 等待上限 |
|---|---:|---:|
| Router | 4,096 | 60 秒 |
| Primary | 32,768 | 125 秒 |
| Alternative | 24,576 | 125 秒 |
| Verifier | 8,192 | 90 秒 |
| Repair | 12,288 | 110 秒 |
| Lemma | 16,384 | 110 秒 |
| Finalizer | 4,096 | 60 秒 |

实际输出预算仍会被剩余上下文再次压缩，始终满足
`prompt + output + safety_margin <= 262144`。

## 4. 安全错误分类

Transport 层至少区分：

- `auth_or_permission_failure`
- `rate_limited`
- `provider_5xx`
- `network_connect_failure`
- `network_read_timeout`
- `response_shape_invalid`
- `empty_response`
- `model_response_deadline_exceeded`
- `model_concurrency_wait_exceeded`
- `unknown_provider_failure`

Candidate 响应另区分：

- `candidate_json_incomplete`
- `candidate_json_invalid`
- `candidate_schema_invalid`

返回 Trace、预检报告和 Manifest 不包含原始异常、密钥或完整失败候选。

## 5. 可观测性与熔断

RunMetrics Schema 升至 1.3，新增：

- `transport_attempts`
- `model_call_failure_count`
- `model_response_rejection_count`

每个模型调用记录配置输出、角色上限、实际输出预算、Transport 尝试数、
安全失败码和响应完整性结果。默认连续三道终态失败且原因属于 Provider/
Candidate 响应故障时打开熔断；成功主流程会重置连续失败计数。

## 6. 验收状态

已由离线自动测试覆盖：

- 错误模型身份在 L0 阶段且零 Provider 调用失败；
- 缺失 Client 在 L0 安全失败；
- 非空非 JSON 文本不能通过 L1；
- L2 完整走通 Parser、Formatter、Trace 和公共输出；
- 角色输出/等待预算；
- 快速可重试与不可重试错误边界；
- 尝试数和安全错误码进入 Metrics；
- 截断与 Schema 不完整 Candidate 被拒绝；
- 连续失败熔断、成功重置和 Manifest 持久化；
- 原始 Provider 异常不进入预检报告。

“结构化预检连续 30 次至少 29 次成功”属于真实 Provider 稳定性验收，当前没有
使用已在对话中暴露的旧密钥执行。应在平台撤销旧密钥、生成新密钥后，以进程
环境变量注入并生成新的受控证据。完成该项之前，Competition 状态继续保持
`candidate-unvalidated`，不得宣称在线模型可靠性已经冻结。

## 7. Phase 2 边界

本阶段没有修改冻结官方入口，也没有实现 signal handling、失败题选择性重跑或
`stop-after-case`。这些属于下一阶段的 Runner/官方入口一致性任务。
