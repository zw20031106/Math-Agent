# Phase 1 并发与模型边界执行报告

> 日期：2026-07-29  
> 阶段结论：完成  
> 是否调用真实模型：否  
> 冻结文件：`main.py`、`llm_client.py` 未修改，校验通过

## 1. 阶段目标

按照 0729 整改计划完成真实题级并发 4，统一 Competition 模型调用边界，
消除本地 runner 对 `INTERN_MODEL` 和 `LOCAL_MAX_CONCURRENCY` 的依赖，并确保
每个活跃题先获得 Primary 调用机会。

## 2. 已解决问题

### 2.1 H01：并发边界冲突

- 在 `ReasoningAgent` 内增加 `BoundedSemaphore(4)`。
- 排队题获得 permit 后才进入 `MathForgeHarness.solve()`，因此 Session 和单题
  Deadline 不会在排队阶段提前消耗。
- `config/competition.json` 的 `model_max_concurrency` 统一为 4。
- 冻结的 `main.py` 仍保持官方默认值 8，但有效活跃题数由 Agent 内部限制为 4。

### 2.2 H02：Local runner 强制串行

- `scripts/run_case_outputs.py` 的 `--concurrency` 改为接受 `1..4`，默认 4。
- `mathforge.benchmark.run_benchmark()` 从“一次性提交全部任务”改为滚动窗口：
  最多仅保留 `concurrency` 个在途任务。
- 每题完成 callback 仍立即执行原子 JSON 写盘和 Manifest 更新。
- `--max-cases`、`--stop-after-case` 会先限制本次计划批次，不会因并发窗口超跑。
- 外部停止或 Provider circuit 打开后，不再提交新题；已经在途的题完成后仍会写盘。

### 2.3 H03：Local client 全局网络锁

- 删除 `SerializedFastRetryClient` 及其覆盖完整网络调用的全局 `Lock`。
- 替换为无全局串行化的 `FastRetryClient`。
- 重试次数、快速失败窗口和安全错误分类保持不变。
- 真实并发由 Harness 的共享 `ModelCallGate(4)` 管理。

### 2.4 H04：Primary 首次调用不公平

- Candidate fanout 改为先同步完成 Primary 分支，再启动可选 Alternative。
- Primary 失败时仍允许 Alternative 作为当前阶段已有的后备候选来源。
- 测试验证调用序列第一项必须是 `PrimarySolver`。
- 完整的跨角色优先队列、Primary transport recovery 和 background tail 物理容量
  归入 Phase 2，未在本阶段越界实现。

### 2.5 Manifest 恢复兼容性

- 新建 Manifest 记录实际 case concurrency。
- Resume 时把 concurrency 纳入兼容性校验。
- 使用不同并发参数恢复会明确拒绝，避免同一运行目录混入不同调度语义。

### 2.6 本地模型选择与正式 provenance

- `run_case_outputs.py` 和 `run_benchmark.py` 使用显式 `--model` 参数。
- 默认值和唯一允许值为 `intern-s2-preview-397b`。
- 本地创建官方 Client 后显式写入公开 `client.model`，确保请求 payload 使用 397B，
  不依赖 `INTERN_MODEL`。
- 删除只为环境变量模型门服务的冗余函数、常量和全局测试 fixture。
- `.env.example` 只保留 `INTERN_API_KEY`。
- 本地 benchmark provenance 记录
  `request_source=argument:--model`；正式 Agent 继续诚实记录
  `official_client_injected/unreported`。

## 3. 主要文件

| 文件 | 变更 |
|---|---|
| `user_agent.py` | Agent 题级准入上限 4 |
| `config/competition.json` | 模型调用并发统一为 4 |
| `mathforge/benchmark.py` | 滚动任务窗口与停止调度回调 |
| `mathforge/harness/orchestration.py` | Primary-first Candidate 调度 |
| `mathforge/model_identity.py` | 删除环境变量模型门，保留显式精确模型身份 |
| `mathforge/evaluation/artifacts.py` | benchmark artifact 接受显式 CLI provenance |
| `scripts/run_case_outputs.py` | 并发 4、无全局网络锁、滚动执行、Manifest 校验、`--model` |
| `scripts/run_benchmark.py` | 显式 `--model` 并写入 Client |
| `tests/test_phase1_0729_concurrency.py` | 阶段 1 核心并发与恢复契约 |
| `README.md`、配置/输出文档 | 删除过时环境变量和串行运行要求 |

