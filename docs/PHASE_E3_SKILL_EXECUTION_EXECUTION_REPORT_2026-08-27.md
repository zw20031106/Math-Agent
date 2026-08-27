# E3 Skill 可执行化阶段执行报告（2026-08-27）

## 目标与范围

本阶段按实施计划完成 E3-T01～E3-T08 的运行时边界：Skill 选择结果必须
携带可执行计划；`requires`/`verification_hooks` 必须经过 Host 能力准入；
验证 hook 必须物化为 TaskGraph 可识别的检查节点；失败信号必须产生
SkillOutcome 并进入 alternative/fallback 或 degraded 路径；Skill 选择保留
原 rule score，同时记录离线 expected gain、token cost、能力可用性和历史
精度；V3 method Skill 经过内容质量门；Solver/Verifier 使用不同认知投影；
Skill-specific benchmark 使用五类覆盖和可观测 ON/OFF 配对评分。

## 实现映射

- `mathforge/skills/execution_plan.py`：新增 `SkillExecutionPlan`、
  `SkillCheckTask`、`SkillOutcome` 及离线 utility 计算。
- `mathforge/skills/runtime.py`：能力准入、alternative/degraded/rejected
  决策、hook task 生成、Evidence 回写和 failure-signal fallback。
- `mathforge/skills/selector.py`、`projection.py`：保留 rule score 并加入
  utility 排序，Solver 投影包含 alternative，所有决策输出公开准入/效用字段。
- `mathforge/runtime.py`、`runtime_flows/scheduler_flow.py`：Runtime trace
  记录执行计划、hook 节点、Evidence 消费、fallback/replan；自治调度图将
  hook 节点置于 Solver 与 review/verifier 之间。
- `mathforge/skills/quality.py`、`registry.py`：V3 method Skill 内容质量门，
  当前目录 51 个 method Skill 全部通过，覆盖阈值为 20。
- `mathforge/skills/evaluation.py`：五类 benchmark case taxonomy、覆盖检查和
  配对可观测结果报告；无 accuracy 正增益时给出降权/禁用建议。
- `tests/test_e3_executable_skills.py`：覆盖计划公式、能力 fallback、hook-Evidence
  绑定、质量门、五类 benchmark 和降权决策。
- `docs/content_review_manifest.json`、`data/*provenance*`：同步 E3 改动后的
  内容与治理指纹；保持 candidate-unvalidated，不伪造正式比赛证据。

## 验证结果

本报告中的验证分为两类：

1. **代码/测试证据**：`python -m compileall .` 通过；E3/受影响测试
   `29 passed in 2.02s`；完整 `pytest -q` 为 `947 passed in 146.80s`；
   `verify_baseline_files.py`、`verify_content_reviews.py`、
   `verify_build_provenance.py` 和 `validate_submission.py` 均通过。
2. **外部证据**：尚未运行真实模型 FULL 竞赛、Skill 正负/对抗样本官方评测、
   proof double review 或完整 C0-C7 消融；因此不能把本阶段单元测试结果宣称
   为数学准确率或比赛验收。

## 当前风险与回滚条件

- 选择 utility 的默认 expected gain 是无在线训练的确定性离线先验，正式权重
  仍需真实配对 benchmark 校准。
- 没有匹配 Claim 的 hook 会被显式标记为 `skipped`/incomplete，不会伪造通过；
  这可能降低部分候选的可验证性，但符合证据门要求。
- 失败信号没有可用 alternative 时保持 `degraded` 并要求 replan；不会静默沿用
  原方法。
- 若出现 accuracy、public contract、timeout 或 full-suite regression，应回滚本
  阶段提交；不修改冻结的 `main.py`、`llm_client.py` 或用户现有 `AGENTS.md`。

## 阶段状态

代码与不变量测试完成后可提交 E3 独立 commit；competition status 继续保持
`candidate-unvalidated`，等待真实 FULL run、技能消融、proof review 与 provenance
闭环证据。
