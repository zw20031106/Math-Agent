# Phase 3 Judge Trace 与输出治理实施状态

日期：2026-07-27

范围：P3-01 至 P3-04

## 结论

Phase 3 已完成。正式入口 `ReasoningAgent.solve()` 只返回四字段公共结果，
其中 `trace` 为 Judge Trace V3；内部 Harness 仍使用完整 Trace V2 完成运行时
交叉校验，本地增量 journal 则记录独立版本的脱敏 Debug Trace。三种用途不再
复用同一输出流。

## 已实施

1. 新增 Judge Trace V3 的显式事件白名单、阶段映射、投影器和完整性校验器。
2. Judge Trace 只保留：

   - 会话、配置、路由和 Skill 摘要；
   - 选中 Candidate 的必要公开步骤与最终答案；
   - evidence、proof completion 和仲裁结论；
   - fallback、timeout、预算及最终状态。

3. 未选 Candidate 固定为七字段摘要：
   `candidate_id`、`role`、`method_family`、`status`、`content_digest`、
   `rejection_category`、`evidence_summary`。
4. 未选 Candidate 的 `final_answer`、`solution_text`、
   `public_solution_steps` 和完整 Claims 不进入公共结果。
5. 选中事件不重复保存 `final_response`，而是记录其 SHA-256 摘要；公开校验会
   拒绝投影完成后被替换的最终回答。
6. 最终输出同时执行：

   - 缩进 UTF-8 JSON 总字节预算；
   - Judge Trace 总事件数预算；
   - Judge Trace 总字符预算；
   - 单事件字符预算；
   - 未选 Candidate 摘要数量预算。

7. 超限内容转换为带类型、数量和内容摘要的结构化记录，不执行破坏 JSON 的
   任意字符串截断。
8. `final_answer_selected`、`proof_completion_summary`、
   `evidence_summary`、`candidate_arbitrated`、终态、预算和
   `run_completed` 均为受保护事件。
9. 本地 journal 接收全部脱敏 Debug 事件；正式返回值不包含 Debug Journal、
   provider 原始响应、私有推理、secret、绝对路径或 traceback。
10. Competition 配置 Schema 升级至 `1.4`，命名配置均显式声明输出预算。

## Competition 输出预算

- `public_result_max_bytes = 4,000,000`
- `judge_trace_max_events = 64`
- `judge_trace_max_chars = 196,608`
- `judge_trace_event_max_chars = 16,384`
- `candidate_summary_max_count = 8`

这些值约束的是最终公共工件，不改变内部题内 Trace 的证明、Evidence 或
Candidate 信息保真度。

## 对抗验收覆盖

- 两个互相冲突的 Candidate，验证未选答案不泄漏；
- 超长证明与 64 Claims；
- 4,096 个内部事件的有界、快速投影；
- secret-like 字符串、Windows/Linux 绝对路径、traceback、
  `raw_response` 和 `candidate_text`；
- fallback、timeout 和外层异常；
- JSON round-trip、输出字节上限、事件上限和单事件上限；
- Judge Trace 与 `final_response` 摘要一致性；
- 已投影 Judge Trace 的幂等公共封装。

## 质量门结果

- `pytest -q`：438 passed；
- 分支覆盖率：82.90%，项目 80% 总门槛和全部关键文件门槛通过；
- `ruff check .`：通过；
- `mypy mathforge user_agent.py`：103 个源文件通过；
- `python -m compileall .`：通过；
- `python scripts/verify_baseline_files.py`：冻结文件通过；
- `python scripts/validate_submission.py`：通过；
- `python scripts/scan_secrets.py`：通过；
- `python scripts/verify_content_reviews.py`：通过；
- `git diff --check`：通过。

## 边界说明

`MathForgeHarness.solve()` 是内部诊断与评测接口，因此仍返回经过 Trace V2
校验的内部结果；正式比赛公共契约由根目录 `user_agent.py` 暴露，并在返回前
唯一执行 Judge Trace V3 projection。此边界保留了内部可审计能力，同时确保
judger 永远收不到 Debug Journal 或冲突答案正文。
