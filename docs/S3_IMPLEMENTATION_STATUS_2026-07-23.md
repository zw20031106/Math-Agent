# S3 推理闭环与上下文隔离实施状态

日期：2026-07-23

范围：C15–C19、C23

状态：已完成工程实现与自动化验收

## 1. 验收结论

| 缺陷 | 实施结果 | 自动化验收 |
|---|---|---|
| C15 Lemma 第二轮泄漏历史候选 | 第二轮只发送原题、conditions、verified LemmaCard 和允许的公开 metadata，不发送历史 `solution_text` | 捕获真实模型 messages，断言历史私有推导不存在且原题只出现一次 |
| C16 expanded candidate 绕过重验 | 将批量 VerifierSkeptic 移到 Lemma 扩展后；扩展候选重新经过 Schema、Claim budget、answer validation、answer tool、claim evidence、obligation、Skeptic、Completion 和 Arbitration | 已审核扩展候选可进入仲裁；缺少 Skeptic finding 的扩展证明被 Completion 拒绝 |
| C17 ClaimGraph/Repair 完整性 | ClaimGraph 使用 `candidate_id::claim_id`；严格拒绝重复、悬空、自依赖和环；Repair 按原图与新图的影响闭包并集复验 | 同名跨候选 Claim 不覆盖；新增悬空依赖在复验前拒绝；依赖切换后新旧上游及下游全部复验 |
| C18 假设感知等价 | 等价检查使用宿主 ProblemIR 的 answer type、assumptions 和 domains；结果分为 equivalent/different/unknown | `x ≥ 0` 时 `sqrt(x^2)` 与 `x` 同簇；缺少定义域时为 unknown 而不是 hard disagreement |
| C19 方法独立性 | 新增受控 MethodFamily 和结构化 MethodStep；签名由步骤、定理及 Claim topology 构成，不再信任自由文本方法名 | 不同字符串但同构步骤不增加独立一致性；结构化不同方法可区分；contract deviation 不计分 |
| C23 Context/Metadata | 每个 Session 持有唯一总容量 RawContextStore；prompt 预算按真实 `to_prompt_json()` 计算；metadata 使用白名单 | 所有 raw reference 可 resolve；重复注册不重复占用；API key、路径和私有字段不会进入 messages |

## 2. 核心契约

核心 Schema 从 `1.1` 升级为 `1.2`。

新增或增强的边界对象：

- `MethodFamily`：Router 的受控方法族集合；
- `MethodStep`：版本化、可验证、可 round-trip 的结构化步骤；
- `ClaimGraph`：版本化 namespaced 图，支持严格 validate/from_dict/to_dict；
- `LemmaCard`：增加 source candidate/claim，并使用 namespaced lemma ID 和
  dependencies；
- `EvidenceRecord.transaction_status`：区分 active 与 rejected Repair
  transaction。

模型仍只能经注入的 `client.chat(...)` 调用；`main.py` 与 `llm_client.py`
未修改。

## 3. Runtime 闭环

高风险 Lemma 路径现在按以下顺序执行：

```text
Primary/Alternative
  -> answer + claim evidence
  -> initial obligations
  -> deterministic Lemma curation/verification
  -> history-free lemma expansion
  -> expanded schema/answer/claim evidence
  -> expanded obligations
  -> one batch VerifierSkeptic for original + expanded candidates
  -> ProofCompletionGate
  -> assumptions-aware equivalence and arbitration
```

`expanded_candidates_reverified` 是 judge-safe Trace 事件，记录 accepted、
rejected、skeptic reviewed 和 deterministic precheck rejection。

## 4. LemmaCurator 架构决策

`LemmaCurator` 保持确定性宿主服务，不新增模型调用。现有
`prompts/lemma_curator/contract.md` 是非活动审核模板，不代表生产链路由该
Prompt Contract 驱动。详细决策见
`docs/ADR_001_S3_DETERMINISTIC_LEMMA_CURATOR.md`。

## 5. 验证结果

- `python -m pytest -q`：219 passed；
- `python -m pytest --cov=mathforge --cov-branch --cov-report=term -q`：
  219 passed，总覆盖率 81%；
- `python -m ruff check .`：通过；
- `python -m mypy mathforge user_agent.py`：79 个源文件通过。

提交前仍执行 compileall、基线文件校验、submission 校验、依赖完整性及
`git diff --check`。

## 6. 剩余边界

- S3 不处理 C20–C22 的终态诊断、Benchmark records/置信区间及测试门禁配置；
- S3 不处理 C24–C26 的 RAG、内容审核、完整运行指纹和 MCP 生命周期；
- `config/competition.json` 继续保持 `candidate-unvalidated`，不得提前冻结。

下一阶段为 S4（C20/C21/C22）。
