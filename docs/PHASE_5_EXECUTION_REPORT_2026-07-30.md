# Phase 5 执行报告：动态 Skill、工具反馈与知识闭环

日期：2026-07-30
依据：`MATHFORGE_FULL_PROJECT_STABILITY_ACCURACY_AND_LONG_HORIZON_AUDIT_2026-07-30.md`

## 1. 阶段结论

Phase 5 已完成。项目已把原有的静态 Skill 拼接和候选后置工具检查扩展为一个
问题内、Host 中介、可继续推理的闭环：

```text
ProblemIR + Subgoal/Obligation + FailureCode
  → 动态选择角色级 Skill 片段
  → Primary 输出公开 Claim + check_type
  → Host 构造 typed CheckSpec / ToolWorkItem
  → 本地 ToolExecutor
  → PublicToolResult
  → 更新 ReasoningState 的 Evidence、矛盾和策略
  → continue / synthesize
  → typed Claim / Lemma reuse
  → 原 Evidence / Proof / Arbitration / Output
```

不可构造的工具参数不会淘汰 Candidate，也不会把整题错误标记为失败，而是形成
`unknown` 工具结果并保留稳定答案路径。工具硬失败可以改变下一轮公开策略，
但不能绕过后续 Evidence、Proof 和仲裁。

本阶段没有修改冻结的 `main.py` 和 `llm_client.py`，没有创建额外在线客户端、
读取 API Key、添加模型环境变量或依赖原生 function calling。所有模型调用仍
只通过注入的 `client.chat(messages, temperature, max_tokens)`。

## 2. 已完成内容

### 2.1 动态 Skill 片段

新增 `DynamicSkillSelector`，其输入仅为公开且题内的数据：

- ProblemIR 的学科、目标、假设、约束和路由种子；
- 当前开放的 Subgoal 与 Proof Obligation；
- 已公开的工具结果和安全 FailureCode；
- 当前角色与字符预算。

选择器按角色提取 Skill 的必要章节，而不是把整份 Skill 无条件拼入 Prompt。
每次选择均记录 included/omitted、rank、score、included sections 和 reason。
工具失败后可重新选择 Primary 的 Skill 片段，下一轮 Prompt 使用更新后的组合。

### 2.2 Host-owned Candidate CheckSpec

新增版本化 `CheckSpec 1.0`，包含：

- `tool_name`；
- Host 构造并经工具 Schema 校验的 `arguments`；
- `ready/unsupported/route_not_selected/argument_unavailable/schema_invalid`
  状态；
- 稳定原因码。

模型仍只提出 Claim 的 `check_type`。模型输出中的 `check_spec` 被 Parser 忽略，
不能伪造工具参数或验证结果。Host 在 Candidate/ReasoningState 边界外构造
`CheckSpec`，并可把它附着到题内 Claim 与 LemmaCard 供后续确定性服务使用。

### 2.3 工具结果回注下一轮

新增 `ToolFeedbackController` 和强类型 `ToolWorkItem`、`ToolFeedbackBatch`、
`PublicToolResult`：

1. 从新产生的非 reasoning Claim 构造工作项；
2. 使用现有 ToolExecutor 与题内 CallBudget 执行；
3. 结果映射为 `confirm_strategy`、`switch_strategy`、
   `request_clarification` 或 `no_change`；
4. 把结果摘要、摘要哈希、Evidence 引用和策略影响提交到
   `ReasoningState 1.1`；
5. `continue` 或 `synthesize` 读取更新后的公开状态。

九类 Claim 工具请求均由同一个生产构造器生成 Prompt 示例和运行参数，删除了
示例参数与生产参数两套手写逻辑。自然语言等式、残差、表达式、矩阵、LaTeX、
概率密度、小样本值和答案类型均有确定性构造规则。

### 2.4 Typed Claim 与目标驱动 Lemma

LemmaCard 现在保留来源 Candidate/Claim、`claim_kind`、Host `check_spec` 和
明确的 `target_obligation_ids`。LemmaCurator 优先使用：

- source Claim 与 Proof Obligation 的精确引用；
- Claim kind 与 obligation kind 的类型对应；
- Claim、局部目标和义务描述之间的有限词项重合。

义务关闭不再依赖“义务类型字符串是否出现在引理文本中”的脆弱判断，而是只由
typed obligation ID 和相应 Evidence 引用驱动。所有引理仍限制在当前题目作用
域，不写入跨题可变存储。

