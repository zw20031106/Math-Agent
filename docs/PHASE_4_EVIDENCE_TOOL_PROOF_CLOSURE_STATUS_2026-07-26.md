# Phase 4：Evidence、Tool 和 Proof 闭环实施状态

日期：2026-07-26
状态：工程实现和离线自动化验收完成

## 1. 实施范围

本阶段对应 0726 实施计划的 Phase 4，并以 C01、C02、C08、C17、C18、
C19 为最低验收边界。未修改冻结的 `main.py` 和 `llm_client.py`，未新增
任何模型客户端或 API Key 读取路径。

## 2. Claim → Tool 请求

新增 `ClaimToolRequestBuilder`。模型只提交受控 `check_type` 建议，Host
根据 Candidate、Claim、题目 domains/assumptions 和 Route 生成参数。
所有请求在工具执行前通过 `ToolRegistry.validate_arguments()`，状态稳定
区分：

- `ready`
- `unsupported`
- `route_not_selected`
- `argument_unavailable`
- `schema_invalid`

Evidence invocation 保存工具版本、Capability、参数摘要、条件、输入 hash、
Schema 状态和耗时。`claim_tool_statistics()` 可从 Evidence 重算请求数、
参数成功率、Schema 成功率以及 pass/fail/unknown/error。

## 3. Fatal capability gate

`hard + fail` 不再自动成为 fatal。Fatal 必须同时满足：

1. Evidence transaction 为 active；
2. 结果为 hard fail；
3. Capability 与 ClaimKind 精确匹配；
4. Host 输入完整并通过 Schema；
5. assumptions/domains 上下文已显式传入；
6. 不是仅表示法或答案形状检查。

因此 `answer.shape`、LaTeX brace、restricted parse 和 numerical sample
均不能淘汰数学候选。Fatal Evidence 可从 `evidence_id → capability →
claim_kind → invocation` 完整反查。

## 4. 答案正规化

在 AnswerValidator、`answer_type_check` 和候选等价判断之前统一处理：

- `Answer:`、`Final answer:`、`\boxed{}` 和数学定界符；
- 整数符号与前导零；
- 普通分数和 LaTeX 分数约分；
- 集合元素顺序；
- tuple/vector 的括号和转置写法；
- interval 的 infinity/union 写法；
- LaTeX matrix 与嵌套列表矩阵。

格式不同但数学表示等价的答案不会仅因 shape 正则差异而 hard fail。

## 5. Proof 与 Repair

Verifier 正常返回时仍执行严格 ProofCompletionGate。只有
`verifier_unavailable` 或 `finalize_cutoff` 才允许确定性退化，而且候选
必须已有适用的 semantic hard pass、没有 fatal evidence、没有 failed
obligation。Verifier 返回 malformed/empty finding 仍 fail closed。

Repair 继续只修改失败 Claim 的依赖影响闭包，并创建新版本。以下情况回滚：

- 失败 Claim 或已验证依赖未重新验证；
- Answer shape patch 无效；
- 新依赖图无效；
- fatal evidence 仍存在；
- 新 Evidence 质量下降。

RunMetrics 1.4 和 Benchmark Summary 新增：

- tool argument success rate
- tool Schema success rate
- tool unknown/error rate
- Repair success rate
- Repair rollback rate
- evidence-quality rollback count

## 6. 自动化验收

`tests/test_phase4_evidence_tool_proof_closure.py` 覆盖：

- 9 个工具示例通过同一运行时 Schema gate；
- Claim 参数成功/未知/错误统计可重复计算；
- capability 不适用、输入不完整和 answer-shape failure 均不可 fatal；
- 分数、集合、向量和矩阵等价表示；
- Verifier 不可用时的确定性保留；
- Claim topology 参与方法独立性；
- Tool/Repair 汇总指标。

既有 Repair 测试继续覆盖影响闭包、版本化、重验、证据下降回滚和非法
Answer patch 回滚。

## 7. 边界

本阶段没有启动在线模型或 88 题评测。真实数据上的工具参数成功率和
Repair 收益将在 Phase 7 按同 commit、同配置和同数据集重新测量；在此
之前 Competition 状态继续保持 `candidate-unvalidated`。
