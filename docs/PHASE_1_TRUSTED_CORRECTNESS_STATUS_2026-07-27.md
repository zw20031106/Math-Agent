# Phase 1 可信正确性主线实施状态（2026-07-27）

## 结论

状态：**Engineering Trusted-Path Passed**

P1-01 至 P1-07 已按依赖顺序完成。该结论表示工程主链已 fail-closed，
不表示真实 Intern 模型精度已达标，也不替代后续并发、judge trace、数学 IR、
治理和真实评测阶段。

## 已完成任务

| 任务 | 实施结果 | 核心验收 |
|---|---|---|
| P1-01 no-throw Terminalizer | close-invariants、proof graph、transport/case summary、final token、budget、run event、metrics、debug sink、trace build 均由终止器隔离；外层最小中文 fallback 不依赖这些服务 | 8 类终止故障及 debug sink 故障注入均返回四字段、非空答案和 list trace，原始异常不泄漏 |
| P1-02 统一 Candidate Admission | 新建确定性准入门；Primary、Alternative、Lemma-expanded、Repair-proposed 与仲裁后选中项统一执行 Schema、AnswerValidator、answer-shape 顺序 | 空答案、非法 choice/integer/fraction、answer type 不兼容及 shape 非 pass 均不得进入仲裁 |
| P1-03 Verifier 错误分类 | 仅 BudgetExceeded、ModelTransportError、ContextBudgetExceeded 视为可用性失败；TypeError、AssertionError、AttributeError 等程序缺陷进入全局 fallback | 可预期传输失败安全降级，程序缺陷不再伪装为 `verifier_unavailable` |
| P1-04 严格 Proof Completion | 删除 deterministic degraded 候选；任何题型只要存在 required obligation，就必须由匹配的 active evidence 完成 | Verifier 不可用不等于义务已满足；未完成候选不能仲裁或成功 |
| P1-05 单次后验证 Repair | 每题最多一次 Repair；为 Repair 与第二次 Verifier 原子预留两次调用；执行 finding→claim closure→patch→admission→evidence→obligation regeneration→Verifier replay→completion | 只有严格改善且完成证明的提案被接受；无改善、Verifier 不可用、证据质量下降或义务未完成均回滚；Verifier 证据始终为 soft |
| P1-06 Runtime Phase 语义 | 新增 `PRECHECKED`；`VERIFIED` 只在 Verifier/Completion 后出现；`REVERIFIED` 只在 post-Verifier Repair 完成复验后出现 | 无 Repair 成功路径不含 `REVERIFIED`；Repair 复验路径允许 `VERIFIED→REVERIFIED→ARBITRATED` |
| P1-07 集成门禁与状态 | 更新 Changelog、状态文档和回归矩阵；保持官方 baseline 不变 | 完整工程门禁通过 |

## 关键不变量

- `solve()` 的公开结果始终可 JSON 序列化，字段为
  `id/status/final_response/trace`。
- 候选只有经过确定性准入、硬证据门、required obligation completion 后
  才能进入仲裁。
- Verifier 的 soft finding 可以触发 Repair，但不能转换为硬证据。
- Repair 不得扩大到 finding 影响闭包之外；提案证据按 transaction
  active/rejected 管理，回滚后义务恢复 unresolved。
- `main.py`、`llm_client.py` 未修改。

## 门禁记录

- Phase 1 新增核心回归：18 passed。
- 全量 `pytest -q`：420 passed。
- `python -m compileall .`：通过。
- `python scripts/verify_baseline_files.py`：通过。
- `python scripts/validate_submission.py`：通过。
- `python scripts/scan_secrets.py`：通过。
- `ruff check .`：通过。
- `mypy mathforge user_agent.py` 及本阶段正式脚本：通过。
- `git diff --check`：通过。

`mypy .` 的阶段前既存问题仍限于不可变 baseline、旧测试类型标注和既有
runner；本阶段未越界修改这些无关文件。
