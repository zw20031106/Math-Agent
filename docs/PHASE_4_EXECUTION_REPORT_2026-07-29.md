# Phase 4 执行报告

日期：2026-07-29

## 执行范围

本阶段严格覆盖整改计划 Phase 4：预算感知的候选生成、候选冲突联合审阅、证明义务推断、验证四态、可执行修复门控、原子修复预算及确定性收口。

## 已完成内容

1. 新增 `AdaptiveFanoutPolicy`，在 Primary 返回后依据风险、解析质量、未决义务、影子一致性、剩余调用预算及必需阶段预留重新计算候选数。
2. 候选总数最多为 3，Alternative 最多为 2；低风险且严格解析、闭环完整的 Primary 不再产生无收益分支。
3. 建立候选公共摘要与冲突矩阵，Verifier 对全部候选进行一次联合交叉审阅。
4. 从公开步骤、方法操作、定理应用、交换次序、边界条件及假设中生成证明义务；不存在选中候选时证明摘要明确为 `not_available`。
5. Verifier trace 统一输出 `pass`、`fail`、`unknown`、`unavailable` 四态。
6. `unknown`、不可定位或缺少可执行描述的 finding 不触发修复。
7. 修复前要求同时保留一次 Repair 与一次 Reverify 调用预算；修复仅在硬证据严格改善时接受，否则回滚。
8. 单个低风险可用候选采用确定性收口；只有候选数不少于 2 时才进入仲裁。
9. 仲裁保持“硬证据门控优先、字典序规则优先、加权分数仅作最终平局项”的既有约束。

## 关键文件

- `mathforge/harness/adaptive_fanout.py`
- `mathforge/harness/orchestration.py`
- `mathforge/verification/cross_review.py`
- `mathforge/verification/proof_obligations.py`
- `mathforge/verification/repair_scope.py`
- `mathforge/agents/verifier.py`
- `mathforge/output/judge_trace.py`
- `mathforge/runtime.py`
- `tests/test_phase4_0729_adaptive_closed_loop.py`

## 验收结果

定向命令：

```text
pytest -q tests/test_phase0_0729_regressions.py tests/test_phase4_0729_adaptive_closed_loop.py tests/test_orchestration.py tests/test_proof_runtime.py tests/test_repair_runtime.py
```

结果：`24 passed, 3 xfailed`。

3 个 `xfail` 均为计划中明确归属 Phase 6 的历史 trace 保留与 Windows 路径脱敏问题，不属于 Phase 4 验收失败。

## 风险与边界

- 本阶段未调用真实在线模型。
- 未修改基线文件 `main.py`、`llm_client.py`。
- 工作区包含进入本阶段前已有的未提交改动，因此本阶段没有把混合状态伪装为独立提交；待全阶段验收后再按可追溯边界处理版本控制。

## 结论

Phase 4 的代码项与定向验收项已完成，可以进入 Phase 5。
