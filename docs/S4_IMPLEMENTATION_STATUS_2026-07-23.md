# S4 可观测性与评测可信度实施状态

日期：2026-07-23

范围：C20–C22

状态：已完成工程实现与自动化验收

## 1. 验收结论

| 缺陷 | 实施结果 | 自动化验收 |
|---|---|---|
| C20 顶层失败不可诊断 | 顶层异常映射为 `parse/context/budget/tool/proof_incomplete/all_candidates_failed/config`；Trace 始终以 `run_completed` 结束 | 逐类错误码测试；judge Trace 不含原始异常；成功和 fallback 均有结构化终态 |
| C20 Trace 与本地诊断混用 | judge Trace 继续白名单和大小限制；可选 debug sink 单独保存脱敏 stack frames 与 internal events | InMemory/JSONL sink 均通过脱敏测试，默认公开入口不启用 |
| C21 成本依赖截断 Trace | 新增版本化 `RunMetrics 1.0`，独立记录成本、阶段、错误码、context/tool/lemma/repair/RAG 和隔离标识 | 删减 Trace 后仍能得到相同成本；严格反序列化、round-trip 和非负约束通过 |
| C21 Benchmark 不可复核 | Benchmark schema 升级至 `3.0`，每题保存独立 RunMetrics、score、latency、pollution 和重复实验信息 | artifact round-trip 后 `summarize(records)` 与原 summary 完全一致 |
| C21 污染检查不足 | 捕获实际模型 messages 中的 nonce；检查外题 nonce、候选调用归属、输出/Trace 串题和返回后变异 | 8 题并发真实消息探针无污染；人工注入返回后变异可被检出 |
| C21 缺统计不确定性 | 支持 repetitions/seed、Wilson 95% CI、seeded bootstrap 95% CI 和配对 exact significance | 同 seed 结果稳定；paired wins/losses/ties/p-value 可从 records 重算 |
| C22 测试门禁不完整 | 新增低/中/高风险黄金 E2E、16 并发故障注入、Prompt/Schema fuzz；固定 Ruff/Mypy/branch coverage 门禁 | 全量测试、静态检查、总覆盖率及五个关键模块覆盖率均通过 |

## 2. Runtime 终态与本地调试

`MathForgeHarness.solve()` 的 judge-safe 结果保持：

```text
final_response
trace
run_metrics
```

所有路径最后写入：

```text
run_completed(outcome, error_code, final_phase)
```

失败明细不会进入 judge Trace。需要本地诊断时，可在构造 Harness 时显式注入
`InMemoryDebugSink` 或 `JsonlDebugSink`。sink 只接收脱敏后的 stack frames 和
internal events；sink 写入失败不会破坏公开 fallback 契约。公开
`ReasoningAgent` 不启用 debug sink。

## 3. RunMetrics 1.0

每次运行创建独立、严格验证、可序列化的 `RunMetrics`，其中包含：

- session ID、request fingerprint、outcome、final phase 和 safe error code；
- model calls、estimated tokens、Claim/Tool/Evidence/Prompt 和 wall-time 成本；
- context attempts/failures；
- tool checks 的 timeout/unknown/error；
- Lemma checked/error、Repair attempts/successes 和 RAG queries/hits。

Benchmark summary 只读取每题 record 的 `run_metrics`。Trace 仍保留供人工复核，
但不再是指标数据库。

## 4. Benchmark 3.0

`run_benchmark()` 新增：

- `repetitions` 和 `seed`；
- `pollution_probe(nonce, all_nonces)`；
- `late_mutation_grace_seconds`；
- Wilson 与 seeded bootstrap 置信区间；
- `paired_significance(treatment, control)` 配对精确检验。

每题 result 在 solve 返回时立即 JSON 深拷贝，后续慢线程即使错误修改原对象，
也不会改变已记录 artifact；探针同时记录该变异。

## 5. C22 质量门禁

提交前执行：

```text
python -m compileall .
ruff check .
mypy mathforge user_agent.py
pytest -q
pytest --cov=mathforge --cov-branch --cov-report=term-missing
python scripts/check_coverage_gates.py
python scripts/verify_baseline_files.py
python scripts/validate_submission.py
git diff --check
```

覆盖率门槛：

| 范围 | 门槛 | 本阶段实测 |
|---|---:|---:|
| mathforge 总体 | 80% | 81.30% |
| Runtime | 80% | 87.42% |
| Completion | 85% | 93.02% |
| Evidence | 85% | 91.93% |
| Config | 70% | 75.92% |
| Formatter | 70% | 77.78% |

## 6. 验证结果

- 全量 pytest：241 passed；
- Ruff：通过；
- Mypy：81 个源文件通过；
- 分支覆盖率：总计 81.30%，五个关键模块门槛全部通过；
- baseline、submission、依赖和 Git diff 门禁在提交前执行。

## 7. 剩余边界

- S4 不执行 C24–C26 的 RAG 内容治理、完整 artifact 运行指纹和 MCP 生命周期；
- `config/competition.json` 继续保持 `candidate-unvalidated`；
- 真实比赛数据的 A0–A10 重复消融、配置冻结和人工审核属于 S5。

下一阶段为 S5（C24–C26）。
