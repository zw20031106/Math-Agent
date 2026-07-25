# S6-E / E4 实施状态：Prompt Contract v2

日期：2026-07-25

对应计划：阶段 E4

提交目标：`S6-E: align prompts with CandidateSolution v2`

## 结论

E4 的代码、确定性契约测试和内容治理工作已经完成。七个固定角色的
Prompt Contract 已统一到 v2；Solver 输出边界与 `CandidateSolution` 2.0
模型字段一致，不再要求模型输出宿主拥有的 `answer_type`，也不再使用
`when possible` 等软化核心契约的措辞。

本阶段没有伪造真实 Intern-S2-Preview-397B 的联网结果。当前执行环境只发现
Codex 内部变量，没有可安全使用的 `INTERN_API_KEY`。仓库已经提供固定 20
题、只接受注入式官方 `client.chat(...)` 的 live probe 入口；在获得有效凭据
的正式运行环境中，应先执行该探针并保存报告，再进入 88 题全量冻结。

## 完成项

### 1. Solver 与 Alternative Contract v2

- 只允许一个完整 JSON object，禁止 Markdown fence 和前后说明文字；
- `method` 必须精确复制 Host 分配的 MethodFamily；
- `solution_text` 明确为完整、可公开、可检查的数学解答；
- `public_solution_steps` 明确为进入公共 Trace 的有序步骤；
- 完整列出 Claim、MethodStep 字段和全部受控枚举；
- 明确列出 Host-owned 字段，模型不得输出；
- 明确模型没有原生 Tool Calling，`check_type` 仅为 Host 检查建议；
- Alternative 只能看到禁止的方法族和公开标签，必须通过公开步骤证明方法
  独立性，不能用改名伪装相同方法。

### 2. Verifier 与 Repair 边界

Verifier 输入现在包含：

- 原题与条件；
- Claims；
- MethodSteps；
- `public_solution_steps`；
- Host Evidence；
- Proof Obligations。

Verifier 输入不包含完整 `solution_text`。输出 finding 保存
`public_rationale`、`missing_condition` 和 `counterexample_summary`，并在
Evidence payload 中保留后两项。

Repair Contract 只允许修正失败 Claim 影响闭包，要求输出替换 Claims、修正的
公开步骤、修正或不变的精确答案以及未解决义务；Host 继续负责版本比较、复验和
证据质量下降回滚。

### 3. SolutionParser 分类与兼容

新增或明确的解析分类：

- `strict_json`：裸的、完整的 Candidate v2 JSON；
- `fenced_json`：可解析但违反无围栏契约；
- `outer_json`：JSON 外存在额外文字；
- `repaired_json`：只经过安全字面量/尾逗号修复；
- `truncated_json`：字符串或括号未闭合；
- `malformed_json`：外形完整但 JSON 语法错误；
- `incomplete_json` / `*:incomplete_candidate`：缺少必需模型字段或关键
  字段为空。

只允许以下无歧义兼容别名，并记录 normalization deviation：

- `structured_method_steps -> method_steps`；
- `public_steps -> public_solution_steps`；
- Claim `id -> claim_id`、`dependencies -> depends_on`；
- MethodStep `id -> step_id`、`claims -> claim_ids`。

规范字段与别名冲突时始终保留规范字段，并记录冲突，不静默覆盖。

## 20 题 Prompt Contract Probe

固定题型组成：

| 类别 | 数量 |
|---|---:|
| 标量计算 | 5 |
| 向量/矩阵输入、标量输出 | 3 |
| 区间输入、数值输出 | 2 |
| 多项式 | 2 |
| 集合/群 | 2 |
| 证明/推导 | 3 |
| 跨领域 | 3 |
| 合计 | 20 |

确定性注入客户端契约结果：

| 指标 | E4 门槛 | 结果 |
|---|---:|---:|
| strict JSON | ≥95% | 100% |
| Host-owned deviation | 0 | 0 |
| Candidate deviation | ≤5% | 0% |
| Claim 非空 | ≥90% | 100% |
| public steps | ≥95% | 100% |
| final answer 可解析 | ≥95% | 100% |
| MethodFamily 遵循 | ≥90% | 100% |
| 私有推理字段 | 0 | 0 |

这些结果验证 Prompt 构造、解析、计量和失败门禁本身，不冒充真实 397B
采样结果。真实模型报告必须由
`run_live_prompt_contract_probe(client, max_tokens=...)` 使用官方注入客户端
产生。

## E4 验收映射

| 验收项 | 状态 | 证据 |
|---|---|---|
| C08 Prompt 与真实输出结构一致 | 通过确定性门；待真实模型复核 | Contract v2、20 题 probe |
| C17 公开解题过程进入 Trace | 通过 | `public_solution_steps` 必填且 Verifier 可见 |
| C19 方法独立性 | 通过确定性门 | assigned MethodFamily 精确匹配和 probe 指标 |
| C20 失败分类 | 通过 | truncated/malformed/incomplete 独立分类 |
| C22 测试门禁 | 通过 | E4 专项、全量 pytest 与静态门禁 |
| C23 角色上下文边界 | 通过 | Verifier 不接收完整 Solver 文本 |
| C25 内容治理 | 工程审核通过，人工冻结仍待签名 | 更新后的 prompt tree hash |

## 自动化门禁结果

- `python -m compileall .`：通过；
- `pytest -q`：301 passed；
- branch coverage：总计 82%，关键模块门禁全部通过；
- Ruff：通过；
- Mypy（核心 91 个源文件，跳过不可变官方客户端的第三方 stub
  跟随）：通过；
- Content review hash：通过；
- Secret scan：通过；
- Submission validator：通过；
- `main.py` / `llm_client.py` immutable baseline：通过；
- 88 题 normalized dataset preflight：88/88 expected、88/88 自动评分、
  invalid expected=0、coverage=100%。

## 未伪造的外部门

- 真实 Intern-S2-Preview-397B 20 题 probe：需要正式运行环境注入凭据；
- 人类数学/Prompt 专家签名：全局内容清单仍保持 `pending-human`；
- 88 题全量真实模型冻结：按计划应在后续真实模型阶段执行。
