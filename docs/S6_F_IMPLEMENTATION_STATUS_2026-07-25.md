# S6-F / E5 实施状态：Skill 2.0 与 Router

日期：2026-07-25

对应计划：阶段 E5

提交目标：`S6-F: upgrade domain skills and routing`

## 结论

E5 已完成 Skill 2.0、角色级运行时注入、Router 高级数学领域扩展、88 题
金标验收、Trace 路由证据和内容治理。当前仍是数学 Agent：固定 LLM 角色负责
数学解题、质疑和局部修复，领域 Skill 动态提供数学方法与定理条件；路由、
预算、组合、证据和 Trace 仍由确定性服务负责。

## Skill 2.0 范围

- 领域 Skill：29 个；
- 通用 Skill：6 个；
- 总数：35 个；
- 新增专门领域：抽象代数、高等代数/高级线性代数、数学分析/高级实分析、
  泛函分析、测度积分、常微分方程、偏微分方程、随机过程、运筹学、线性回归、
  微分几何；
- 复分析及原有 17 个领域统一升级到 Skill 2.0；
- 所有文件必须声明 triggers、roles、version，并包含九个强制章节。

注册表保持原有 `compose(names, max_chars) -> str` 入口，同时新增带
`included/omitted/unknown` 结果的角色级组合。预算不足时只省略完整 Skill
块，不允许字符切片产生残缺指令。

## 角色级运行时接入

运行时分别为以下角色构建 Skill 上下文：

- PrimarySolver；
- AlternativeSolver；
- LemmaCurator；
- VerifierSkeptic；
- RepairAgent；
- LLMFinalizer。

Solver 分支获得各自角色兼容的 Skill；Verifier、Repair 和 Finalizer 的真实
Prompt 入口已接入对应内容。RAG 卡片只在完整卡片能放入剩余预算时追加到
PrimarySolver，不能反向截断已选 Skill。Lemma 扩展也按完整 Lemma 行追加。

`skills_selected` Trace 现在记录：

- Skill 名称与版本；
- 实际角色；
- domain/general 选择原因；
- 每个角色因预算省略的完整 Skill；
- 未知 Skill；
- Skill 内容树指纹。

`route_planned` 记录置信度、候选领域和明确 trigger reason。缺少专门领域与
低 Parser 置信度都会留下风险标记。

## 88 题 Router 金标

数据：`data/dev_set_2_gold.jsonl`

| 指标 | E5 前 | E5 后 | 门槛 |
|---|---:|---:|---:|
| Top-1 | 8/88（9.09%） | 87/88（98.86%） | ≥90% |
| Top-2 | 8/88（9.09%） | 88/88（100%） | ≥97% |
| general-math Top-1 | 45 | 0 | 0 个无解释回退 |

唯一 Top-1 偏差为 idx 42：数学分析排第一、测度积分排第二。该题同时含极限
积分与测度结构，Top-2 覆盖正确；结果满足预先冻结的 Top-1/Top-2 门槛。

`scripts/evaluate_router.py` 可重复生成指标并在不满足门槛或出现
`general-math` Top-1 时返回非零状态。E5 前指标保存在
`data/router_e5_baseline.json`，避免以修改后的规则伪装基线。

## 通用 Skill 动态可达性

| Skill | 运行时选择条件 | 目标角色 |
|---|---|---|
| answer-normalization | 所有题 | Solver、Repair、Finalizer |
| counterexample-search | medium/high risk | VerifierSkeptic |
| lemma-compression | high-risk proof/derivation | LemmaCurator |
| numerical-stability | 数值领域或数值风险触发 | Solver、Verifier |
| proof-obligation | proof/derivation | Solver、Lemma、Verifier、Repair |
| symbolic-equivalence | expression/polynomial | Solver、Verifier |

专项测试覆盖六个通用 Skill 的选择、角色兼容、运行时组合与 Trace 可见性。

## E5 验收映射

| 验收项 | 状态 | 证据 |
|---|---|---|
| C11 Skill 动态调用 | 通过 | 六个通用 Skill 选择与角色组合测试 |
| C12 Router 准确性 | 通过 | Top-1 98.86%、Top-2 100% |
| C19 方法独立性 | 通过 | 29 个 Subject 各三个互异 MethodFamily |
| C22 测试门禁 | 通过 | E5 专项、全量 pytest 与静态门禁 |
| C23 角色上下文边界 | 通过 | 角色白名单与独立 Prompt 注入 |
| C24 Trace 可审计 | 通过 | 路由原因、角色、版本、omitted/unknown |
| C25 内容治理 | 工程审核通过，人工冻结待签名 | Skill tree hash 与审查文档 |

## 自动化结果

- Router gold：87/88 Top-1，88/88 Top-2，general Top-1=0；
- Skill registry：29 domain + 6 general，全量 Skill 2.0；
- Runtime：完整块组合，六类固定执行角色接入；
- `python -m compileall .`：通过；
- `pytest -q`：310 passed；
- branch coverage：82.08%，五个关键模块均超过独立门槛；
- coverage 插桩任务：309 passed、1 deselected；排除项仅为
  `test_eight_problem_slow_client_p95_and_returned_traces_are_stable`，
  该 `<0.2s` 性能断言已在无插桩全量测试中通过，覆盖插桩会改变其计时；
- Ruff、Mypy、内容哈希、secret scan、submission validator 与 immutable
  baseline 门禁：通过；
- 人工冻结：仍为 `pending-human`，没有伪造人类数学专家签名。
