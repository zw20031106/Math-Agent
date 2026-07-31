# Phase T3 Solution Process Trace 执行报告

日期：2026-07-31  
阶段：T3——解题过程优先的 Judge Trace 3.6

## 1. 阶段结论

Phase T3 已完成。公共 Judge Trace 已升级到 3.6，`trace[0]` 现在固定为
`solution_process`。对于成功题目，该事件直接给出选中候选的公开方法、分步
解题过程、response mode 和 LaTeX 结论；对于失败或超时题目，首事件明确标记
为 `unavailable`，不伪造推理。

内部 Debug Trace 和逐阶段 Trace Journal 保持原有时间顺序与完整诊断信息。

## 2. 首事件契约

```json
{
  "event": "solution_process",
  "status": "complete",
  "response_mode": "answer_only",
  "candidate_id": "primary-1",
  "method": "direct-analytic",
  "steps": ["..."],
  "conclusion": "$...$"
}
```

完整性校验新增：

- `solution_process` 必须且只能出现一次；
- 必须为公共 Trace 第一项；
- 成功结果必须包含非空步骤与结论；
- 其 Candidate ID 必须与最终选择一致；
- `run_completed` 仍必须为最后一项。

## 3. 语义精简

1. 公共 Trace 不再复制约 2 KB 的完整 `effective_config_snapshot`；配置哈希和
   模型来源仍保留在 `session_started`。
2. `skills_selected` 只保留实际选中的 Skill、角色、原因、排序和评分，不再
   输出约 10 KB 的未选 Skill 目录及片段清单。
3. `final_answer_selected` 使用 `solution_process_ref: "trace[0]"`，不重复首项
   的解题步骤。
4. `problem_parsed` 增加 T1 的 `response_mode`。

离线同构样本的公共 Trace 从旧结构约 24.5 KB 基线降到约 13.2 KB，降幅约
46%，同时保留 Evidence、Proof、仲裁、闭环健康、预算和终态信息。

## 4. 安全边界

`solution_process` 只使用 Candidate Schema 中允许公开的
`public_solution_steps`，不输出原始模型响应、prompt、`solution_text` 字段、
私有思维链、密钥、绝对路径或异常栈。

## 5. 验证

覆盖以下专项测试：

- 成功题首事件及候选一致性；
- Fallback 首事件安全状态；
- Skill 和配置噪声删除；
- Trace 幂等投影；
- Schema 3.6、配置哈希、模型来源、超时和安全回归。

提交前执行：

```text
python -m compileall .
pytest -q
python scripts/verify_baseline_files.py
```
