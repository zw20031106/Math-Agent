# E7 Public JSON / Trace / Renderer Execution Report

日期：2026-08-28
阶段：E7（Public JSON / Trace / Renderer）
仓库：`math_agent`

## 目标与范围

本阶段按实施计划完成 E7-T01 至 E7-T06。目标是保持官方四字段输出契约，
把诊断信息与 Public JSON 解耦，并让 proof-full 的公开证明优先来自
`ProofBackbone` 与已验证 Claim，而不是对模型原始文本做字符截断。

## 已实施内容

1. `mathforge/output/public_result.py`
   - 固定 `id`、`status`、`final_response`、`trace` 四个顶层字段；内部
     `run_metrics`、`evaluation_artifact` 和输出限制不会穿透到官方结果。
   - 新增 `validate_public_result` 与 `PublicContractError`，检查字段集合、
     JSON 可序列化性、非空答案和控制字符；公共文本会在投影前做安全清理。
   - Trace 投影异常继续按官方契约 fail-closed，保留答案文本但将发布状态降为
     `failed`；输入的内部数学结果、RunMetrics 与 Evaluation Artifact 不被修改。
2. `mathforge/output/verified_proof.py` 与 `deterministic_formatter.py`
   - 新增 `VerifiedProofRenderer`、`ProofRenderResult` 和函数式入口。
   - 证明渲染顺序为 ProofBackbone → 依赖优先的 verified Claims → 简洁正文 →
     exact conclusion；覆盖不足会显式标记 incomplete，只有没有结构化验证信息
     时才回退到旧 Candidate public steps。
   - 语义压缩优先移除非关键 supporting Claim；只有所有关键单元仍超限时才使用
     exact-answer emergency fallback。
   - 根据当前正式评分契约明确固定 `worked_solution → exact answer`，并保留
     `public_process` 作为未来需正式确认时的显式策略值。
3. `mathforge/evaluation/debug_artifact.py`、Runtime、case runner
   - 新增独立 Evaluation Artifact schema/sink，记录 run metrics、provider
     telemetry、prompt snapshot、skill selection、task graph、candidate
     provenance、evidence、completion 和 failure attribution。
   - Runtime 每题生成内部 artifact，可注入内存或 JSONL sink；正式 case runner
     将其写入 `.evaluation-artifacts/<attempt>.evaluation.jsonl`，与官方逐题 JSON
     和 Trace Journal 分目录保存。
4. `mathforge/harness/trace.py` 与 Judge Trace projection
   - 增加 accuracy-first eviction policy：plan/reasoning/verification/
     arbitration/finalize 优先，repair/候选冲突/Skill outcome 次之，model
     activity 最后；在事件数或字符压力下按策略淘汰可选事件。

## E7 不变量测试

新增 `tests/test_phase_e7_public_json_renderer.py`，覆盖：

- verified Claim 依赖排序、proof coverage、未验证证明降级和 emergency 标记；
- worked-solution 策略决策与现有 scorer 行为；
- 四字段 Public Contract、控制字符回归、额外 Debug 字段拒绝；
- Trace projection failure 的 fail-closed 与内部数学结果隔离；
- Evaluation Artifact 九类诊断字段、内存/JSONL sink 和 round-trip；
- accuracy-first Trace eviction 顺序。

## 本地验证证据（诊断性）

以下结果来自仓库单元测试、Fake/Scripted Client 和静态校验，仅证明工程不变量，
不代表官方平台数学正确率或真实模型证据：

- E7 定向测试：9 passed；
- E7 相关输出/Trace/Proof Runtime 回归：29 passed；
- 完整 `pytest -q`：989 passed；
- 强制命令：`python -m compileall .`、`pytest -q`、
  `python scripts/verify_baseline_files.py`；
- 治理命令：`python scripts/verify_content_reviews.py`、
  `python scripts/verify_build_provenance.py`、`python scripts/validate_submission.py`。

## 外部证据与发布状态

本阶段没有运行真实官方 FULL competition run，也没有宣称真实模型准确率、P95、
成本或数学正确性达标。`config/competition.json` 继续保持
`candidate-unvalidated`；content review 仍需 human sign-off。逐案真实输出、
模型调用时间线、proof double review、C0-C7 ablation、clean commit 和 provenance
freeze 仍是发布候选的必要条件。

## 变更与指纹

本阶段使用一个独立提交。源码、测试、CHANGELOG 和本报告稳定后，按现有治理脚本
重新计算受影响 content/build/release 指纹；`AGENTS.md` 的已有用户修改不纳入本
阶段提交。