### 2.5 审核方法卡与运行门禁

新增 `ReviewedMethodCardStore` 和 `method_cards_manifest.json`。加载时强制校验：

- 数据文件 SHA-256；
- 方法卡数量和唯一 ID；
- `reviewed` 信任级别、审核人、审核日期和来源版本；
- 每张卡片的内容哈希；
- 库版本；
- A/B 前不得在运行时启用。

`competition.json` 和 `balanced.json` 已关闭 Frozen Lemma Store；RAG 继续
保持关闭。方法卡当前仅作为只读、可审计资产存在，不在没有准确率和时延 A/B
证据的情况下改变正式求解路径。

### 2.6 Trace 与配置快照

Judge Trace 升级为 3.4：

- `skills_selected` 增加选择上下文、排序、评分、章节和原因；
- 新增受保护的 `tool_feedback_completed`；
- 公共工具结果保留 ID、状态、摘要、摘要哈希和策略影响；
- 公共投影不包含工具参数、完整 payload、原始异常、绝对路径、秘密或私有
  推理文本。

Effective Config Snapshot 升级为 1.1，显式公开动态 Skill、Host CheckSpec、
工具反馈协议、只读方法卡和 A/B 门禁状态。

## 3. 验收结果

| Phase 5 验收门 | 结果 | 证据 |
|---|---|---|
| 工具参数可构造率 ≥90% | 通过 | 生产 `ClaimToolRequestBuilder` 对九类 Prompt 示例达到 9/9，即 100% |
| 不可构造只产生 `unknown` | 通过 | `argument_unavailable` 和预算不可用均返回非致命 `unknown`，不形成 hard fail |
| 工具结果改变下一轮策略并提升正确率 | 通过 | 回归中工具关闭时 Fake 模型综合为错误答案；硬失败回注后策略和 Skill 改变，下一轮综合为正确答案 |
| Skill included/omitted/reason 可追溯 | 通过 | 内部 Trace 和 Judge Trace 3.4 均验证 selection context、rank、score、section 和 reason |
| Lemma 为 typed、目标驱动复用 | 通过 | 仅显式关联的 obligation ID 被关闭，非目标义务保持开放 |
| 方法卡只读且 A/B 前禁用 | 通过 | 数据/卡片哈希、审核元数据和配置门禁测试通过 |
| 跨题状态零污染 | 通过 | 同一共享 Harness 连续求解两题，工具结果、工作项 ID 和动态 Skill 上下文均不串题 |

## 4. 自动化验证

最终验证结果：

```text
python -m compileall .                         passed
pytest -q                                      605 passed in 132.50s
python scripts/verify_baseline_files.py        passed
python scripts/verify_build_provenance.py      passed
python scripts/verify_content_reviews.py       passed
python scripts/validate_submission.py          passed（保留两项冻结前治理警告）
python scripts/scan_secrets.py                 passed
git diff --check                               passed
```

新增 7 项 Phase 5 回归覆盖参数可构造率、不可构造降级、工具反馈提升、动态
Skill 追溯、typed Lemma、方法卡门禁、Judge Trace 安全和共享 Harness 跨题
隔离。另有 101 项相关历史契约回归通过；全量 605 项测试全部通过。

当前 Python 环境未安装 ruff 和 mypy 模块，因此没有伪报静态检查通过；语法、
运行契约和行为验收由 compileall 与全量 pytest 覆盖。

## 5. 治理与兼容性

- PrimarySolver Prompt 合同升级为版本 4；
- Prompt manifest 的 Host compiler 版本升级为 4；
- ReasoningState Schema 升级为 1.1；
- Judge Trace Schema 升级为 3.4；
- Phase 0 配置基线、内容审查清单和构建 provenance 已同步；
- `main.py`、`llm_client.py` 的冻结基线校验通过；
- `status/final_response/trace` 公共产出规则不变。

## 6. 边界与后续阶段

本阶段的“正确率提升”证据是确定性回归中的因果对照，不等同于真实
Intern-S2-Preview-397B 数据集 A/B。项目配置仍应保持
`candidate-unvalidated`，方法卡 RAG 和 Frozen Lemma Store 继续关闭。

Phase 6 应在此基础上继续完成题目前置 Proof Obligation、完整公开解答复审、
候选冲突交叉审阅和原子 Repair/Reverify。真实模型的工具参数覆盖率、一般
高难度题准确率、额外调用收益和 p95 时延需留到正式离线/注入 Client A/B
阶段评估。
