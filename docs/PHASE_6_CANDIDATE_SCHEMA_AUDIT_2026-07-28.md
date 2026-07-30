# Phase 6 Candidate Schema 专项审查

日期：2026-07-28  
范围：模型提示、Candidate 解析、Host 补全、准入、Evidence、Proof、Trace 与真实 Intern-S2 397B 调用。

## 1. 结论

当前 `CandidateSolution` 内部对象能够表达数学候选、Claim 图、MethodStep、
Evidence 和 Proof Obligation 的关联，但模型边界仍不够稳定。问题不是 API
不可用，也不是模型没有返回文本：真实金丝雀的 L0/L1/L2 均通过，正式第 0
题的两次 Primary 调用分别返回 2,354 和 3,350 字符，随后均被标记为
`candidate_schema_invalid`。这表明故障集中在正式上下文下的模型 Payload
与严格 Parser 契约之间。

最核心的设计问题是项目同时存在两套不同含义的 Candidate Schema：

1. 模型侧 Payload：只允许九个顶层字段，不允许身份、版本、验证状态等
   Host 字段。
2. Host 侧 `CandidateSolution` V2：包含身份、角色、答案类型、版本、解析
   状态、契约偏差和验证状态等完整字段。

二者的边界目前主要由 Prompt 字符串和 `SolutionParser` 隐式维持。文档使用
`CandidateSolutionModelFieldsV2` 这一名称，但代码中没有对应的独立类型或
机器可校验 JSON Schema。因此，文档、Prompt、Parser 和内部数据类发生漂移
时，静态检查不能及时发现。

## 2. 当前模型侧契约

模型必须返回且只返回：

```json
{
  "method": "assigned-method-family",
  "final_answer": "exact answer",
  "public_solution_steps": ["public step"],
  "claims": [
    {
      "claim_id": "c1",
      "statement": "checkable claim",
      "depends_on": [],
      "check_type": "reasoning",
      "importance": "critical"
    }
  ],
  "method_steps": [
    {
      "step_id": "s1",
      "kind": "conclusion",
      "claim_ids": ["c1"],
      "theorem": ""
    }
  ],
  "solution_text": "complete public derivation",
  "assumptions": [],
  "theorems": [],
  "unresolved_obligations": []
}
```

Host 随后注入 `candidate_id`、`role`、`answer_type`、版本、解析状态、方法规划
与验证状态。模型不得写入这些字段。

## 3. 问题清单

### CS-01：模型 Payload 没有独立的可执行 Schema（高）

`CandidateSolutionModelFieldsV2` 只存在于 Prompt 元数据中。Parser 手写维护
必填字段、别名、枚举和 Host 字段，内部数据类又维护另一套规则，容易出现
三处漂移。

解决方案：后续建立只包含模型所有权字段的 `ModelCandidatePayloadV2` 或
JSON Schema，并由它生成 Prompt 骨架、Parser 校验和契约测试。Host
`CandidateSolution` 保持为独立内部 Schema。

### CS-02：生产 Prompt 与合同正文并非同一内容（高，已部分修正）

`contract.md` 有完整样例，但生产 `PromptCompiler` 只使用 frontmatter 和压缩
协议，不发送正文。此前压缩协议只有字段枚举，没有完整 JSON 骨架。

本轮已在生产 Prompt 中加入精确、紧凑的九字段 JSON 骨架；仍保留上下文
压缩，不直接复制整份合同正文。

### CS-03：契约重试没有校验反馈（高，已修正）

此前第二次 Primary 调用只把温度设为零，仍发送相同消息，模型不知道第一次
缺少了哪些字段或使用了哪些错误键。

本轮已把受控的 `parse_status` 和字段级 deviation code 追加到第二次请求。
不回传失败候选全文、原始异常或私有推理。

### CS-04：嵌套 Schema 异常绕过重试（高，已修正）

重复 Claim ID、未知依赖、依赖环、非法 ID 或过长 Claim 会让
`CandidateSolution.validate()` 在 Parser 中直接抛出
`SchemaValidationError`。此前这类错误不会进入 Primary 契约重试。

本轮将其统一分类为 `candidate_schema_invalid`，并进入同一个有界重试闭环。

### CS-05：Parser 的“修复”与最终拒绝策略矛盾（中）

Parser 会规范化 `id -> claim_id`、`dependencies -> depends_on`，也会识别
Markdown fence、外层 JSON 和可修复 JSON；但任何 deviation 或非
`strict_json` 状态最终都会被拒绝。这些代码目前主要提供诊断价值，并不提高
成功率。

