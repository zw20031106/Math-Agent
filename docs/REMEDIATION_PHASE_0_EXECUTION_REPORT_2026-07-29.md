# MathForge 整改阶段 0 执行报告

日期：2026-07-29  
依据：`MathForge项目全面审查报告.md`  
阶段目标：解除治理门阻塞、恢复可验证基线，并建立 F3/F4 模型调用闭环回归用例。

## 一、完成项

### G1：修复 Prompt Compiler 内容审查哈希

- 重新计算当前 `mathforge/agents/prompt_compiler.py` 的规范化 SHA-256。
- 更新 `docs/content_review_manifest.json` 中 `prompt-compiler` 审查范围的内容哈希。
- 保留 `pending-human` 状态，不伪造人工签名或人工批准。

### F3 回归骨架：有效候选在 finalize cutoff 到达时不得丢失

- 新增回归用例，模拟模型成功返回 Candidate 的同一时刻进入确定性定稿窗口。
- 验收要求：Candidate 的 `final_answer` 仍为真实答案，不得抛弃并进入通用兜底。

### F4 回归骨架：已完成响应超过角色输出软上限时保留可解析内容

- 新增回归用例，区分“超过角色输出上限”和“超过总上下文窗口”。
- 验收要求：只要完整响应仍落在模型上下文窗口内，就保留响应并记录
  `output_budget_exceeded=true`，不得把已经付费取得的有效内容直接丢弃。

## 二、验证结果

执行：

```text
pytest -q \
  tests/test_s5_governance.py::test_content_review_manifest_covers_all_scopes_but_blocks_human_freeze \
  tests/test_submission_validation.py::test_submission_validator_passes_repository \
  tests/test_phase1_model_call_loop.py::test_solver_keeps_a_valid_candidate_that_arrives_at_finalize_cutoff \
  tests/test_s6_e1_context_deadline.py::test_completed_response_over_role_cap_is_retained_when_context_still_fits
```

结果：

```text
4 passed
```

报告中记录的两个治理失败已转绿，F3/F4 闭环回归骨架均可执行。

## 三、阶段结论

阶段 0 已完成。治理内容哈希与当前 Prompt Compiler 一致，提交验证不再被
`prompt-compiler content hash mismatch` 阻塞；后续阶段可以在明确的
“有效响应不得因截止窗口或角色软上限被无条件丢弃”回归约束下继续整改。

## 四、边界与遗留项

- 本阶段未将配置状态改为 `validated`；该状态必须等阶段 4 的全量回归和真实环境验证。
- 当前工作区还包含进入阶段 1/2 的未完成代码，未在本报告中宣称验收通过。
- `main.py`、`llm_client.py` 保持冻结，未修改。
