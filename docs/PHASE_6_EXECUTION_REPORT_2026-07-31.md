# Phase 6 执行报告：验证、交叉审阅与原子修复闭环

日期：2026-07-31
依据：`MATHFORGE_FULL_PROJECT_STABILITY_ACCURACY_AND_LONG_HORIZON_AUDIT_2026-07-30.md`

## 1. 阶段结论

Phase 6 已完成。当前 Harness 已形成以下稳定闭环：

```text
ProblemIR
  → Solver 前题目级 Proof Obligations
  → Primary / Alternative 公开 Candidate
  → Claim 绑定与方法级义务补充
  → 本地 Hard Evidence + Candidate Conflict Matrix
  → Claim-linked Verifier 定向审阅
  → 证据层级与确定性 Arbitration
  → 证据触发的 Claim-local Repair
  → 原子 Reverify + commit/rollback
  → stable final_response + Judge Trace 3.5
```

本阶段没有修改冻结的 `main.py` 和 `llm_client.py`，没有创建额外在线模型
Client，没有读取 API Key 或模型环境变量。所有模型调用仍只通过注入的
`client.chat(messages, temperature, max_tokens)`。

## 2. 已完成内容

### 2.1 Solver 前题目级 Proof Obligations

- `ProofObligationEngine.plan_problem()` 在任何 Solver 调用前，根据 ProblemIR
  生成题目级义务。
- Candidate 产生后，题目级义务绑定到实际 Claim，并追加定理前提、边界、
  交换极限/求和/积分次序等方法级义务。
- `ProofObligation.origin` 区分 `problem` 和 `method` 来源。
- Primary 和 Alternative 的 Prompt Contract 显式要求用公开 Claim 和解答
  步骤覆盖 Host 预先规划的义务。

### 2.2 可审阅的公开解答切片

- Verifier 不再只接收候选摘要，也不接收私有 `solution_text`。
- Host 从 `public_solution_steps + MethodStep.claim_ids` 构造有界的
  Claim-linked `review_segments`；没有公开步骤时，使用公开 Claim statement
  作为保守回退。
- Verifier 角色视图采用显式白名单，仅保留实际使用的 Candidate 字段，并
  移除重复公开步骤和 ClaimGraph。
- 该白名单修复了 Lemma 扩展场景中 Verifier 上下文仅超预算 24 字符而被
  错误跳过的问题，没有提高角色上下文上限。

### 2.3 Candidate 冲突定向审阅

- `CandidateConflictMatrix` 继续记录答案、方法、假设和义务差异，并新增关键
  Claim 冲突。
- 答案冲突生成 answer-level review target；假设、关键 Claim 或义务冲突
  生成 claim-level review target。
- 不把“不同方法使用不同表述”直接当成关键 Claim 冲突；同答案的正交方法
  可以形成独立互证，不会因文本不同被无条件送入收紧审阅。
- Verifier Finding 必须引用真实 Candidate/Claim/Obligation/ReviewTarget；
  Host 校正 `review_level`，并在 Trace 中记录 expected/reviewed/unreviewed
  target。
- 结构上没有可审阅 Claim 映射、也没有冲突 target 时，Verifier 不发起无效
  模型调用。

### 2.4 证据层级与 Proof Completion

当前明确区分：

1. `hard_evidence`；
2. `independent_corroboration`；
3. `model_review`；
4. `not_required`；
5. `incomplete`。

软 Verifier `pass` 只把义务标记为 `reviewed`，Completion 状态为
`model_reviewed`，不会再把义务标记为硬 `satisfied` 或把 Proof 伪装成
`complete`。只有映射正确、能力匹配的硬 Evidence 才能关闭硬证明义务。

### 2.5 确定性 Arbitration

- 排名顺序由硬失败、证据层级、必需义务覆盖率、答案一致性、独立方法互证、
  定向审阅支持和软分数组成。
- 两个不同方法得到同一答案时，独立互证优先于一个无证据的冲突答案。
- 实质排名完全相同时，使用公开 Candidate 内容的 SHA-256 摘要破局，不再
  使用生成顺序。
- 可选 LLM Arbiter 只能在实质并列候选集合内选择，不能绕过硬 Evidence
  排名。

### 2.6 原子 Repair/Reverify 与稳定回退

- Post-Verifier Repair 只有在 Repair 与 Reverify 的模型调用额度和阶段时间
  均可一次性预留时才启动。
- Repair 仍是 Claim-local、版本化 Patch，只能修改失败 Claim 的依赖影响
  闭包。
- 修复候选必须通过 Candidate Admission、本地重验证、再次 Verifier 审阅和
  严格质量比较。
- 重验证缺失、Verifier 不可用、Evidence 质量下降、未严格改善或仍有硬失败
  时，选择原 Candidate，并把新 Evidence 事务标记为 `rejected`。
- 原 Candidate 的稳定答案不会因修复失败而被覆盖。

