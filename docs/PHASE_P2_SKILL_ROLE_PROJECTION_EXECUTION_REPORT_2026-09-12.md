# Phase P2：Skill Role Projection 执行报告

日期：2026-09-12

## 范围与目标

本阶段执行 0907 Prompt/Skill 改造方案的 Phase P2，范围限定为
mathforge/skills/projection.py 的 V3 Skill 角色投影。目标是让各固定角色只
接收其决策所需的数学 Section：Solver 能核对前提和失败边界，Verifier 能
审查定理边界，RepairAgent 能执行局部闭包修复，LLMFinalizer 不接收数学
Skill。

## 已完成的实现

- PrimarySolver：recognition、do not use when、core theorem、exact
  preconditions、procedure、branch conditions、failure modes、verification
  recipe、alternative strategy、stop / escalate conditions。
- AlternativeSolver：在上述求解 Sections 基础上保留 counterexample
  patterns，并显式包含 exact preconditions，保证替代方法可以独立判断适用性。
- LemmaCurator：core theorem、exact preconditions、procedure、branch
  conditions、stop / escalate conditions。
- VerifierSkeptic：do not use when、core theorem、exact preconditions、
  failure modes、counterexample patterns、verification recipe、stop /
  escalate conditions。
- RepairAgent：do not use when、exact preconditions、procedure、branch
  conditions、failure modes、verification recipe、alternative strategy、stop /
  escalate conditions。
- LLMFinalizer：空投影，不接收数学 Skill；投影函数在无选中 Section 时返回
  空文本，避免只留下 Skill 标题。

投影函数的选中/省略返回值和既有 V3 SkillPackage 结构保持不变；没有升级
Skill schema，没有改变 selector 的准入、排序或 legacy V2 分支。

## 验证结果

- 新增 P2 映射不变量测试，验证六个角色的完整顺序和三项关键边界；
- Prompt、Skill 选择器、E3 执行化和编译快照相关测试共 14 项通过；
- python -m compileall . 通过；
- python scripts/verify_baseline_files.py 通过；
- 最近一次全套 pytest -q 为 1046 passed，剩余 2 项为历史
  docs/content_review_manifest.json 内容 hash 不一致导致的治理阻塞，
  不涉及 P2 代码断言。

## 证据边界与后续

本阶段只有代码和离线测试证据，未运行真实 Intern 模型、官方题集或 Skill
正/负/对抗消融，因此不宣称准确率提升。后续 Skill schema optional metadata、
高风险 Skill 审计和真实 ON/OFF benchmark 应在后续计划阶段执行。
