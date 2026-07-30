# Phase 0（0729）基线冻结与失败复现执行报告

> 日期：2026-07-29  
> 阶段结论：完成，允许进入 Phase 1  
> 是否调用真实模型：否  
> 冻结文件：未修改，校验通过

## 1. 阶段目标

将第四次真实测试暴露的问题转换成脱敏、可重复执行的回归证据，明确区分：

- 已有正常能力；
- 已稳定复现但尚未修复的缺陷；
- Phase 1 应立即转为通过的契约；
- Phase 2/4/6 才允许修复的问题。

## 2. 对应问题

- T01：Primary 传输失败无恢复；
- H01/H02：runner 强制并发 1；
- H03：本地模型调用被全局锁串行；
- V01：Proof Obligation 依赖模型自报；
- V02/O02：无候选显示 proof complete；
- V03：Verifier unknown 触发 Repair；
- O03：路径脱敏误伤 LaTeX；
- O04：Journal 覆盖；
- O05：stale running Manifest 无中断历史；
- G02/C22：离线 Stub 与真实响应形态之间缺少 replay 层；
- C25：真实证据脱敏和 provenance 边界。

## 3. 新增文件

1. `tests/fixtures/phase0_0729_live_regressions.json`
2. `tests/test_phase0_0729_regressions.py`
3. `docs/PHASE_0_0729_PROBLEM_TEST_MAP.md`
4. `docs/PHASE_0_EXECUTION_REPORT_2026-07-29.md`

## 4. 关键设计决策

### 4.1 不保存原始私有响应

Fixture 只保留：

- 公开数学候选；
- 公开解题步骤；
- 稳定错误码；
- 聚合延迟、调用和 Repair 指标；
- Manifest 中可公开的生命周期事实。

Fixture 不保留：

- API Key 或 Authorization；
- 本地绝对路径；
- 原始异常；
- 原始失败 completion；
- 模型私有思维链。

### 4.2 未完成问题使用严格 xfail

Phase 0 的职责是复现，不是越阶段修复。九个未完成问题使用
`pytest.mark.xfail(strict=True)`：

- 缺陷仍存在时，测试报告为 XFAIL；
- 如果代码意外改变并 XPASS，严格模式会让测试失败；
- 对应阶段实施时必须删除 xfail，并使测试真实通过。

### 4.3 Phase 1 契约已单独标记

以下两个测试将在 Phase 1 去掉 xfail：

- runner 默认并接受 concurrency=4；
- Local retry wrapper 不串行独立请求。

## 5. 未修改范围

- 未修改 `main.py`、`llm_client.py`；
- 未修改模型调用、并发、Candidate、Proof、Repair 和 Trace 生产逻辑；
- 未调用真实 API；
- 未覆盖或移动第四次测试原始结果；
- 未处理 Phase 2/4/6 问题。

## 6. 测试结果

执行：

```text
pytest -q tests/test_phase0_0729_regressions.py -rxX
python scripts/verify_baseline_files.py
```

结果：

```text
2 passed, 9 xfailed
Official immutable baseline files verified.
```

全量阶段门禁：

```text
python -m compileall .                    passed
pytest -q                                500 passed, 9 xfailed
python scripts/verify_baseline_files.py   passed
```

两个通过项：

1. 脱敏 live fixture 不包含凭证和绝对路径；
2. 两个真实候选 replay 可被当前严格 Candidate Parser 解析。

九个 XFAIL 与问题映射见 `PHASE_0_0729_PROBLEM_TEST_MAP.md`。

## 7. Before / After

### Before

- 第四次真实测试证据只存在外部测试目录；
- 已知缺陷没有统一、可执行的问题映射；
- 离线测试通过会掩盖真实闭环失败。

### After

- 公开、安全的真实测试摘要进入测试 fixture；
- Candidate 真实形态可离线 replay；
- 九个关键缺陷被严格复现；
- Phase 1、2、4、6 的责任边界明确。

## 8. C01–C26 映射

| 标准 | Phase 0 结果 |
|---|---|
| C01/C02 | Proof 与工具问题已建立回归入口，尚未修复 |
| C05 | 模型/并发配置冲突已建立 Phase 1 契约 |
| C07 | 真实 transport 与 terminal error 分开保存在 fixture |
| C13/C14 | 并发、调用和 Repair 成本有真实聚合证据 |
| C17 | unknown Repair 问题已复现 |
| C20/C21 | 状态、Journal、Manifest 问题已复现 |
| C22 | 新增 Replay 与故障契约层 |
| C23/C25 | Fixture 脱敏测试通过 |

## 9. 尚未完成风险

Phase 0 没有修正生产行为。当前仍然：

- runner 强制并发 1；
- 本地模型请求被全局 Lock 串行；
- Local runner 依赖 `INTERN_MODEL`；
- Competition 模型并发仍为 3；
- 后续阶段问题继续处于严格 XFAIL。

## 10. 是否允许进入下一阶段

允许进入 Phase 1。

进入条件已经满足：

- Phase 1 的 Before 行为可复现；
- 冻结文件未变；
- 真实证据已脱敏；
- Phase 1 修改范围和验收项已明确。