### 2.7 Trace、配置快照与治理

- Judge Trace 升级为 3.5，新增题目级义务、Verifier target 覆盖、Proof
  evidence tier、确定性 tie-break 和修复闭环投影。
- Effective Config Snapshot 升级为 1.2，公开前置义务、Claim-linked 审阅、
  证据层级、软审阅非硬完成以及原子修复策略。
- `closed_loop_health` 将未审阅冲突、仅模型审阅证明和不完整 Proof 反映为
  降级原因，但不因此删除已有稳定答案。
- Prompt Contract 版本更新为 Primary 5、Alternative 3、Verifier 3。
- 内容审查清单新增 `verification-closure` 范围，并同步构建来源哈希。

## 3. 验收结果

| 验收项 | 结果 | 自动化证据 |
|---|---|---|
| Solver 前生成题目级义务 | 通过 | Phase 6 专项测试与 Runtime Trace |
| Candidate 后绑定实际 Claim 并追加方法义务 | 通过 | `test_problem_obligations_are_planned_before_and_bound_after_candidate` |
| Verifier 获得 Claim-linked 公开解答且无私有解答泄漏 | 通过 | Verifier、Context 和 Phase 6 专项测试 |
| 无结构可审阅内容时不调用 Verifier | 通过 | `test_verifier_skips_structurally_unreviewable_obligation_without_model_call` |
| 答案/Claim 冲突生成定向 review target | 通过 | Cross-review 与 Verifier 专项测试 |
| 软审阅不构成硬 Proof complete | 通过 | `test_mapped_skeptic_pass_is_model_reviewed_but_not_hard_complete` |
| 冲突答案不按生成顺序选择 | 通过 | 定向审阅与反转输入顺序测试 |
| 独立互证优先于无证据冲突答案 | 通过 | `test_independent_method_agreement_beats_uncorroborated_conflict` |
| Repair 无原子调用对时不启动 | 通过 | `test_runtime_does_not_start_repair_without_atomic_call_pair` |
| Repair 失败保留原 Candidate 并拒绝新 Evidence | 通过 | Atomic rollback 专项测试与历史 Repair 回归 |
| Judge Trace 3.5 有界且无私密内容 | 通过 | Phase 6 专项投影测试与全量 Trace 回归 |
| Lemma 扩展候选仍能在预算内批量复审 | 通过 | `test_lemma_second_round_is_history_free_and_expanded_candidate_is_batch_reviewed` |

## 4. 自动化验证

```text
python -m compileall -q .                  passed
pytest -q                                  613 passed in 144.60s
python scripts/verify_baseline_files.py    passed
python scripts/verify_content_reviews.py   passed
python scripts/verify_build_provenance.py  passed
python scripts/validate_submission.py      passed with two expected freeze warnings
python scripts/scan_secrets.py             passed
git diff --check                          passed
```

`validate_submission.py` 保留两项预期治理警告：

- Competition 配置仍为 `candidate-unvalidated`，尚未由真实模型 A/B 冻结；
- 数学内容目前只有工程审查，正式冻结前仍需人工签名。

这两项不是 Phase 6 实现失败，也没有通过伪造签名或修改配置状态来消除。

## 5. 文件与契约变更

主要生产文件：

- `mathforge/verification/proof_obligations.py`
- `mathforge/verification/cross_review.py`
- `mathforge/agents/verifier.py`
- `mathforge/context/views.py`
- `mathforge/context/compressor.py`
- `mathforge/verification/completion.py`
- `mathforge/verification/arbitration.py`
- `mathforge/harness/repair.py`
- `mathforge/runtime.py`
- `mathforge/output/judge_trace.py`
- `mathforge/output/loop_health.py`
- `mathforge/harness/effective_config.py`

新增专项测试：

- `tests/test_phase6_0730_verification_cross_review_repair.py`

同步文档与治理：

- `CHANGELOG.md`
- `docs/PUBLIC_OUTPUT_CONTRACT.md`
- `docs/FILE_MODULE_COMPONENT_CALL_MAP_2026-07-25.md`
- `docs/content_review_manifest.json`
- `data/build_provenance_manifest.json`

## 6. 阶段边界

Phase 6 的结论是离线确定性实现与回归已完成，不等同于真实
Intern-S2-Preview-397B 数据集准确率、额外调用收益和 p95 延迟已经冻结。
正式 Competition 配置仍应保持 `candidate-unvalidated`。后续真实模型验证
应继续使用官方注入 Client，在断外网 Docker 条件下做并发 1/2/4、
简单到一般高难度题的对照，并分别统计：

- 稳定答案产出率；
- 正确率和独立互证增益；
- Verifier target 覆盖率；
- Repair 触发率、接受率与回滚率；
- 每题模型调用数和 p50/p95 延迟；
- `model_reviewed`、`incomplete` 与硬 `complete` 的分布。
