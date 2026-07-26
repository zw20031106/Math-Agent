# Phase 5 Trace 与可观测性实施状态

日期：2026-07-26
状态：已实施，待真实同版本评测随 Phase 7 冻结

## 1. 实施边界

本阶段只处理既定 Phase 5：

1. Transport Event 与安全错误分类；
2. Claim—Evidence Proof Graph；
3. Trace 增量落盘；
4. Public/Internal Trace 分离；
5. 单题结构化可视化摘要。

`main.py` 与 `llm_client.py` 保持冻结且未修改。模型调用仍只经过注入的
`client.chat(messages, temperature, max_tokens)`。

## 2. 已完成内容

### 2.1 Transport Event

每题在终态前生成 `model_transport_completed`。每个模型调用只公开：

- 调用序号；
- 固定角色名与内部阶段名；
- `completed/failed/timeout` 状态；
- Transport 尝试次数；
- Response Validation 分类；
- 安全失败码；
- 耗时与输出字符数。

失败码只允许
`auth_or_permission_failure`、`rate_limited`、`provider_5xx`、
`network_connect_failure`、`network_read_timeout`、
`response_shape_invalid`、`empty_response`、
`model_response_deadline_exceeded`、
`model_concurrency_wait_exceeded` 和
`unknown_provider_failure`。原始异常、请求地址、Authorization 和密钥不进入事件。

### 2.2 Claim—Evidence Proof Graph

`proof_graph_completed.graph` 使用 Schema `1.0`，包含：

- Candidate 节点：角色、方法、版本、完整性、候选答案、最终状态；
- Claim 节点：陈述、类型、重要性、验证状态；
- Evidence 节点：能力、强度、状态、事务状态、摘要及是否为 fatal；
- Proof Obligation 节点：类型、必需性、满足状态；
- Candidate—Claim、Claim 依赖、Evidence 支持/反驳/未知、
  Claim—Obligation 和 Evidence—Obligation 边。

所有节点 ID 唯一，所有边必须指向已存在节点，选中 Candidate 必须与仲裁一致。

### 2.3 增量 Trace

`TraceBuilder` 新增可注入的、只接收已脱敏公共事件的 Event Sink。
自定义逐题运行器为每道题创建：

```text
<output-dir>/.trace-journal/<id>.trace.jsonl
```

每个事件单独序列化、刷新并 `fsync`，所以不需要等待单题完成才能看到阶段进度。
Journal 有独立连续的 `journal_seq`，最终公开 JSON 仍保持原有四字段合同。
Sink 失败不会中断数学求解，并由 `trace_streams.journal_failures` 观测。

### 2.4 Public/Internal 分离与资源治理

- Public Trace 只接受白名单 Lifecycle Event；
- Internal Trace 也执行同一敏感信息清理，并额外移除
  `chain_of_thought`、`scratchpad`、`raw_response`、
  `candidate_text` 等私有推理字段；
- 两个流均使用线程锁，支持并发 Candidate 回调；
- Internal resident event 默认硬上限为 4096；
- 即使 `trace_max_events=0`，Public resident event 也有 4096 的安全上限；
- 连续、内容相同的非关键事件归并为 `repeat_count`；
- 超过 32768 字符的非最终答案文本变为
  `preview + chars + sha256`，避免复制无界大 payload；
- “Trace 无字符硬截断”保留为“不对整个 Trace 做武断总字符裁剪”，
  不是允许无限复制原始内部内容。

### 2.5 单题摘要

`case_trace_summary.summary` 使用 Schema `1.0`，直接回答：

- 调用了哪些固定 LLM 角色，各调用多少次；
- 每个 Candidate 是否完整、使用什么方法、候选答案是什么；
- 每个 Candidate 的 Evidence 通过/失败/未知/错误数量；
- fatal Evidence 是什么；
- Repair 尝试、接受、回滚及原因；
- 哪个 Candidate 被选中或为何没有选中；
- Provider 调用、失败类别和尝试次数；
- Proof Graph 节点与未解决 Obligation 数量；
- 从 Candidate 生成到最终 Outcome 的简明决策路径。

摘要只使用结构化公共事实，不生成或恢复模型私有思维链。

## 3. Trace V2 增强不变量

在原有顺序、阶段、Candidate 生命周期、Evidence 引用、仲裁和最终答案不变量上，
新增：

1. Transport call index 连续；
2. Transport failure code 必须来自安全白名单；
3. Proof Graph Schema 正确、节点唯一、边无悬空引用；
4. Proof Graph、单题摘要与仲裁选中 Candidate 一致；
5. 每个 Event 可 JSON round-trip；
6. 最终 Trace 不含敏感字段、API Token、Authorization、绝对本地路径、
   Traceback 或私有推理字段。

## 4. 验收对应

| Phase 5 验收项 | 实现与证据 |
|---|---|
| 可回答角色、Candidate 完整性/答案、Evidence、Repair/淘汰/选中原因 | `model_transport_completed`、`proof_graph_completed`、`case_trace_summary` |
| Provider 失败无需原始异常即可定位 | 安全 Transport failure code 与专项故障注入测试 |
| 无密钥、绝对路径、原始异常和私有推理 | 双流脱敏、最终 Schema 安全扫描、仓库 Secret Scan |
| Trace 增长不导致内存无界或单题超时 | Resident event 硬上限、重复归并、大 payload 摘要、增量落盘 |
| Trace V2/后继 Schema 不变量通过 | Transport/Graph/Summary 交叉引用与篡改拒绝测试 |

## 5. 验证

新增 `tests/test_phase5_trace_observability.py`，覆盖成功调用、Provider 失败注入、
Proof Graph、单题摘要、即时 JSONL、逐题 Journal、公共/内部隔离、Resident 上限、
重复事件归并和 Schema 篡改拒绝。

阶段提交前按仓库合同执行：

```bash
python -m compileall .
pytest -q
python scripts/verify_baseline_files.py
```

此外执行 Ruff、Mypy、Submission Validation 和仓库 Secret Scan。

## 6. 保留事项

- 官方 `main.py` 是冻结基线，不能接入自定义输出目录；增量 Journal 因而只在
  自定义 `scripts/run_case_outputs.py` 路径启用。
- 本阶段不运行新的 88 题真实评测，也不把 Competition 状态改为 `frozen`；
  同版本真实评测、对比和人工冻结属于后续阶段。
