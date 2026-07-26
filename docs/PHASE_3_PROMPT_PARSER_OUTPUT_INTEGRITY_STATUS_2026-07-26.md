# Phase 3：Prompt、Parser 和输出完整性实施状态

日期：2026-07-26

## 1. 本阶段范围

本阶段按 2026-07-26 复审实施计划完成：

1. 题型/角色 Prompt Compiler；
2. 运行时重复合同压缩；
3. Candidate 核心字段优先；
4. 截断、自然语言、Schema 违约等响应分类；
5. 工具 Claim 最小可执行输入示例；
6. `final_response` JSON wrapper 防泄漏。

`main.py` 和 `llm_client.py` 未修改。本阶段没有发起在线模型请求；代表性
重复验收使用注入式确定性 Client，专门验证生产 Prompt → Provider →
Parser → Candidate 闭环。

## 2. Host Prompt Compiler

新增 `mathforge/agents/prompt_compiler.py`。Compiler 读取原有版本化静态
合同的角色、可见上下文、禁止上下文、工具边界、失败策略和停止条件，但不再
把每个长合同中的重复说明和完整大示例逐次拼入运行时 Prompt。

Solver Profile：

| Profile | 选择条件 | Primary 上限 | Alternative 上限 |
|---|---|---:|---:|
| `minimal` | 短计算、填空或选择题，条件少且非高风险 | 8,192 | 8,192 |
| `standard` | 非简单、非证明、非工具密集题 | 16,384 | 12,288 |
| `tool` | 数值、矩阵、概率归一化或有限枚举工具密集题 | 16,384 | 16,384 |
| `proof` | 证明或推导题 | 32,768 | 24,576 |

Router、Verifier、Repair 和 Finalizer 也通过 Compiler 生成精简角色合同，
输出上限分别为 4,096、8,192、12,288 和 4,096。Provider 仍会再次应用
阶段上限和 `prompt + output + 8,192 < 262,144` 的上下文门。

## 3. Candidate 核心优先

模型被要求在单个完整 JSON 对象中按以下顺序输出：

1. `method`
2. `final_answer`
3. `public_solution_steps`
4. `claims`
5. `method_steps`
6. `solution_text`
7. `assumptions`
8. `theorems`
9. `unresolved_obligations`

前四项是可落盘和验证所需的核心，但九个字段仍须完整出现；不会把未闭合 JSON
或只有部分核心字段的响应冒充完整 Candidate。简单题明确限制为 1–3 个公开
步骤、Claims 和 MethodSteps，证明题则保留完整依赖、定理条件和未解决义务。

## 4. Prompt 长度验收

对 `Compute 17+28.` 使用生产 `SkillRegistry`、6,000 字符 Skill 预算和
保守 UTF-8 chat envelope 计数：

| 项目 | 结果 |
|---|---:|
| 实际合成 Skill 字符 | 2,570 |
| Prompt 字符 | 3,954 |
| fallback token 上界 | 4,042 |
| 复审记录的旧实际范围 | 约 9,500–9,700 |

4,042 小于 5,000，也低于旧 9,500 基准的 60%，满足“明显小于”的验收。

## 5. Parser 完整性状态

`candidate_response_integrity()` 现在产生：

| 状态 | 判定 | Candidate Gate |
|---|---|---|
| `complete` | 严格 JSON、九字段完整、无合同偏差 | 接受 |
| `schema_violation` | 缺字段、空核心字段、Host 字段、围栏/外层/修复兼容路径等 | 拒绝 |
| `truncated` | 字符串、对象或数组未闭合 | 拒绝 |
| `malformed` | JSON 结构错误但并非简单截断 | 拒绝 |
| `natural_language` | 纯文本或只抽取到答案 | 拒绝 |
| `empty` | 空内容 | 拒绝 |

这修复了旧行为中 `raw_text`/`regex_answer` 虽标记为
`candidate_non_json` 却仍可进入候选池的问题。响应分类会记录安全错误码，
不会公开原始异常或失败候选。

## 6. 工具 Claim 示例

新增 `mathforge/tool_prompt_examples.py`，覆盖全部九个工具。每项包含：

- 原子且明确的 Claim statement；
- 与工具一致的 `check_type`；
- Host 可重建且能真实执行的输入；
- 一个不能安全映射的模糊反例。

测试逐项调用 `run_tool_direct()`，九个示例均能执行并返回
`pass/fail/unknown` 合法状态。运行时 `tool` Profile 最多注入三个与路由
相关的示例，并明确要求模型不得输出其中的 `host_arguments`，因此没有突破
“模型无原生工具调用、参数由 Host 重建”的架构边界。

## 7. 输出完整性

如果模型把另一个 JSON 对象写入 `solution_text`，Parser 增加
`solution_text:json_wrapper` 合同偏差并拒绝该 Candidate。正常 Candidate
只把公开数学推导交给 `DeterministicFormatter`，最终输出不包含
`method`、Candidate Schema 或 `final_response` wrapper。

## 8. 代表性三次重复验收

以下每类通过完整生产链重复三次：

- 简单计算；
- 数学证明；
- 概率密度；
- 线性代数矩阵。

12/12 次均满足：

- `strict_candidate_json`
- 非空 Claims
- 非空 MethodSteps
- 非空公开解题步骤
- 方法族与 Host 分配一致
- Profile 输出预算实际传入 Provider

该验收验证工程合同稳定性，不替代后续使用精确
`intern-s2-preview-397b` 的真实模型质量测试。

## 9. 指纹与审核

Prompt 指纹现在同时绑定：

- 七个静态角色合同；
- Host Prompt Compiler；
- 工具 Claim 示例。

Provenance Prompt Manifest 新增 `host_prompt_compiler` 条目。内容审核清单
新增 `prompt-compiler` 范围，并把工具能力范围升级为
`tool-contract-3`。工程哈希已更新；人工签名状态仍按既有治理规则保持
`pending-human`。
