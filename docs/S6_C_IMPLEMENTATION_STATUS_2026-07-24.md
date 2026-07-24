# S6-C / E2 实施状态：Trace 2.0 与候选公开推理链

日期：2026-07-24

对应计划：阶段 E2

提交目标：`S6-C: add auditable trace v2 and candidate public reasoning`

## 结论

E2 已将公开 Trace 升级为可机器校验的 2.0 契约。这里记录的是可公开、
可复核的数学解题步骤、Claim、证据与选择依据，不输出模型的私有
chain-of-thought。每次 `solve()` 的公开事件均由 Host 添加：

- `schema_version=2.0`；
- 从 1 开始且连续的 `seq`；
- 非递减的 `elapsed_ms`；
- 由事件类型唯一决定的 `stage`。

运行结束前会检查候选、证据、修复、仲裁、最终答案与 Session 引用；任何
Trace 2.0 输出在 `public_result` 边界还会再次校验。

## 1. CandidateSolution 2.0

`CandidateSolution` 增加 `public_solution_steps`，Schema 版本升级为 2.0。
严格 JSON、围栏 JSON、局部 JSON和原始文本降级路径都会生成公开步骤。

候选生成成功后立即写入：

```text
candidate_generation_started
  -> candidate_generated
     -> candidate_evidence_completed
```

失败分支写入：

```text
candidate_generation_started
  -> candidate_generation_failed
```

成功候选公开 `method/status/public_solution_steps/final_answer/claims/
method_steps/assumptions/theorems/unresolved_obligations` 和绑定完整候选的
内容摘要，但不公开非入选候选的 `solution_text` 或模型原始响应。失败候选
只保留空的安全公开内容、稳定失败原因和已知身份字段。

## 2. Evidence、Repair 与 Arbitration

`EvidenceLedger` 可注册 Candidate → Claim 集合。注册表启用后，未知 Candidate
或未知 Claim 的 Evidence 会在写入前失败。

每个 `candidate_evidence_completed` 记录：

- Candidate ID；
- Claim ID 与 Evidence ID；
- check/capability/status/strength/summary；
- answer-shape 检查；
- hard-fail 与未知 Claim；
- completed 或 skipped 的明确原因。

`repair_proposed` 记录 source/proposed Candidate、受影响 Claim、Claim 局部
before/after、答案变化、公开候选内容和内容摘要；`repair_completed` 记录
回滚、复核 Claim、Evidence ID 与质量结果。

`candidate_arbitrated` 记录：

- viable Candidate；
- 淘汰 Candidate 与原因码；
- 每个候选的 hard fail、required coverage、answer consistency、
  independent agreement、soft score；
- 实际词典序键；
- 等价簇、未知对、分歧对和稳定 tie-break 说明。

`final_answer_selected` 只对最终入选候选公开完整 `solution_text`、公开步骤、
最终答案和实际 `final_response`。

## 3. Trace 完整性门禁

`validate_trace_v2()` 强制执行：

1. seq 连续、elapsed 非递减、stage 固定且所有事件可 JSON round-trip；
2. 每个 Candidate start 恰有一个 success/failure 终态；
3. 每个成功 Candidate 恰有一个 Evidence completed/skipped 终态；
4. Evidence Candidate/Claim 引用存在；
5. Repair source/proposed 引用存在；
6. Arbitration 只引用已生成/已提出 Candidate；
7. selected 属于 viable；
8. final selected 等于 Arbitration selected；
9. `final_response` 等于 selected public solution；
10. `run_completed` 是最后事件。

异常路径会先补齐缺失的 Candidate 生成或 Evidence 终态，再写
`budget_summary` 和 `run_completed`。15 分钟墙钟 Runner 的超时结果也使用
同一 Trace 2.0 终态契约。

## 4. 安全与无截断

Sanitizer 不再对字符串、列表或字典做长度切片。Competition 配置中的
`trace_max_chars=0` 与 `trace_max_events=0` 会保留所有允许公开的合法内容。
正数旧限制下，Candidate、Evidence、Repair、Arbitration 和 terminal 等受
保护事件也不会为满足尺寸上限而被静默删除。

递归清洗仍会移除或替换：

- API key/token；
- Authorization/Bearer；
- benchmark nonce；
- 本地绝对路径；
- traceback/异常对象；
- 非 allowlist/private reasoning 事件。

## 5. 验收覆盖

`tests/test_s6_e2_trace_v2.py` 覆盖：

- 主路径 Candidate → Evidence → Arbitration → Final；
- 一个分支失败时的 start/terminal 一一对应；
- 缺 Evidence、foreign Candidate、错误 final response 的拒绝；
- 超过 1000 字符的公开步骤；
- 超过 32 项的列表和超过 32 键的字典；
- 超过 12000 字符和 64 个事件的完整保留；
- secret、Authorization、路径、traceback、nonce 的递归清洗；
- Evidence 的未知 Candidate/Claim 拒绝；
- Trace JSON round-trip。

提交前执行：

```bash
python -m compileall .
pytest -q
python scripts/verify_baseline_files.py
```

未执行真实 397B 全量测试；该高成本验证不属于 E2 的确定性契约验收。
