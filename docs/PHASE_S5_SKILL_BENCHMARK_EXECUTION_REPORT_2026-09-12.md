# Phase S5 执行报告：Skill Benchmark 与 ON/OFF 消融

日期：2026-09-12
状态：工程实现完成；真实模型消融证据门阻断（未伪造通过）

## 目标

为 13 个 P0 重写包和 9 个 S4 外部改写包建立统一的正例、负例、对抗例、
选择和消融基准，并把“能否被选择”“是否应被降权”“模型准确率是否提高”
分成不同证据层。离线选择结果不被当作模型准确率；ON/OFF 只有在收到成对的
实际模型输出后才计算。

## 实现

### 基准语料

新增 [data/skill_s5_benchmark.json](../data/skill_s5_benchmark.json)：

- 覆盖 22 个目标 Skill，每个 Skill 恰好 5 个 case type，共 110 个 case；
- `positive`/`selection`/`ablation` 期待目标 Skill 被纳入候选；
- `negative`/`adversarial` 使用 `deprioritize` 期待，要求目标不在首位或不被
  纳入；这是对 S1 “负触发是有界降权而非硬 veto”策略的忠实测试；
- 对抗题明确记录缺少前提、边界、定义域、可观测状态或验证能力等原因。

### 可执行评估

新增 [mathforge/skills/s5_benchmark.py](../mathforge/skills/s5_benchmark.py)：

1. 校验 JSON schema、22 个 Skill 清单、case ID 唯一性和五类覆盖；
2. 使用生产 `SkillRegistry` 与 `DynamicSkillSelector` 构造 `ProblemIR`，执行
   离线选择审计；
3. 输出按 case type/Skill 的通过计数、正例召回、负触发降权率和具体失败
   case；
4. `evaluate_s5_ablation()` 只接受 `actual`/`expected_answer` 等可观察成对
   行，拒绝手写 `skill_on_correct`/`skill_off_correct`，缺少实测行时返回
   `pending_real_runs`；
5. 输出 case、Skill 指纹和证据范围，避免把本地模拟冒充官方结果。

新增 [scripts/run_skill_s5_benchmark.py](../scripts/run_skill_s5_benchmark.py)
作为 CLI：

```text
python scripts/run_skill_s5_benchmark.py \
  --output artifacts/s5_selection_benchmark_20260912.json
```

提供 `--ablation-records` 时才会计算成对 ON/OFF；生产级消融还应按 E8 规则
使用至少 3 次重复、相同 case 集、交错执行顺序和可观测 provider health。

## 离线选择结果

运行版本指纹：

- case SHA-256：`7afa66cc2c8b649401ddb6172ceeaf2badc1611c98bfb5e4aaaf91b21817fd88`；
- Skill catalog SHA-256：`9cba5587d18d7f46305082dafaac13f650a75c7367ea293218be335a0a7af0f0`；
- Skill 总数：95；V3：60；
- case：110，22 个 Skill 均完整覆盖五类测试。

| Case type | 通过 | 总数 | 解释 |
| --- | ---: | ---: | --- |
| positive | 13 | 22 | 目标 Skill 被生产 top-k 纳入 |
| negative | 22 | 22 | 目标 Skill 被降权或未纳入 |
| adversarial | 22 | 22 | 缺少前提的目标 Skill 未占首位 |
| selection | 12 | 22 | 方法选择场景中目标 Skill 被纳入 |
| ablation（选择层） | 9 | 22 | 消融 case 的选择层预检 |
| 合计 | 78 | 110 | 离线选择通过率 0.7091 |

包含类 case 的正例召回为 `34/66 = 0.5152`，负/对抗降权率为 `44/44 = 1.0`。
这组结果是选择器工程诊断，不是数学题准确率。

## 当前暴露的问题

1. **生产 `top_k=3` 的效用排序挤出了长篇 V3 Skill。** 许多目标包虽然命中
   主题、pattern 或 route seed，但其正文较长、默认 `expected_gain` 为零，
   估算 token cost 较高；通用旧 V2 Skill 因成本较低占据 top-k。这解释了
   positive/selection/ablation 通过率偏低，是实际的选择缺陷而不是测试噪声。
2. **必需观测量的缺失会叠加降权。** 题面没有使用 Skill frontmatter 中的
   精确短语时，目标包会得到 `missing_required_observable`；这说明当前只做
   词面匹配仍不足以完成结构识别，不能把降权结果误解为数学方法不适用。
3. **负触发目前是降权，不是 veto。** 本阶段负例通过并不表示错误 Skill
   永远不会进入候选；Host 仍需在 exact preconditions 和 verification gate
   阶段拒绝不满足定理前提的候选。
4. **真实准确率和 token 成本尚未有证据。** 本次没有调用官方模型，也没有
   使用 Fake/Scripted Client 生成分数；ON/OFF 结果明确为
   `pending_real_runs`，需要 110 个 case 的成对行（若按 E8 3 次重复则至少
   660 行）后才能计算。

## 后续整改计划

1. **路由候选保留策略**：在不绕过语义前提和 hook admission 的情况下，为
   RouterPlanner 已确认且目标结构命中的 Skill 设计可审计的候选保留位，避免
   `top_k` 仅按正文长度/默认效用淘汰；新增 route-valid/route-invalid 对抗例。
2. **真实效用校准**：使用相同题集、交错执行和至少 3 次重复的 Skill ON/OFF
   实测结果估计 `expected_gain`、`historical_precision` 与 token cost；禁止
   在没有观测数据时手填高收益先验。
3. **结构化选择特征**：把 `required_observables` 从纯词面命中升级为
   ProblemIR/ReasoningState 字段映射，并保留缺失观测的公开原因；不满足精确
   前提时仍不得强行纳入。
4. **真实消融与准确率**：通过 CLI 导入成对实际输出，检查 case ID、重复次数、
   交错顺序、provider health、answer/expected 可评分性，再使用现有
   `evaluate_skill_specific_benchmark` 和 E8 paired evaluator 生成准确率、
   置信区间、调用数、延迟和失败分层。
5. **发布治理**：真实 benchmark 固定 commit/config/prompt/Skill/data 指纹，
   完成数学人工复核后再重建过期的 content-review manifest；不得为了让旧
   validator 变绿而手工改 hash。

## 验证

新增 `tests/test_phase_s5_skill_benchmark.py`，覆盖语料完整性、五类覆盖、
生产 selector 确定性、负/对抗策略、缺少真实行时 fail-closed、成对记录计算和
手写正确率字段拒绝。定向测试：`4 passed`。

提交前验证结果：

- `python -m compileall -q .`：通过；
- `pytest -q`：`1065 passed, 2 failed`；失败仍为既有
  `content_review_manifest` 内容哈希陈旧导致的
  `test_content_review_manifest_covers_all_scopes_but_blocks_human_freeze` 与
  `test_submission_validator_passes_repository`，未通过手工改 hash 绕过；
- `python scripts/verify_baseline_files.py`：通过。

本阶段完成了 benchmark/evaluator 的工程实现和可复现离线诊断，但在真实模型
ON/OFF 证据到位前，不得宣称新增 Skill 提升官方准确率，也不得冻结发布基线。
