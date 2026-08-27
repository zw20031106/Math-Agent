# E4 Stateful Long-Horizon 与 Truncation 阶段执行报告（2026-08-27）

## 目标与范围

本阶段按实施计划完成 E4-T01～E4-T10：截断响应分类、公开 checkpoint
恢复、候选状态重建、应急答案降级、恢复答案证据门、Host-managed
VerifiedFactBank、ProofBackbone、Host 依赖推断以及语义 information-gain
停滞判定。恢复链路只使用公开协议字段和 `ReasoningState`，不保存、重建或
回传私有 chain-of-thought。

## 实现映射

- `mathforge/harness/truncation.py`：新增 `TruncationAssessment` 四态分类、
  `CheckpointCursor`/`CheckpointStore`、`VerifiedFactBank`、`ProofBackbone`、
  `HostInferredDependencies`、`RecoveredAnswerGate` 和加权
  `InformationGainScorer`。
- `mathforge/runtime.py`：每个 Solver 分支建立公开初始 checkpoint；成功
  Progress commit 后更新 cursor；截断 Progress 丢弃未提交 delta、恢复最近
  checkpoint 并继续同一 frontier；候选恢复携带 checkpoint、事实库和 proof
  backbone；应急答案只在长视野闭合窗口内且无可用候选时调用，并单独统计
  assurance。
- `mathforge/agents/solver.py`、`mathforge/parsing/solution_parser.py`：Progress/Candidate
  记录截断证据；结构性 Candidate 截断从公开状态重建 compact Candidate；有
  checkpoint 时禁止退化为原题 answer-only 重试；无状态的旧兼容调用仍保留
  原有 salvage 行为，并将 answer salvage/emergency 标记为 Host-owned assurance。
- `mathforge/harness/reasoning_state.py`、`schemas.py`、
  `model_candidate_contract.py`：压缩保留事实库/ProofBackbone，Candidate
  增加 Host-owned assurance，模型不能伪造该字段。
- `mathforge/agent_runtime/autonomy.py`、`harness/events.py`、
  `output/_judge_trace_projection.py`、`harness/orchestration.py`：将语义
  增益、截断、checkpoint、恢复、事实晋升、骨干更新和恢复门决策写入公开
  trace，并在候选内容/终态中保留 assurance。
- `tests/test_phase_e4_long_horizon_recovery.py`：覆盖四态截断证据、checkpoint
  回滚、恢复上下文、候选状态重建、直接执行器截断恢复、应急窗口、恢复答案
  证据门、事实库单调性/GC、ProofBackbone/依赖推断、answer-salvage assurance
  和信息增益权重。

## 验证结果

本报告中的验证分为两类：

1. **代码/测试证据**：`python -m compileall .` 通过；E4 新增与受影响回归
   测试通过；最终 `pytest -q`：`960 passed in 147.62s (0:02:27)`；
   `verify_baseline_files.py`、`verify_content_reviews.py`、
   `verify_build_provenance.py` 和 `validate_submission.py` 按阶段要求执行。
   另以注入的 Scripted/Fake Client 做了 round1 成功、round2 截断、round3
   checkpoint resume 的本地诊断，确认恢复输入包含 checkpoint 版本和公开
   frontier；该诊断不是真实模型或官方平台证据。
2. **外部证据**：尚未运行真实模型 FULL 竞赛、官方数学评分、C0-C7 消融、
   proof double review、P95/成本门或正式发布冻结。因此本阶段结果不能宣称
   数学准确率提升或比赛验收通过，competition status 继续保持
   `candidate-unvalidated`。

## 当前风险与回滚条件

- `PROBABLE_TRUNCATION` 的完整结构响应仍走兼容路径；只有结构性损坏才强制
  状态重建，以免破坏既有 simple-direct Candidate 合同。
- `answer_salvaged`/`provisional` 必须获得 deterministic hard pass、独立等价
  Candidate 或 compact fresh confirmation；高风险/证明题不能直接成为 winner。
- 事实库和 proof backbone 是每题分支内存，checkpoint 有界为最近两个；若
  真实运行显示上下文超预算、恢复候选未经验证进入终局、截断后状态重复提交、
  或旧阶段测试/公共 JSON 回归，应回滚本阶段提交并重新校准策略。
- 不修改冻结的 `main.py`、`llm_client.py` 或用户已有 `AGENTS.md` 改动。

## 阶段状态

E4 实现与不变量测试完成后建立一个独立 phase commit。治理指纹随最终文件
内容同步，正式 FULL/官方证据仍待后续阶段收集。
