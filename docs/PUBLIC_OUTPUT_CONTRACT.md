# MathForge 公共输出契约

版本：2.2

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
  900 秒 watchdog 到期为 `timeout`。
- `final_response`：非空字符串。
- `trace`：有序事件列表，以 `run_completed` 结束。

公共结果没有 `result` 包装，也不暴露 `run_metrics`。后者只保留在内部
Harness、Benchmark artifact 和逐题运行清单中。

## Trace 内容

公共 Trace 是可审计的解题过程，不是框架日志堆叠：

- 候选成功时，完整保留每个候选的公开解题步骤、最终答案、假设、定理、
  Claims、MethodSteps 和未解决义务，不设置字符数上限。
- 完整保留证据结果、证明义务、Lemma/Repair 记录、候选仲裁、最终选择与
  终态原因。
- 删除重复的阶段切换、上下文视图构建和重复完成事件；压缩静态 provenance、
  skills 和 budget 遥测。
- 模型调用失败只记录安全原因码（例如 `model_call_failed`），不公开 API
  密钥、绝对路径、原始异常或私有推理草稿。

当模型没有返回任何候选内容时，Trace 不会伪造推理链；`status` 为
`failed`，并明确记录失败发生在模型调用阶段。

## 独立文件与即时写盘

```text
python scripts/run_case_outputs.py \
  --input cases.jsonl \
  --output-dir case-outputs \
  --config config/competition.json \
  --concurrency 4
```

运行器先完成输入与清单预检，再通过注入的官方 `client.chat(...)` 发起一次
真实响应预检。只有预检得到非空内容后，批量题目才会启动。正式模型调用
串行执行，只对 20 秒内返回的服务端快速拒绝做有界指数退避重试；竞赛配置
为快速失败预留 100 秒，并允许单次长请求持续 735 秒。这样既不会用样例
客户端默认的 120 秒截断 Intern-S2 长推理，也不会让重试越过单题截止时间。
竞赛配置的模型调用 Gate 并发数为 1；多候选仍会生成，但按截止时间感知的
顺序进入模型服务，避免并发请求造成服务拒绝。
运行时必须使用实际可调用字段 `INTERN_MODEL=intern-s2-preview`。批量预检和
Competition 主求解 Completion 上限均为 65,536 Token；总上下文仍为 262,144
Token，另保留 8,192 Token 安全余量。

每道题结束后立即：

1. 生成只含 `id`、`status`、`final_response`、`trace` 的
   `case-outputs/<id>.json`；
2. 刷新并同步同目录临时文件；
3. 原子替换目标文件；
4. 原子更新 `case-outputs/run_manifest.json`；
5. 输出并刷新 `CASE_COMPLETED` 行。

成功、失败和超时都会形成非空、可解析、带终态 Trace 的逐题 JSON。单题
watchdog 为 900 秒，其中 Harness 最迟在 870 秒交还控制权，预留 30 秒完成
序列化和写盘。迟到线程不能改写已经返回或落盘的结果。

## 恢复运行

中断后使用同一命令并增加 `--resume`。恢复前会校验：

- 输入 JSONL 与配置文件的 SHA-256；
- case ID 集合、数量与随机种子；
- 已有逐题 JSON 的精确四字段 Schema、ID、状态、非空回答和终态 Trace；
- 逐题文件与运行清单绑定的 SHA-256。

校验成功的题目直接跳过，只执行缺失题目。未知文件、损坏文件、哈希变化或
不兼容清单会在题目模型调用前失败。

## 冻结入口边界

官方 `main.py` 和 `llm_client.py` 不得修改。`main.py` 保留官方样例的
`idx/status/final_response/trace` 包装；本项目的四字段独立文件使用
`scripts/run_case_outputs.py`。
