# Math-Agent S2 实施状态报告

日期：2026-07-23

范围：C11、C12、C13、C14

基线提交：`53ac720`

## 1. 结论

S2 的 Router 校准和统一资源控制已经完成工程实现与自动化验收。Router 的
领域置信度、领域歧义和题目复杂度不再混为一个分数；所有 Runtime 模型、
工具和上下文工作共享同一个 Deadline 与会话资源预算。

本阶段没有真实榜单消融，因此 `config/competition.json` 继续保持
`candidate-unvalidated`。

## 2. C11/C12：Router 与风险派生

Router 现在显式计算：

- `routing_confidence`：top-1 领域置信度；
- `ambiguity_margin`：top-1 与 top-2 的差值；
- `complexity_flags`：独立的复杂度信号；
- `ProblemIR.subject_candidates`：完整、稳定排序的领域候选。

top-1/top-2 差值不超过阈值时，即使 top-1 置信度较高，也会保留
auxiliary。`probability + random + matrix + eigenvalue` 的反例现在得到：

```text
primary = linear-algebra
auxiliary = probability
risk = medium
```

复杂度特征覆盖：

- 题目长度；
- 条件数量；
- 符号数量；
- 分段与绝对值；
- 充要方向、逆命题和交换次序；
- 存在唯一性；
- 病态数值；
- 混合领域；
- 证明深度。

`derive_route_policy()` 是唯一的 risk 派生入口，统一生成：

```text
candidate_count
max_reasoning_rounds
use_rag
use_lemma_loop
use_llm_finalizer
```

LLM 可以提升风险，但不能把宿主复杂度规则判定的风险降级。新增
`data/router_calibration.json`，包含 7 条人工标注的代数、线性代数、
概率、微积分、数论、离散数学和证明路由样本。

## 3. C13：会话级资源上限

配置 Schema 升级至 `1.1`，safe、balanced、competition 三套配置完整展开
以下资源字段：

```text
max_claims
max_tool_calls
max_isolated_tool_calls
max_tool_seconds
max_evidence_records
max_prompt_chars_total
model_call_start_margin_seconds
```

资源计数全部属于单次 Session，并由线程安全的 `CallBudget` 统一维护：

- 多候选 Claim 使用同一个总额度；
- 超大 Claim 数在逐 Claim 构造前失败；
- Direct、隔离进程、MCP、Claim verification 和 arbitration
  equivalence 共用 Tool 次数与秒数；
- Evidence Ledger 在写入前预留记录额度；
- Router、Solver、Verifier、Repair 和 Finalizer 的实际 messages
  共用 Prompt 字符总额度；
- `run_metrics` 和 `budget_summary` 输出实际资源使用量。

## 4. C13/C14：共享 Deadline

Runtime 在以下工作开始前检查同一个 monotonic Deadline：

- Problem/Solution parser；
- RAG 检索；
- Context 组装与压缩；
- 模型调用；
- Direct、隔离和 MCP 工具；
- 仲裁答案等价检查。

工具 timeout 固定为：

```text
min(tool_default, remaining_tool_seconds, deadline.remaining_for_stage)
```

模型调用除 deterministic finalization reserve 外，还使用
`model_call_start_margin_seconds`，避免在剩余时间不足以覆盖官方客户端最坏
响应窗口时启动新调用。

## 5. C14：CallAllocationPlan

Router 完成后，Runtime 建立显式调用计划：

```text
router
primary
alternatives
verifier
repair_reserve
lemma_reserve
finalizer_reserve
```

Primary 和需要的 Verifier 先占用必选容量，可选阶段只能使用自己的分配。
Feature 已请求但容量不足时写入 trace 的 `unreachable_by_budget`。

3-call 压力 E2E 已验证：

1. Primary 与 Alternative 使用前两次调用；
2. Primary 的硬失败触发 Repair 条件；
3. Repair 因无分配额度不会调用模型；
4. 最后一次调用仍由 VerifierSkeptic 使用。

## 6. 验收

- 多领域同分反例：通过；
- high-risk 派生一致性：通过；
- 7 条人工路由校准集：通过；
- 恶意 5000 Claim 降级测试：单模型调用、无工具调用、固定时间返回；
- Repair/Verifier 配额竞争 E2E：通过；
- 全量 pytest：204 项通过；
- 分支覆盖率：81%；
- Ruff：通过；
- mypy：79 个源文件通过。

最终提交门禁还包括 compileall、官方冻结基线、公开提交校验、
`pip check` 和 `git diff --check`。
