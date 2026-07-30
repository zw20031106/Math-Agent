# MathForge Phase 3 执行报告

日期：2026-07-30  
阶段：ProblemIR、路由和有效配置  
结论：实现完成，专项验收通过；全项目回归结果见第 6 节

## 1. 执行范围

本阶段严格对应审查计划 Phase 3：

1. 裸行首 `A ` 不再触发选择题，仅接受可靠连续枚举；
2. ProblemIR 升级为 v2；
3. 低置信度答案类型改为软门和规范化恢复；
4. 增加一般高难度结构路由与 Primary 后验升档；
5. 输出最终生效的 Prompt/Provider/Deadline 配置；
6. 自动关闭空 Frozen Lemma Store。

没有修改 `main.py`、`llm_client.py`，没有增加外部模型客户端、模型环境变量
依赖或在线网络依赖。

## 2. ProblemIR 2.0

`ProblemIR` 的 Schema 版本从 1.3 升级到 2.0，新增：

- `answer_type_confidence`
- `definitions`
- `quantifiers`
- `constraints`
- `target_kind`
- `ambiguities`
- `difficulty_features`
- `subproblem_hints`

`target_kind` 使用受控枚举：

- `select_option`
- `compute_value`
- `prove_statement`
- `derive_statement`
- `explain_reason`
- `construct_object`
- `multiple_targets`

这些字段经过严格类型、范围、未知字段和 round-trip 校验。Primary 与
Alternative Prompt 会收到一个有界的公开 ProblemIR 结构摘要；每个片段最多
240 字符，不注入私有推理或外部状态。

## 3. 解析与答案类型软门

### 3.1 选择题识别

选项必须：

1. 使用 `A.`、`A)`、`(A)`、`（A）`、`A、` 或 `A:` 等明确标点；
2. 至少存在 A、B 两项；
3. 标签从 A 开始连续且不重复。

因此 `A finite graph ...` 和裸 `A value` 不再被误识别为选择项。显式
“select”但没有可靠枚举时记录
`choice_intent_without_reliable_options`，不把答案类型硬化为 `choice`。

### 3.2 低置信度答案类型

Parser 对明确整数、区间、矩阵、集合等目标继续给出高置信度；缺少可靠目标
形状时保留 `expression`，但置信度为 0.78。低于 0.85 时：

- Candidate 自报类型与 Parser 类型不一致只生成 warning；
- 非空答案的预期形状失败只生成 warning；
- answer-type 工具检查 Candidate 当前类型，避免错误的 Parser 类型生成
  fatal hard evidence；
- 空答案、Candidate Schema 失败和 answer-recovered 的确定性恢复门仍是硬拒绝。

这避免“表示误判淘汰正确答案”，同时不降低空答案和结构违约的安全门。

## 4. 一般结构难度与 Primary 后验

路由使用与题目领域无关的结构信号，包括：

- 嵌套聚合与渐近消去；
- 状态依赖概率、耦合约束和容斥型计数；
- 根式定义域、全局多变量约束和参数区间；
- 高阶微分系统、奇异/特殊积分；
- 多目标、长条件链、嵌套量词和双向证明；
- 候选冲突与多阶段证明。

不存在奥赛专用类别或比赛题模板硬编码。冻结的 12 题一般高难度集合中，
11 题路由为 high，召回率 91.7%；5 个简单校准题没有任何 high 误升。

Primary 返回后，以下公开质量信号触发显式
`primary_posterior_escalation`：

- recovered parse；
- 缺少答案或公开步骤；
- 未解决义务；
- Contract deviation；
- 缺少 critical Claim。

后验升档只使用已解析的公开 Candidate 字段，并仍受调用预算、阶段预算和
Deadline 控制。

## 5. Effective Config 与空缓存

Judge Trace 升级为 3.2，新增受保护的
`effective_config_snapshot`，公开最终生效的：

- 每个固定角色的 Prompt 字符上限；
- Skill、原题和总 Prompt 字符预算；
- 每阶段输出 token 上限；
- Provider 只使用 `injected_client.chat`；
- 最大物理并发、tail 上限、上下文窗口和安全边际；
- 阶段 p95、阶段调用超时和队列上限；
- soft/exploration/hard/outer Deadline 与终态预留；
- Frozen Lemma Store 的 requested/effective/count/disabled reason。

每次公开模型调用记录同时包含：

- `prompt_tokens`
- `context_window_tokens`
- `safety_margin_tokens`
- `configured_output_tokens`
- `stage_output_cap_tokens`
- `max_output_tokens`
- `stage_p95_seconds`
- `effective_queue_budget_seconds`
- 实际队列、执行和总耗时

竞赛配置虽然请求 Frozen Lemma Store，但当前受审资源记录数为 0；Harness
初始化时将其自动关闭，并在 Trace 中记录 `disabled_reason=empty_store`。

## 6. 验收结果

| 验收项 | 结果 | 证据 |
|---|---:|---|
| 误判对抗集 | 通过 | 6/6；裸 A 行、长条件、多目标、工具声明、候选冲突、结构化输出压力均满足断言 |
| ProblemIR v2 Schema | 通过 | 严格字段校验与 round-trip |
| 低置信度软门 | 通过 | 类型不一致保留 Candidate 并记录恢复 warning；空答案仍拒绝 |
| 高难度路由召回 | 通过 | 11/12 = 91.7%，目标 ≥90% |
| 简单题 high 误升 | 通过 | 0/5 |
| Primary 后验升档 | 通过 | 缺少 critical Claim 时启用已预留 Alternative |
| 每次调用限制可解释 | 通过 | Judge Trace 3.2 含最终配置与逐调用 token/queue 字段 |
| 空 Frozen Lemma Store | 通过 | requested=true、effective=false、record_count=0、reason=empty_store |

## 7. 安全与兼容性

- API Key、绝对本地路径、raw response、异常堆栈和私有推理不进入公共 Trace；
- 有效配置快照不包含模型密钥或未经官方接口暴露的客户端字段；
- ProblemIR 结构提示只包含原题的确定性公开抽取；
- 既有 hard evidence、Proof、Arbitration 和安全 Candidate salvage 规则未放宽；
- Judge Trace 版本显式升级为 3.2，运行清单继续从代码常量校验当前版本。

## 8. 测试与校验

```text
pytest -q
590 passed in 144.37s

python -m compileall .
passed

python scripts/verify_baseline_files.py
Official immutable baseline files verified.

python scripts/validate_submission.py
Submission validation passed.

python scripts/scan_secrets.py .
Secret pattern scan passed.
```
