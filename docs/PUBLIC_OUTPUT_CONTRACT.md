# MathForge 公共输出契约

版本：2.1

## 对外字段

`ReasoningAgent.solve(problem, metadata)` 只返回：

```json
{
  "id": 0,
  "final_response": "Final answer: ...",
  "trace": []
}
```

- `id`：优先读取 `metadata.id`，否则读取 `metadata.idx`；两者均缺失时为
  `null`。
- `final_response`：非空字符串。
- `trace`：列表，并以终态事件结束。

公共结果没有 `result` 包装，也不暴露 `run_metrics` 或 `provenance`。
后两者仅保留在内部 Harness、Benchmark artifact 和逐题运行清单中。

## 独立文件与即时写盘

```text
python scripts/run_case_outputs.py \
  --input cases.jsonl \
  --output-dir case-outputs \
  --config config/competition.json \
  --concurrency 4
```

输入预检会在创建在线客户端前完成，包括重复 ID、期望答案及评分覆盖率检查。
每道题结束后立即：

1. 生成只含 `id`、`final_response`、`trace` 的
   `case-outputs/<id>.json`；
2. 刷新并同步同目录临时文件；
3. 原子替换目标文件；
4. 原子更新 `case-outputs/run_manifest.json`；
5. 输出并刷新 `CASE_COMPLETED` 行。

成功、内部失败和超时都会形成非空、可解析、带终态 Trace 的逐题 JSON。
单题 watchdog 为 900 秒，其中 Harness 最迟在 870 秒交还控制权，预留 30 秒
完成序列化和写盘。超时后的迟到线程不能改写已返回或已落盘的结果。

## 恢复运行

中断后使用同一命令并增加：

```text
--resume
```

恢复前会校验：

- 输入 JSONL 与配置文件的 SHA-256；
- case ID 集合、数量与随机种子；
- 已有逐题 JSON 的精确三字段 Schema、ID、非空回答和终态 Trace；
- 逐题文件与运行清单绑定的 SHA-256。

校验成功的题目直接跳过，只运行缺失题目。未知文件、损坏文件、哈希变化或不兼容
清单会在发起模型调用前失败。

## 冻结入口边界

官方 `main.py` 与 `llm_client.py` 不得修改。`main.py` 保留官方样例的
`idx/status/final_response/trace` 包装；需要本项目三字段独立文件时，使用
`scripts/run_case_outputs.py`。
