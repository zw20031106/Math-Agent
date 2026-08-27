# Math-Agent E2：Prompt 与 Structured Output 减负执行报告

## 1. 执行结论

E2 已按 2026-08-27 实施计划完成实现与确定性验收。本阶段未修改冻结的
`main.py` 或 `llm_client.py`，并保持 `ReasoningAgent.solve(problem, metadata)`
返回非空 `final_response` 与列表型 `trace` 的公开契约。`competition` 配置仍为
`candidate-unvalidated`；本报告中的测试、快照和本地 Fake Client 证据不替代真实
模型 FULL run、官方平台评分或人工数学复核。

## 2. E2-T01/T02：模型语义与 Candidate 负载

- `ModelSemanticPayload` 将 `final_answer` 与 `solution_text` 作为最小必需字段，
  proof 模式按需支持有序 `proof_steps`、`critical_claims` 与 `open_conditions`。
- Host-owned 的 ID、版本、状态、优先级、预算和超时字段递归拒绝，Host 在解析后
  负责 Candidate/Claim/Artifact 生命周期元数据。
- 旧的 1.0 Candidate Profile 保留为兼容默认；E2 语义 Profile 通过显式参数启用，
  不重复发送完整 Candidate/ClaimGraph/公开解答三份数学文本。

## 3. E2-T03/T04：lite Envelope 与简单题直出

- 新增 `AgentTurnPayload 1.1-lite`，模型只输出 `action`、`payload`、`outbound`、
  `stop_reason`；Host 生成协议版本、结果类型、ID、进度摘要和默认空字段。
- P0（1.0）与 P1（1.1-lite）记录 JSON valid rate、截断率、准确率、输出 token
  和延迟；只有 P1 同时满足非回退且存在严格改善时才标记迁移资格。生产默认仍兼容
  P0，Provider 偶发返回 P0 envelope 时有显式兼容降级。
- 新增 `enable_simple_direct_candidate` 配置开关。对 calculation/fill_blank/MC，
  仅在风险非 high、无实质歧义、无长程需求时将候选数压到 1，跳过 ProgressArtifact
  与 exploration wave；该路径仍经 RouterPlanner 和 Candidate/证据边界。

## 4. E2-T05/T06：Prompt 快照与 token 遥测

- `CompiledPromptSnapshot` 保存 role/mode、合同版本和 hash、协议版本、输出 schema、
  selected skill 摘要及 max output cap，不保存答案或模型私有推理。
- `tests/fixtures/e2_compiled_prompt_snapshots.json` 固化各固定角色与 Solver
  candidate/progress lite 模式；合同 hash 改变而 Prompt hash 不变时，golden binding
  断言失败。
- `PromptCompilation`、`CallBudget` 与 `RunMetrics` 记录：
  `contract_tokens`、`runtime_protocol_tokens`、`skill_tokens`、`state_tokens`、
  `problem_tokens`、`schema_tokens`。Router、Solver、Peer Review、Verification
  Closure、Lemma、Repair、Verifier 和 Finalizer 的编译调用均把同一组分解写入
  `CallBudget`。这些是 A/B 分析遥测，不作为数学正确性的硬门槛。

## 5. 确定性验收

本阶段新增 `tests/test_e2_prompt_structured_output.py`，覆盖语义负载 Host 字段
隔离、lite 严格解析与 P0 兼容、AB 迁移门槛、简单题单 Solver call、Prompt golden
快照、合同绑定和 token 组件遥测。提交前执行以下命令，最终输出为：

```text
python -m compileall .
pytest -q
python scripts/verify_baseline_files.py
python scripts/verify_content_reviews.py
python scripts/verify_build_provenance.py
python scripts/validate_submission.py
```

```text
pytest -q: 942 passed in 143.20s (0:02:23)
python scripts/verify_baseline_files.py: Official immutable baseline files verified.
python scripts/verify_content_reviews.py: Content review manifest verified.
python scripts/verify_build_provenance.py: Build provenance manifest verified.
python scripts/validate_submission.py: Submission validation passed.
```

测试结果仅代表仓库内确定性/模拟客户端证据；真实模型准确率、延迟、成本、P95、
截断率和官方竞赛结果仍待后续 FULL run 与 C0–C7/组件消融门禁。

## 6. 后续门禁

不得仅凭本阶段本地绿灯把 competition 状态改为 `frozen`。仍须完成真实 FULL run、
组件消融、invalid/timeout/P95/cost gates、证明双评（冲突时第三评审）及完整
provenance/release 检查。