## 4. 冗余清理

- 删除空壳用途的 `tests/conftest.py` 全局 `INTERN_MODEL` 注入。
- 删除未被生产路径使用的 `require_exact_intern_model()` 和
  `MODEL_ENVIRONMENT_VARIABLE`。
- 删除本地提交校验器中的 `LOCAL_MAX_CONCURRENCY=1` 警告。
- 删除 eager `as_completed` 全量提交路径和网络调用全局锁。
- 将旧类名 `SerializedFastRetryClient` 全部替换为与行为一致的
  `FastRetryClient`。

## 5. 测试与门禁

阶段定向回归：

```text
50 passed, 7 xfailed
```

全量门禁：

```text
python -m compileall .                    passed
pytest -q                                506 passed, 7 xfailed
python scripts/verify_baseline_files.py   passed
python scripts/validate_submission.py     passed
```

剩余 7 个严格 XFAIL 均属于计划明确分配给 Phase 2、Phase 4 或 Phase 6 的
Transport recovery、Proof/Repair 和 Trace/Manifest 历史问题。阶段 1 的两个
原 XFAIL 已删除标记并真实通过。

## 6. 验收结论

| 验收项 | 结果 | 证据 |
|---|---|---|
| 4 题同时运行，活跃 solve 不超过 4 | 通过 | Agent admission 并发探针 |
| 正常模型调用物理在途不超过 4 | 通过 | `ModelCallGate(4)` 八线程探针 |
| 每题先获得 Primary | 通过 | Orchestrator 调用顺序测试 |
| 不设置 `INTERN_MODEL` 可构造正式 Agent | 通过 | 正式入口无环境模型测试 |
| Local runner 明确发送 397B | 通过 | Client `model` 赋值与 runner 测试 |
| 不一次性提交完整数据集 | 通过 | 12 题滚动窗口停止调度测试 |
| 单题完成立即持久化 | 通过 | 既有 lifecycle 与 `--max-cases` 回归 |
| Resume 校验 concurrency | 通过 | 不同并发恢复拒绝测试 |

## 7. C01-C26 相关映射

| 标准 | 本阶段结果 |
|---|---|
| C05 | 正式/本地模型来源分离，本地显式精确模型字段 |
| C07 | Local transport wrapper 保留受控重试且不再全局串行 |
| C13 | 题级并发、模型 Gate 和滚动窗口统一为 4 |
| C14 | Primary-first；完整 recovery/跨角色优先级留待 Phase 2 |
| C20/C21 | 并发运行仍逐题原子持久化，Manifest 增加恢复兼容字段 |
| C22 | 新增并发、滚动调度、Manifest 和模型选择离线回归 |
| C23/C25 | 冻结文件与提交校验均通过，正式 provenance 不伪造模型身份 |

## 8. 未越界处理的风险

以下不是 Phase 1 未完成项，而是整改计划已明确分配给后续阶段：

- Primary 第一次 Transport 失败后的候选级 recovery：Phase 2。
- 跨 Primary recovery、Verifier、Repair、Alternative 的完整优先队列：Phase 2。
- background tail 占用真实物理容量：Phase 2。
- 无候选时 proof complete、模型自报 obligation、unknown Repair：Phase 4。
- Trace LaTeX 路径误脱敏、attempt Journal、stale running history：Phase 6。

因此本阶段只做离线并发和故障注入验收，不启动真实 4 题 canary。根据计划，
真实 canary 应在 Phase 2 完成 Primary recovery 和 Provider 调度后执行。
