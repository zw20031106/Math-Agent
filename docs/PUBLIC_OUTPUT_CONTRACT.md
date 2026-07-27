# MathForge 公共输出契约

版本：3.0

## 对外字段

`ReasoningAgent.solve(problem, metadata)` 只返回：

```json
{
  "id": 0,
  "status": "success",
  "final_response": "Final answer: ...",
  "trace": []
}
```

- `id`：优先读取 `metadata.id`，否则读取 `metadata.idx`；两者都缺失时为
  `null`。
- `status`：仅允许 `success`、`failed`、`timeout`。只有主求解流程成功才是
  `success`；Fallback、候选生成失败和内部执行失败均为 `failed`；单题
  1,200 秒 watchdog 到期为 `timeout`。
- `final_response`：非空字符串。
- `trace`：有序事件列表，以 `run_completed` 结束。

公共结果没有 `result` 包装，也不暴露 `run_metrics`。后者只保留在内部
Harness、Benchmark artifact 和逐题运行清单中。

## Trace 内容

公共 `trace` 使用 Judge Trace V3，是面向判分的有界审计叙事，不是内部
框架日志或 Debug Journal：

- 保留会话/配置、路由/Skill、关键 Evidence、proof completion、仲裁、
  最终选择、预算和终态摘要。
- 只对选中 Candidate 保留必要公开解题步骤和最终答案，且不在 Trace 中重复
  `final_response`；二者通过内容摘要绑定并校验一致性。
- 未选 Candidate 只保留 `candidate_id`、`role`、`method_family`、
  `status`、`content_digest`、`rejection_category` 和
  `evidence_summary`，不保留其答案、步骤、Claims 或完整正文。
- 最终缩进 UTF-8 JSON、Trace 事件数/字符数、单事件字符数和未选 Candidate
  数量均受命名配置预算约束。超限内容转换为带数量和摘要的结构化记录，不
  破坏 JSON 或裁掉关键终态事件。
- 模型调用失败只记录安全原因码（例如 `provider_5xx`、
  `network_read_timeout`、`candidate_json_incomplete`），不公开 API 密钥、
  绝对路径、原始异常、raw response 或私有推理草稿。

内部 Harness 的 Trace V2 保留完整交叉引用用于运行时验证；本地增量 journal
使用独立的脱敏 Debug Trace Schema。两者都不会由 `ReasoningAgent.solve()`
返回给 judger。

当模型没有返回任何候选内容时，Trace 不会伪造推理链；`status` 为
`failed`，并明确记录失败发生在模型调用阶段。

## 独立文件与即时写盘

```text
python scripts/run_case_outputs.py \
  --input cases.jsonl \
  --output-dir case-outputs \
  --config config/competition.json \
  --concurrency 1
```

运行器先完成输入与清单预检，再依次执行 L0/L1/L2：精确模型身份和 Client
可用性、短且严格的 JSON、缩短版真实数学 Candidate。L2 必须经生产 Parser、
Formatter、Trace 和公共输出契约完整验证。只有三级全部通过后，批量题目才会
启动；“返回了非空文本”不再构成通过。每级状态、耗时、输出上限和 Transport
尝试数写入 Manifest。

正式请求的本地 HTTP 窗口为 125 秒，对齐官方约 120 秒服务端边界并只保留
少量传输裕量。只有在 10 秒内明确返回的限流、5xx 或连接错误才允许重试
一次；空响应、读超时、不完整 JSON 和 Schema 违约不重复发送同一大 Prompt。
官方 Client 的内部尝试数固定为 1，外层每次尝试均进入结构化 Metrics。
竞赛配置的模型调用 Gate 并发数为 1；多候选仍会生成，但按截止时间感知的
顺序进入模型服务，避免并发请求造成服务拒绝。
运行时必须使用官方精确版本字段
`INTERN_MODEL=intern-s2-preview-397b`；Legacy `intern-s2-preview`
当前指向 35B，不能作为 397B 验收结果。角色输出上限分别为
Router/Finalizer 4,096、Verifier 8,192、Repair 12,288、Lemma 16,384、
Alternative 24,576、Primary 32,768 Token；总上下文仍为 262,144 Token，
另保留 8,192 Token 安全余量。

每道题结束后立即：

1. 生成只含 `id`、`status`、`final_response`、`trace` 的
   `case-outputs/<id>.json`；
2. 刷新并同步同目录临时文件；
3. 原子替换目标文件；
4. 原子更新 `case-outputs/run_manifest.json`；
5. 输出并刷新 `CASE_COMPLETED` 行。

成功、失败和超时都会形成非空、可解析、带终态 Trace 的逐题 JSON。单题
watchdog 为 1,200 秒，其中 Harness 最迟在 1,150 秒交还控制权，预留 50 秒
完成序列化和写盘。每次模型排队最多使用 15 秒，角色调用超时从排队开始计算。
模型调用超时后，Python daemon thread 不会被伪称为已取消；它进入有上限的
provider background tail，达到上限后 circuit-open，后续调用快速失败。迟到线程
只能更新不含题目、Candidate 或 Session 引用的 provider 级登记，不能改写已经
返回或落盘的结果。

## 恢复运行

中断后使用同一命令并增加 `--resume`。恢复前会校验：

- 输入 JSONL 与配置文件的 SHA-256；
- case ID 集合、数量与随机种子；
- 已有逐题 JSON 的精确四字段 Schema、ID、状态、非空回答和终态 Trace；
- 逐题文件与运行清单绑定的 SHA-256。

默认只跳过校验成功且状态为 `success` 的题目；`failed` 和 `timeout`
题目会重新执行并原子替换原结果。可以使用 `--rerun-status` 显式调整
重跑集合。未知文件、损坏文件、哈希变化或不兼容清单会在题目模型调用前
失败。

Runner 默认且强制 `concurrency=1`，因此未启动题目的 1,200 秒期限不会在
队列等待期间消耗。Manifest 依次进入 `created`、`preflight_passed`、
`running`，并以 `completed`、`degraded`、`aborted` 或 `failed` 结束。
SIGINT/SIGTERM 会等待当前题安全写盘、阻止启动下一题并记录 `aborted`。
`--max-cases` 和 `--stop-after-case` 会在目标题写盘后以 `degraded`
终止，后续可用 `--resume` 继续。

## 冻结入口边界

官方 `main.py` 和 `llm_client.py` 不得修改。`main.py` 保留官方样例的
`idx/status/final_response/trace` 包装，并仍会把正常返回强制标为
`success`、在异常结果中增加 `error` 字段且默认并发为 8。本项目的精确
四字段、状态、单题期限、Manifest 和 Resume 契约由
`scripts/run_case_outputs.py` 提供。若要求两个入口完全一致，必须先取得
修改冻结基线的书面许可。