解决方案：在 Phase 6 后明确两级策略：

- 可安全规范化且无冲突的格式偏差可进入一次“规范化后重验”；
- Host 字段、未知字段、类型错误、别名冲突、引用错误和图错误继续硬拒绝。

在形成单独的模型 Payload Schema 前，不建议直接放宽所有 deviation。

### CS-06：方法族约束此前没有形成硬准入（高，已修正）

模型返回错误 `method` 时，旧逻辑在严格 Payload 校验之后才记录 deviation，
只降低独立性得分，单候选仍可能进入后续闭环。

本轮把方法族不一致改为 `candidate_method_invalid`，允许 Primary 在预算内
修正一次；Candidate Admission 再次执行硬校验。

### CS-07：`check_type` 混合了两个维度（高，待架构修订）

当前 `check_type` 同时表示：

- 逻辑义务类型，如 `necessity`、`boundary`、`theorem_preconditions`；
- 工具能力，如 `simplify_expression`、`numerical_residual`。

一个 Claim 可能既是定理前提，又适合符号验证，单字段无法无损表达。模型还
容易把自然语言 Claim 错标为符号工具输入。真实运行中已经出现此问题。

本轮先将 Prompt 默认值明确为 `reasoning`，只有路由已授权且 Claim 给出精确
数学输入时才允许选择工具名；工具资源边界也会把错误输入降级为软错误。

长期方案：拆分为 `obligation_kind` 与 `verification_hint`，Host 只把后者映射
到工具能力。

### CS-08：`unresolved_obligations` 的所有权不清晰（中）

该字段被要求由模型返回，但 `ProofObligationEngine.generate()` 随后会根据
题型、定理和 Claim 重新生成并覆盖它。模型输出值没有稳定的持久语义。

解决方案：将模型字段改名为 `declared_open_questions`，或从模型 Payload 中
移除，由 Host 独占 `unresolved_obligations`。这是 Schema 版本变更，应在
Phase 6 真实验证后单独实施。

### CS-09：内部 Claim 枚举校验分散（中）

`SolutionParser` 校验模型侧 `importance` 和 `check_type`，但 `Claim.validate()`
本身未完整约束这些枚举。通过其他内部构造路径创建的 Claim 可能绕开相同
规则。

解决方案：把通用枚举放入 Schema 层；模型专属的允许集合放入模型 Payload
层，避免 Parser 与内部对象各自维护不一致的集合。

### CS-10：九字段内容存在较高重复度（中）

`solution_text`、`public_solution_steps`、`claims` 和 `method_steps` 会重复表达
同一推导。它有利于公开答案、Trace 和证明图分别消费，但也提高模型 JSON
出错概率和输出成本。

解决方案：当前不删字段，以满足公开 Trace 和证据闭环；后续可让
`solution_text` 由 Host 根据 `public_solution_steps` 与 Claims 确定性生成，
或只要求模型提供一种规范化公共步骤结构。

### CS-11：正式失败的可观测性不足（高，已修正）

旧 Trace 只保留 `candidate_schema_invalid`，无法区分缺字段、错误别名、
嵌套图错误或方法错误，又不能为了调试泄露完整失败 Candidate。

本轮在 Branch Failure 中增加受控字段级 validation code。它不包含失败候选
全文、绝对路径、API 密钥、原始异常或私有推理。

## 4. 本轮不应采取的做法

- 不把任意非 JSON 文本当作成功 Candidate。
- 不因模型给出看似正确的 `final_answer` 就绕过 Claims、MethodSteps 和
  Proof Gate。
- 不在 Trace 中保存完整失败 Candidate 或模型私有推理。
- 不无限重试 Schema 错误；Primary 仍只允许一次有预算的纠错。
- 不把 20,000 字符 `final_response` 上限误用于内部 Trace 或模型上下文。

## 5. 验收标准

下一次真实金丝雀必须同时满足：

1. L0/L1/L2 全部通过，模型身份是 `intern-s2-preview-397b`。
2. 正式 Candidate 是 bare strict JSON，九个模型字段齐全。
3. nested Claim/MethodStep 键、类型、引用和 DAG 均合法。
4. `method` 与 Host 分配的方法族一致。
5. 工具不因错误 Claim 输入终止整题。
6. 必需 Proof Obligation 得到 Evidence/Verifier 闭环。
7. `0.json` 只有 `id/status/final_response/trace` 四个字段，状态为
   `success`，最终答案正确。
8. `final_response` 不超过 20,000 字符并保留完整最终答案；Trace 使用独立
   预算。

