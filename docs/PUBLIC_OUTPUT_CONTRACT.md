# MathForge 公共输出契约

版本：1.0

## 对外字段

`ReasoningAgent.solve(problem, metadata)` 只返回：

```json
{
  "id": 0,
  "final_response": "Final answer: ...",
  "trace": []
}
```

- `id`：优先读取 `metadata.id`，否则读取 `metadata.idx`；两者都没有时为
  `null`。
- `final_response`：非空字符串。
- `trace`：列表。

对外结果没有 `result` 包裹，也不暴露 `run_metrics` 或 `provenance`。后两者只保留
在内部 `MathForgeHarness` 与聚合 Benchmark artifact 中。

## 独立文件与即时写盘

运行：

```text
python scripts/run_case_outputs.py \
  --input cases.jsonl \
  --output-dir case-outputs \
  --config config/competition.json \
  --concurrency 4 \
  --model-identifier public-model-name
```

每道题完成后立即写入 `case-outputs/<id>.json`。写入过程先生成同目录临时文件，再
执行原子替换；其他并发题目尚未完成时，已完成题目的文件已经可用。

## 冻结入口边界

官方 `main.py` 和 `llm_client.py` 不得修改。`main.py` 会按照官方样例再包装为
`idx/status/final_response/trace`。需要本项目三字段 `id/final_response/trace`
文件时，应使用 `scripts/run_case_outputs.py`。
