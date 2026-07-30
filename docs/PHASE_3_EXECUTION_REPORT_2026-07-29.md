# Phase 3 Candidate v2 与跨审阅数据契约执行报告

> 日期：2026-07-29  
> 阶段结论：完成  
> 验证方式：Captured response、解析故障注入、Repair/Runtime 离线回归

## 1. 完成范围

1. Candidate v2 增加 Host 可信的 `source` 和 `parse_tier`；
2. Candidate 来源支持：
   `llm_primary`、`llm_alternative`、`llm_repair`、
   `llm_finalizer`、`deterministic_shadow`、`lemma_guided`；
3. Parser 将响应分为 `strict`、`recovered`、`answer_recovered`、
   `rejected`；
4. Candidate ID、role、answer type、source、parse tier、version 和
   MethodSteps 均由 Host 生成或规范化，模型字段不能覆盖；
5. 缺失模型 `method_steps` 不再丢弃 Candidate，Host 会从规范化 Claims
   构建 MethodSteps；
6. 字段别名、Markdown fence、外层文本和安全 Host 字段偏差可恢复；
7. 从超长响应末尾反向寻找完整 Candidate，避免前部残缺 JSON 遮蔽末尾结果；
8. 方法字符串差异从 Candidate hard gate 降为 diversity signal：
   Candidate 可进入验证，但不能凭错误方法标签获得独立方法一致性加分；
9. `answer_recovered` 必须经过确定性答案形状/证据门，工具关闭时不能直接进入
   Competition 成功闭环；
10. RepairAgent 输出 `CandidatePatch`，只包含受影响 Claim 替换、局部公共步骤、
    最终答案和未决项；
11. Host 将 Patch 合并到原 Candidate，未受影响 Claims、方法、条件和版本链不会
    被模型重写；
12. 既有 reverify、证据质量比较和回滚规则继续生效；
13. 新增 `CandidateReviewSummary` 与 `CandidateConflictMatrix`；
14. Cross-review 数据只包含公共步骤、关键 Claims、答案、方法、假设和未决项，
    不包含 `solution_text` 或私有推理；
15. Primary、Alternative 和 Repair Prompt 已简化，Verifier 继续使用公共摘要契约；
16. Alternative 仍只接收问题与禁止的方法标签，不接收 Primary 全文。

## 2. Candidate 接收策略

| 等级 | 条件 | 后续要求 |
|---|---|---|
| `strict` | 裸 JSON、字段完整、无偏差 | 正常证据与仲裁 |
| `recovered` | 可安全修复的 JSON，仍有答案、公共步骤和 Claims | 正常证据与仲裁，Trace 标记恢复 |
| `answer_recovered` | 只能可靠提取答案和公共步骤 | 必须通过确定性 answer/evidence gate |
| `rejected` | 无可靠答案、截断/畸形对象不可恢复 | 拒绝或使用 Primary 保留调用 |

`solution_text` 中再次包裹结果 JSON 仍作为硬契约错误拒绝，避免输出协议被嵌套结果
污染。

## 3. Repair Patch

模型只允许返回：

```json
{
  "replacement_claims": [],
  "final_answer": "",
  "public_solution_steps": [],
  "unresolved_obligations": []
}
```

`source_candidate_id`、`base_version` 和 `affected_claim_ids` 由 Host 注入。
Patch 中出现未授权 Claim 会被 Schema 拒绝。合并后只对影响闭包重新验证，证据质量
下降、关键失败仍存在或最终答案缺少依赖路径时回滚。

## 4. Cross-review 数据边界

`CandidateReviewSummary` 不携带原始模型响应和完整 `solution_text`。
`CandidateConflictMatrix` 仅确定性比较答案、方法、假设和未决义务。真正的交叉审阅
调用与自适应触发属于 Phase 4，本阶段只冻结安全数据契约。

## 5. 验收证据

- Captured Candidate replay：全部接收，达到计划要求的 ≥95%；
- fence、别名、Host 字段注入：安全恢复，Host ownership 保持；
- 超长响应末尾 Candidate：成功提取；
- 方法字符串差异：只调用一次模型，Candidate 保留；
- 自然语言答案恢复：通过 answer gate 时接收，失败时拒绝；
- RepairAgent：返回 `CandidatePatch`，无 `method`/`solution_text`；
- Repair Runtime：局部合并、重新验证、错误答案回滚均通过；
- Cross-review 序列化：不包含完整解答文本或私有推理；
- Candidate Trace/Case summary：公开 `source` 和 `parse_tier`。

全量门禁：

```text
python -m compileall -q .                  passed
pytest -q                                  517 passed, 6 xfailed
python scripts/verify_baseline_files.py     passed
python scripts/validate_submission.py       passed（仅保留既有冻结警告）
python scripts/verify_build_provenance.py   passed
```

## 6. 边界说明

Phase 3 没有提前实现 Adaptive Fanout、LLM Cross-review 调用、Shadow 求解器或
Proof Obligation 推断；这些仍按计划分别属于 Phase 4–5。当前新增对象是后续闭环
可直接使用的数据契约，不额外消耗模型调用。
