# Phase 1 执行报告：稳定答案保全与 Provider 降级策略

日期：2026-07-30
阶段结论：完成，可进入 Phase 2
真实模型调用：未执行（全部验收使用注入式离线 client）

## 目标与实施

本阶段执行审查报告的“稳定答案保全”计划，目标是在不放松硬证据门的前提下，
降低传输和下游异常导致的空答案。

已完成：

1. **单调预算重规划**
   `CallAllocationPlan.with_stage_floors()` 保留已消耗阶段的累计下限，
   `CallBudget.set_allocation_plan()` 不再因缩小未来计划而否定历史合法调用；全局
   `max_calls` 仍是不可绕过的总上限。
2. **最后安全候选保全**
   `MathForgeHarness.solve()` 维护 `last_safe_checkpoint`。启用硬证据时，只有通过
   `hard_evidence_gate` 的候选可成为安全检查点；禁用硬证据时，已通过确定性入场的
   候选可成为检查点。所有候选被硬拒时显式清空检查点。
3. **受控降级产出**
   下游异常发生后，如存在未被硬否定的检查点，系统以确定性格式化返回该数学答案，
   记录 `degraded_candidate_salvage`、候选 ID、检查点和公开步骤；不会伪造完整验证，
   也不会返回 hard-failed Candidate。无安全候选时保留原有 fallback。
4. **低风险 lazy Standby Alternative**
   预算中预留一个备用分支，但 Primary 严格成功时不执行。Primary 两次可重试传输失败、
   备用分支成功时，备用答案成为正常 primary outcome 的候选来源。
5. **共享 Provider 健康进入调度决策**
   普通连接/读取/空响应/响应形状失败进入有限窗口健康状态。Provider 为 degraded 或
   circuit-open 时，仍保留候选答案形成与确定性输出，但停止 Router、Verifier、Repair、
   Lemma 和 LLM Finalizer 等可选模型工作，并在 `call_allocation_rebalanced` 中记录原因。
6. **非敏感 typed failure**
   `degraded_candidate_salvage` 成为受控运行指标错误码；公共 Trace 不暴露原始异常、
   凭据或本地路径。保全后的终态为 `completed`，与 `outcome=primary` 一致。

## 关键验收回归

- 历史已用 Primary 调用在重规划后仍合法，但总调用数不超过 `max_calls`。
- 两次 Primary `503` 失败后，备用 Candidate 成功时返回非空数学答案，且不触发
  `fallback_used`。
- 健康的低风险 Primary 成功时实际模型调用数为 1，没有无条件执行 Standby。
- 下游 Formatter 注入异常时，已通过门控的候选被保全；hard gate 明确拒绝候选时，
  不发生 candidate salvage。
- 两次普通 Provider 失败进入 `degraded`；降级状态在 Trace 中改变后续可选阶段选择。

## 验证记录

```text
python -m pytest -q -p no:cacheprovider --basetemp <external-temp> <all 69 test modules>
python -m compileall -q mathforge user_agent.py
python scripts/verify_baseline_files.py
```

结果：全量测试按两个无重叠分组完成，`150 passed + 417 passed = 567 passed`；
编译和不可变基线校验通过。原先 Windows 默认临时目录的访问限制通过仓库外受控
`--basetemp` 规避，未掩盖或忽略任何测试失败。

## 对 C01–C26 的相关贡献

本阶段直接改善 C01（稳定非空数学输出）、C07（安全传输失败）、C13/C14（预算与
候选调度）、C20/C21（终态和 Trace 闭环）、C22（故障注入回归）以及 C23/C25
（非敏感错误边界）。它不替代后续阶段对高难题长程推理、Skill 动态调度、工具闭环和
跨题记忆的验收。

## 明确保留的边界

- 不修改 `main.py` 或 `llm_client.py`。
- 不读取 API key、不假设模型字段、不创建新的在线 client；所有模型调用仍只经注入的
  `client.chat(messages, temperature, max_tokens)`。
- “保全”不等于跳过验证：hard evidence 已否定的 Candidate 永不回流为最终答案。
