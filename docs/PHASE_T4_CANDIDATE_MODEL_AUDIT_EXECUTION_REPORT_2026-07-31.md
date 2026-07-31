# Phase T4 候选、模型调用与修复审计执行报告

日期：2026-07-31  
阶段：T4——逻辑化 Judge Trace 与完整公开审计

## 1. 阶段结论

Phase T4 已完成。Judge Trace 升级为 3.7。公开 Trace 不再只是若干运行事件的
堆叠，而是形成如下稳定叙事：

```text
公开解题过程
→ 本题实际工作流总览
→ 题意、路线与长程推理状态
→ 按调用顺序排列的固定模型角色活动
→ 所有成功候选的有界公开解法
→ Evidence / Verifier / Proof 审查
→ 必要的局部 Repair 与重新验证
→ 确定性仲裁与最终答案选择
→ 闭环健康度、预算和终态
```

字符压缩不是本阶段目标。只有重复配置、重复选中答案和无法帮助理解闭环的噪声
被省略；解题步骤、成功候选内容、验证结论、修复结果和选择依据属于核心信息。

## 2. 已实现内容

1. `trace[0]` 继续固定为 `solution_process`，给出选中解法的公开步骤和 LaTeX
   结论。
2. `trace[1]` 新增 `workflow_overview`，按题意解析、规划、候选、验证、修复、
   仲裁和最终化的顺序说明本题实际闭环。
3. `model_activity.calls` 按真实调用顺序记录角色、目的、Candidate 归属、状态、
   安全失败码、响应校验、Transport 次数、Token 与时间。
4. `candidate_summaries` 覆盖所有实际开始生成的 Candidate。选中项引用
   `trace[0]`；成功但未选中的项保留有界公开答案和公开步骤；失败项保持空内容。
5. `repair_history` 公开 claim-local 修复内容、受影响 Claim、重新验证引用以及
   接受或回滚结果。
6. `budget_summary` 只保留聚合计数，避免与 `model_activity` 重复整份调用明细。
7. Live profile 读取器兼容 Judge Trace 3.7，同时保留对旧 Trace 的读取兼容。

## 3. 安全边界

公开审计内容只来自 Candidate Schema 允许公开的字段和 Host 生成的结构化状态。
Trace 不包含模型私有思维链、Prompt、raw response、完整失败 Candidate、API 密钥、
本地绝对路径、异常正文或 traceback。失败调用仍可通过角色、Candidate ID 和安全
失败码定位。

## 4. 阶段验收

- 两个成功候选均可追踪到模型调用，未选候选的公开步骤可见；
- 选中候选只在 `solution_process` 保留一份步骤，后续使用引用；
- Alternative 调用失败时有明确归因，且不泄漏异常正文、不伪造候选内容；
- Repair 的公开修改、重新验证和接受/回滚状态可审计；
- `workflow_overview` 步骤连续且与最终 Candidate 一致；
- 极端内部事件量下仍保留首项解法、逻辑总览、决策摘要、关键闭环和最终终态；
  独立模型调用明细在竞赛默认预算中完整保留。

提交前质量门：

```text
python -m compileall .
pytest -q
python scripts/verify_baseline_files.py
python scripts/verify_content_reviews.py
python scripts/verify_build_provenance.py
```
