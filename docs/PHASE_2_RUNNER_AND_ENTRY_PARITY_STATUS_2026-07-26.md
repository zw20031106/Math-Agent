# Phase 2：Runner 与官方入口一致性实施状态

日期：2026-07-26

## 1. 本阶段范围

本阶段按 2026-07-26 复审实施计划完成以下工作：

1. 自定义逐题 Runner 默认且强制单题并发；
2. 完整区分 Manifest 的正常完成、降级停止、外部中断和致命失败；
3. 支持信号停止、指定题后停止、限定本次题数，以及失败/超时重跑；
4. 建立自定义 Runner 与冻结官方入口的契约对照测试；
5. 明确冻结文件导致的不可修正边界。

`main.py` 和 `llm_client.py` 均未修改。

## 2. Runner 闭环

### 2.1 严格单题调度

`scripts/run_case_outputs.py` 的 `--concurrency` 默认值为 `1`，传入其他
值会在读取测试集和调用模型前直接失败。Runner 每次只把一道题交给
`run_benchmark`，上一题完成四字段 JSON 和 Manifest 原子写入后，下一题
才会创建自己的 900 秒墙钟。

这保证等待上一题的时间不计入尚未启动题目的单题期限。

### 2.2 Manifest 生命周期

| 状态 | 含义 | 可否使用 `--resume` |
|---|---|---|
| `created` | 清单已创建，尚未通过模型预检 | 是 |
| `preflight_passed` | L0/L1/L2 已通过，尚未启动题目 | 是 |
| `running` | 正在执行一道题 | 是 |
| `completed` | 所有题目均已有终态文件 | 无需 |
| `degraded` | 按控制条件或 Provider 熔断提前停止 | 是 |
| `aborted` | 收到 SIGINT/SIGTERM 后安全停止 | 是 |
| `failed` | 预检、配置或 Runner 出现致命失败 | 是 |

`finalize()` 不会把 `aborted`、`degraded` 或 `failed` 覆盖回其他状态；
终态同时保存 `ended_at`、待运行题数和逐题状态计数。旧的 Manifest
Schema 1.1 可读取并在恢复时升级为 1.2。

### 2.3 停止与恢复

- SIGINT/SIGTERM 只提出停止请求，不破坏当前题的结果槽；
- 当前题完成安全写盘后停止接收下一题，Manifest 记为 `aborted`；
- `--max-cases N` 在本次执行完成 N 题后停止；
- `--stop-after-case ID` 在指定题写盘后停止；
- Provider 连续故障熔断记为可恢复的 `degraded`；
- `--resume` 默认只跳过 `success`，已有 `failed` 和 `timeout` 文件会被
  原子替换为本次重跑结果；
- `--rerun-status failed,timeout` 可显式调整重跑状态集合。

推荐命令：

```powershell
$env:INTERN_MODEL = "intern-s2-preview-397b"
python scripts/run_case_outputs.py `
  --input "D:\path\cases.jsonl" `
  --output-dir "D:\path\outputs" `
  --config "config\competition.json"
```

恢复命令：

```powershell
python scripts/run_case_outputs.py `
  --input "D:\path\cases.jsonl" `
  --output-dir "D:\path\outputs" `
  --config "config\competition.json" `
  --resume
```

## 3. 四字段和 15 分钟验收

每题结束时依次完成：

1. 生成且校验仅含 `id`、`status`、`final_response`、`trace` 的结果；
2. 同目录临时文件写入、刷新并原子替换 `<id>.json`；
3. 记录结果哈希、状态、Metrics 和时间并原子更新 Manifest；
4. 刷新打印 `CASE_COMPLETED`；
5. 才允许调度下一题。

Harness 最迟在 870 秒交还，预留 30 秒进行确定性终结和持久化。终态映射
保持为：主流程成功为 `success`，fallback/error 为 `failed`，墙钟到期为
`timeout`。超时 Worker 被关闭出共享结果槽，不能覆盖已经返回或落盘的
结果。

## 4. 冻结官方入口对照

官方入口的求解内容仍来自根目录 `ReasoningAgent.solve()`，但冻结包装器
和自定义 Runner 并不具备完全相同的文件契约：

| 项目 | 自定义 Runner | 冻结 `main.py` |
|---|---|---|
| 标识字段 | `id` | `idx` |
| Agent 返回失败状态 | 保留为 `failed` | 强制写成 `success` |
| 异常输出 | 合法四字段、非空回答、终态 Trace | 增加 `error`，回答为空 |
| 默认题级并发 | 强制 1 | 环境默认 8 |
| Resume | 成功跳过，失败/超时重跑 | 任意非空文件均跳过 |
| Manifest/信号终态 | 完整支持 | 不支持 |

`tests/test_phase2_entry_parity.py` 固定验证了这条边界：官方入口能够传递
Agent 的 `final_response` 和 `trace`，但会改写标识和状态。由于项目规则
明确禁止修改 `main.py`、`llm_client.py`，本阶段没有伪造“完全一致”。
如要求官方入口也输出相同四字段、状态和恢复语义，必须先取得书面许可，
再修改冻结基线和对应哈希。

## 5. 回归覆盖

本阶段新增或更新测试覆盖：

- 默认并发为 1，显式并发 2 在运行前被拒绝；
- 成功结果默认跳过，失败和超时默认重跑；
- `created → preflight_passed → running → aborted` 生命周期；
- SIGINT 转换为安全停止请求并恢复原信号处理器；
- `--max-cases` 在题目写盘后产生 `degraded`，未启动下一题；
- Provider 熔断产生 `degraded` 而不是致命 `failed`；
- 官方冻结入口的内容传递和包装差异；
- 失败/超时仍保持四字段、原子文件和终态 Trace；
- 900 秒墙钟的缩短比例测试，以及迟到线程不可覆盖结果。

最终门禁按项目规则执行：

```text
python -m compileall .
pytest -q
python scripts/verify_baseline_files.py
```
