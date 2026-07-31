# Phase T5 Prompt 与 Candidate Schema 对齐执行报告

日期：2026-07-31  
阶段：T5——按题型生成公开解法并统一模型 Candidate 边界

## 1. 阶段结论

Phase T5 已完成。Host 内部 `CandidateSolution 2.0` 保持不变；新增独立的模型侧
`ModelCandidatePayload 2.1`，由生产 Prompt 和 Parser 共用。此次没有增加新的
内容质量硬淘汰条件，目标是在不损害稳定产出的前提下，让模型明确知道最终输出
模式、公开步骤要求和 LaTeX 规则。

## 2. 题型与输出模式

Solver 现在能在实际 Prompt 中同时看到 `response_mode` 与 `answer_type`：

- `answer_only`：Candidate 仍提供 1--4 个简洁、可核查的公开步骤供
  `trace[0]` 使用；Host 的 `final_response` 只给规范化最终答案。
- `worked_solution`：`solution_text` 给出题目要求的完整推导，公开步骤提供有序、
  可独立检查的同一推导。
- `proof_full`：`solution_text` 给出完整证明，公开步骤给出同构的有序分步证明；
  通过压缩措辞把完整证明控制在约 18,000 字符内，而不是截掉关键证明环节。

数学公式在 `solution_text`、公开步骤和 Claim 中使用 `$...$` LaTeX 定界。
`final_answer` 保持不带定界符的标准 LaTeX 源，由确定性 Formatter 唯一渲染。

## 3. Candidate Schema 对齐

`ModelCandidatePayload 2.1` 的八个必填模型字段为：

```text
method
final_answer
public_solution_steps
claims
solution_text
assumptions
theorems
unresolved_obligations
```

`candidate_id`、`role`、`answer_type`、版本、解析状态、来源、
`contract_deviations`、`method_steps` 和验证状态仍由 Host 持有。为兼容既有夹具，
Parser 可接收可选 `method_steps`，但生产 Prompt 不要求模型输出它；Host 会从
Claims 确定性构造 MethodSteps。

共享模块同时定义 Candidate Patch 的四字段骨架。Repair Parser 会记录缺字段、
Host 字段和未知字段的受控 deviation code，但不因纯排版质量新增整题硬失败。

## 4. 固定角色对齐

- PrimarySolver / AlternativeSolver：接收 response mode，生成对应粒度的公开解法；
- VerifierSkeptic：能看到 response mode；证明题缺关键推理、定理条件或边界时不得
  标记为 pass；
- RepairAgent：局部修复步骤与 Claim 使用公开 LaTeX，仍只修改失败依赖闭包；
- LLMFinalizer：不再被要求输出 Host-owned `method_steps`，并核对 method、公开
  步骤、解法正文、Claims、假设、定理和开放义务；任何改写均回滚到确定性格式化；
- RouterPlanner 与非生产 LemmaCurator 的职责未扩张。

所有角色继续禁止请求或输出私有思维链、scratchpad、原始响应和本地工具参数。

## 5. 验收标准

- 三种 response mode 均进入实际 Solver 系统 Prompt 和问题结构；
- 模型 Candidate 精确 JSON 骨架可解析，字段集合与 Parser 共用定义一致；
- answer-only 仍要求公开步骤，proof-full 明确要求完整证明；
- 所有公开数学公式有 LaTeX 约束，最终答案仍由 Host 唯一包装；
- Finalizer 修改公开步骤、方法或开放义务时确定性回滚；
- 不修改 `main.py`、`llm_client.py`，不读取 API 密钥或引入新的在线 Client。

提交前质量门：

```text
python -m compileall .
pytest -q
python scripts/verify_baseline_files.py
python scripts/verify_content_reviews.py
python scripts/verify_build_provenance.py
```
