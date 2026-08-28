# E6 Verification / Repair / Arbitration Execution Report

日期：2026-08-28
阶段：E6（Verification / Repair / Arbitration）
仓库：`math_agent`

## 目标与范围

本阶段按实施计划完成 E6-T01 至 E6-T09。重点是把“未被否证”和“已被硬证据
验证”拆成不可混淆的状态，令完成门、答案一致性、候选独立性、反驳/修复、最终
审计和证据失败分类共享同一套 Host-owned deterministic 语义。

## 已实施内容

1. `mathforge/verification/e6.py`
   - 新增 `VerificationState`，显式记录 `schema_valid`、`answer_shape_valid`、
     `not_disproved`、`semantically_supported`、`hard_verified` 和 `audited`；
     `hard_verified` 必须有正向语义支持，不能由 `not_disproved` 单独推导。
   - 新增 `CompletionPolicy`，按 `response_mode × risk_level` 实施 answer-only、
     worked-solution 和 proof-full 的完成/ best-available 规则。
   - 新增 `AnswerConsistency`，贯通 Candidate final answer、terminal Claim、工具
     结果、proof conclusion、formatter/scorer normalization；确定性不一致会进入
     仲裁硬失败排序。
   - 新增 `CognitiveProvenance`、`AtomicRepairClosure`、`FinalAuditCoverage`，以及
     E6 证据状态 taxonomy 和修复分类 API。
2. `mathforge/harness/schemas.py`、`mathforge/harness/repair.py`
   - Candidate 增加 Host provenance：method family、shared/private context、Skill、
     lemma、proof backbone、model/prompt、branch 等字段；修复版本完整继承这些字段。
3. `mathforge/verification/candidate_pool.py`、`arbitration.py`
   - 候选池保存 provenance 并执行严格认知独立性门；相同或不可区分的模型身份、
     共享 private context、共享未验证 lemma/proof backbone 不计入 independent
     corroboration。测试配置的兼容模式不会改变 competition profile 的严格规则。
   - Arbitration 使用真实答案一致性和风险完成策略；不一致 Candidate 不能靠
     weighted score、model vote 或 digest 成为优先候选。
4. `mathforge/verification/review_repair_audit_v2.py`、`verification_closure.py`
   - warning/info 让步保持 challenged，error 进入 repair_requested，critical 在
     独立确认前不得直接 reject；补充五类 Host repair error classifier 和规范动作。
   - Final Audit 覆盖检查同时要求 required artifacts/findings/obligations 完整、无
     open 项且 Candidate version 等于 active version。
5. `mathforge/verification/evidence.py`、`tools/registry.py`、Runtime
   - 工具/Verifier 结果提供 `PASS/FAIL/UNKNOWN/UNSUPPORTED/MALFORMED/TIMEOUT/
     INTERNAL_ERROR` taxonomy；只有 capability-matched 的真实 hard PASS 才能成为
     hard evidence。
   - Runtime 在 RepairAgent 启动前原子预留 repair + reverify + final audit +
     deterministic finalize reserve，并把准入/保留旧 Candidate/best-available 状态
     写入公开 trace；ProofStage 和 final audit trace 使用 E6 policy/coverage。

## E6 不变量测试

新增 `tests/test_phase_e6_verification_repair_arbitration.py`，覆盖：

- VerificationState 的状态分离与正向 hard verification 约束；
- 三种 response/risk completion policy；
- terminal/tool/proof/formatter/scorer 答案一致性；
- 同模型相关证据、不同模型低相关上下文 corroboration；
- concession 状态迁移与 critical 独立确认；
- 五类修复分类、原子三阶段闭环和 final audit coverage；
- 证据失败 taxonomy 与 capability-matched hard PASS。

## 本地验证证据（诊断性）

以下证据来自仓库单元测试、Fake/Scripted Client 和静态校验，仅证明工程不变量，
不代表官方平台数学正确率或真实模型证据：

- E6 新增测试：10 passed；
- E6 相关验证/修复/仲裁/Runtime 回归：通过；
- 完整 `pytest -q`：980 passed；
- 强制命令：`python -m compileall .`、`pytest -q`、
  `python scripts/verify_baseline_files.py`；
- 治理命令：`python scripts/verify_content_reviews.py`、
  `python scripts/verify_build_provenance.py`、`python scripts/validate_submission.py`；
  strict release validation 仍按证据治理状态执行，不以手工 manifest 修改冒充冻结。

## 外部证据与发布状态

本阶段没有运行真实官方 FULL competition run，也没有宣称真实模型准确率、P95、
成本或数学正确性达标。`config/competition.json` 继续保持
`candidate-unvalidated`；content review 仍需 human sign-off。逐案真实输出、模型
调用时间线、proof double review、C0-C7 ablation、clean commit 和 provenance
freeze 仍是发布候选的必要条件。

## 变更与指纹

本阶段使用一个独立提交。治理指纹在最终代码与文档稳定后重新计算并写入现有
release/build provenance 链；`AGENTS.md` 的已有用户修改不纳入本阶段提交。
