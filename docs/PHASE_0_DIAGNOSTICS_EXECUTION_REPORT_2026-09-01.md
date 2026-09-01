# Math-Agent Phase 0 执行报告：恢复诊断能力

日期：2026-09-01  
依据：`方案文件/0901/Math-Agent_全项目重审_问题总结_解决方案_实施计划_2026-09-01.md`  
阶段目标：让每个用例的截断、阶段、失败和答案交付路径可被公开追踪，为后续阶段建立可验证入口。

## 一、已执行任务

| 任务 | 实施结果 |
| --- | --- |
| 0.1 | `config/competition.json` 的 `trace_max_chars` 从 `0` 调整为 `4000`。 |
| 0.2 | Judge Trace 投影新增固定 `diagnostics` 事件，并输出 `truncation_verdicts`、`deadline_phase`、`elapsed_seconds`、`model_calls`、`prompt_tokens_avg`、`circuit_open`、`salvage_used`、`sanitizer_issues`、`error_code`。官方两字段 Trace 同步输出该诊断内容。 |
| 0.3 | `CallBudget`、`RunMetrics`、终结器、Benchmark 汇总接入 `answer_source` 与 `answer_source_counts`。本阶段只使用两态：保留候选为 `L1`，无候选兜底为 `L5`。重复记录会覆盖而不会累加。 |
| 0.4 | `max_background_model_tails` 从 `6` 调整为 `2`，并解除其必须不小于前台模型并发的错误约束；前台并发仍由配置保持为 `6`，用例并发保持为 `2`。 |
| 0.5 | 新增 20 用例本地确定性冒烟门禁，逐用例检查诊断字段并汇总答案来源计数。 |

## 二、中文化边界

- 七个角色合同正文已改为中文，Prompt Compiler 和 Skill Registry 会在每次模型输入中注入中文语言合同。
- 技能块的模型可见章节标题已中文化，并明确要求自然语言使用中文。
- JSON 字段名、角色 ID、协议版本、技能标识和数学公式保持机器兼容；它们不是自然语言答案内容。
- 公开兜底 Trace 的说明文字已改为中文；`final_response` 继续由确定性格式化器输出规范化数学答案。
- `main.py`、`llm_client.py` 未修改。

## 三、Gate 0 证据

本地 20 用例确定性冒烟结果：

```text
diagnostics step：20/20 存在且字段完整
截断诊断：20/20 可读取（每例包含 complete/suspect/truncated 计数）
answer_source_counts：L1=10，L5=10，总计=20
```

机器可读证据已保存至 `artifacts/phase0_diagnostics_gate_20260901.json`。

该冒烟测试验证的是投影、预算和终结器的闭环，不替代官方真实模型评测。此前中断的旧真实运行仅作为诊断材料保留，不能作为本阶段的准确率基线；新的真实模型证据应在后续阶段按当前提交重新生成。

## 四、验证命令

```text
pytest -q tests/test_phase0_diagnostics_answer_source.py
python scripts/verify_content_reviews.py
python scripts/validate_submission.py
```

阶段专用测试、完整回归（`1014 passed`）、内容审查校验、构建来源校验和提交校验均已通过。提交前还需执行仓库规定的完整验证：

```text
python -m compileall .
pytest -q
python scripts/verify_baseline_files.py
```

## 五、阶段结论与边界

Phase 0 的代码门禁已完成，Gate 0 已由 20 用例本地冒烟闭合，可以进入 Phase 1（时间预算与截断判定）。本阶段没有宣称数学正确率、官方平台准确率或发布冻结状态已达标；这些结论必须等待当前版本的真实全量运行、证明题复核和来源指纹闭合。
