# Phase 0（0729）问题—证据—测试映射

> 日期：2026-07-29  
> 范围：`MathForge_Harness全项目问题汇总与整改实施计划_2026-07-29.md`

| 问题 | 证据或测试 | Phase 0 状态 | 计划解决阶段 |
|---|---|---|---|
| T01 Primary 传输失败无恢复 | `test_primary_transport_failure_uses_the_reserved_recovery_call` | 严格 xfail，缺陷已复现 | Phase 2 |
| H01/H02 runner 强制并发 1 | `test_case_runner_accepts_and_defaults_to_concurrency_four` | 严格 xfail，缺陷已复现 | Phase 1 |
| H03 本地模型调用被全局锁串行 | `test_local_retry_wrapper_does_not_serialize_independent_model_calls` | 严格 xfail，缺陷已复现 | Phase 1 |
| V02/O02 无候选显示 proof complete | `test_no_selected_candidate_cannot_be_reported_as_proof_complete` | 严格 xfail，缺陷已复现 | Phase 4 |
| O03 路径脱敏误伤 `\int` | `test_trace_redaction_preserves_latex_commands_after_matched_prefix` | 严格 xfail，缺陷已复现 | Phase 6 |
| V01 proof obligation 依赖自报字段 | `test_proof_obligations_are_inferred_from_candidate_operations` | 严格 xfail，缺陷已复现 | Phase 4 |
| V03 unknown 触发 Repair | `test_only_actionable_verifier_failures_trigger_repair` | 严格 xfail，缺陷已复现 | Phase 4 |
| O04 Journal 重跑覆盖 | `test_trace_journal_factory_preserves_previous_attempt` | 严格 xfail，缺陷已复现 | Phase 6 |
| O05 stale running 无中断历史 | `test_resume_marks_a_stale_running_attempt_as_interrupted` | 严格 xfail，缺陷已复现 | Phase 6 |
| G02 Stub 测试缺真实响应形态 | `phase0_0729_live_regressions.json`、`test_captured_candidate_replays_remain_strictly_parseable` | 脱敏 replay 已建立 | 全阶段 |
| C25 真实证据不得含秘密 | `test_sanitized_live_fixture_preserves_regression_evidence_without_secrets` | 已通过 | 全阶段 |

说明：

- `xfail(strict=True)` 表示缺陷已稳定复现，但尚未越阶段修复。
- 当对应阶段实施时，必须先移除该测试的 xfail，再以通过状态作为最低验收。
- Fixture 只保存公开候选、稳定错误码和聚合指标，不包含 API Key、绝对路径、原始失败响应或私有思维链。
