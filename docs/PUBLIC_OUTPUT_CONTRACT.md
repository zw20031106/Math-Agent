# MathForge 公共输出契约

版本：5.0

## 对外字段

`ReasoningAgent.solve(problem, metadata)` 只返回：

```json
{
  "id": 0,
  "status": "success",
  "final_response": "72",
  "trace": [
    {"step": "plan", "content": "公开解题计划"},
    {"step": "reasoning", "content": "可核查的数学推导"},
    {"step": "finalize", "content": "答案提取与 JSON 校验"}
  ]
}
```

- `id`：优先读取 `metadata.id`，否则读取 `metadata.idx`；两者都缺失时为
  `null`。
- `status`：仅允许 `success`、`failed`、`timeout`。只有主求解流程成功才是
  `success`；Fallback、候选生成失败和内部执行失败均为 `failed`；竞赛配置的
  单题 900 秒边界到期为 `timeout`。
- `final_response`：非空字符串。非证明题只返回规范化最终答案；证明题返回
  关键且完整的公开证明步骤与结论。
- `trace`：有序的 `{step, content}` 列表，以 `plan` 开始、以 `finalize`
  结束。它呈现公开、可检查的数学推理和多 Agent 决策链，不输出隐藏思维链。

公共结果没有 `result` 包装，也不暴露 `run_metrics`。后者只保留在内部
Harness、Benchmark artifact 和逐题运行清单中。

非证明题的 `final_response` 不带 `Final answer:` 标签，不携带推导正文，也不
添加外围 `$...$`、`\(...\)` 或 `\[...\]`。分数、表达式、矩阵等答案保留内部
标准 LaTeX 源；选择题仅返回选项字母。证明题保留选中 Candidate 的公开证明，
并在末尾给出结论。非证明题的推导、候选比较和验证过程全部进入 `trace`。

## Prompt 与 Candidate 边界

- Host `CandidateSolution 2.0` 与模型侧 `ModelCandidatePayload 2.1` 是两个明确
  分离的契约。后者只包含 `method`、`final_answer`、`public_solution_steps`、
  `claims`、`solution_text`、`assumptions`、`theorems` 和
  `unresolved_obligations`；身份、角色、答案类型、版本、解析状态、来源、
  `method_steps` 和验证状态由 Host 持有。
- PromptCompiler 与 SolutionParser 共用同一份字段集合、Claim 字段和精确 JSON
  骨架。Parser 为历史夹具兼容接收可选 `method_steps`，生产 Prompt 不再要求模型
  输出该 Host 派生字段。
- Solver 明确接收 Host 判定的 `response_mode`。`answer_only` 仍生成 1--4 个公开、
  可核查步骤供 `trace[0]` 使用，但 `final_response` 只渲染答案；
  `worked_solution` 生成完整推导；`proof_full` 生成完整证明及同构的详细公开步骤。
- `solution_text`、`public_solution_steps` 和 Claim 中的数学公式使用 `$...$` LaTeX
  定界；`final_answer` 单独保持不带定界符的 LaTeX 源，由 Host 统一渲染。
- 以上为生成质量契约，不新增“排版稍有偏差即淘汰”的硬门。原有安全 Schema、
  空答案、依赖图和答案形状门保持不变，避免为了格式美观降低稳定答案产出率。

## Trace 内容

公共 `trace` 使用 Official Step/Content V1，是面向判分的有界审计叙事，不是
内部框架日志或 Debug Journal。内部 Harness 仍保留 Judge Trace V4.0：

- `trace[0]` 固定为 `solution_process`，记录选中 Candidate 的公开方法、
  分步数学过程、LaTeX 结论和 `response_mode`；失败结果以 `unavailable`
  明确标记，不伪造解题过程。
- `trace[1]` 固定为 `workflow_overview`，按“题意解析、路线规划、候选生成、
  验证、必要修复、仲裁、最终格式化”的实际执行顺序汇总结果，并引用后续
  审计事件。Trace 的首要目标是呈现连贯的解题与闭环逻辑，不以压缩字符数
  作为质量目标。
- `model_activity` 按实际调用序号记录固定 LLM 角色、调用目的、关联 Candidate、
  成败状态、Schema 校验结果、Transport 尝试次数、Token 和耗时；不记录 Prompt、
  原始响应或异常正文。
- `agent_protocol` 在 F2 Shadow Protocol 阶段公开 Agent/Task/Turn/Artifact/Message
  的安全因果摘要；模型调用记录同步提供 `agent_id`、`task_id`、`turn_id`、
  `output_artifact_id` 和 `message_id`。Artifact 只保存响应哈希与字符数，既有流程
  仍是候选选择的唯一权威。
- `route_planned` 在 F3 记录 Router 是否真实调用模型、LLM 计划或规则回退来源、
  安全失败原因、Plan 版本、子目标 DAG、Agent Task 提议以及 Route/Plan Artifact
  和通信消息引用。正式配置中 Router 是每题首个认知模型调用；其方法族和任务
  绑定会进入后续 Solver 调用记录。
- F4 的 `autonomous_solver_planned` 与 `reasoning_loop_completed` 明确记录
  `fixed_planned_rounds=false`、Agent Action/Progress/Candidate 尝试、停滞停止、
  弃权和截断恢复统计；不再把自主循环伪装为旧的固定轮次循环。
- `llm_lemma_curator_completed`、`lemma_request_completed`、
  `agent_tool_request_completed`、`agent_replan_completed`、
  `candidate_partial_recovery_started` 和 `proof_token_canary_degraded` 记录 F4

- F5 的 `candidate_pool_initialized` 公开候选作者、独立模型 Turn、方法签名和
  结构独立性门结果；`peer_review_completed` 与 `rebuttal_completed` 分别记录
  双向 Solver 审阅和作者回应的 Finding/Claim 引用、Artifact/Message/Thread
  谱系。`solver_peer_review_phase_completed` 记录 Concede 或重复候选对下游活动
  Candidate 集合的实际影响。公开 Trace 不包含审阅者或作者的私有思维链。
  的公开通信与降级结果。`agent_protocol.messages` 展示线程化消息引用，但不公开
  Prompt、原始响应、完整失败 Candidate 或私有推理。
- F6 的 `verifier_completed` 公开独立 Cross Exam 的 Critique、actionability 和
  Peer Finding 二阶审查数量；`new_branch_started/completed` 记录 Critique→Router
  Replan→新 Solver Task→再次 Peer Review 的因果链；`final_audit_completed` 只
  描述暂定最终 Candidate 的独立审计，`audit_reentry_decision` 记录是否重新进入
  闭环。`decision_committed` 引用确定性仲裁产生的 DecisionArtifact 以及可用的
  AuditArtifact。Repair 记录固定引用触发它的 Critique；复审生成的新 Critique
  不得覆盖该来源。所有事件仅包含公开状态、ID 和安全失败码。
- `candidate_summaries` 必须包含选中 Candidate 的 `trace[0]` 引用，并为每个成功
  生成但未选中的 Candidate 保留有界 `public_final_answer` 与
  `public_solution_steps`，使候选对比可审计；生成失败的候选不伪造内容。
- 发生修复时，`repair_history` 按尝试记录源 Candidate、修复 Candidate、受影响
  Claim、公开修复步骤、重新验证证据以及 accepted/rolled_back 结果。
- 保留会话/配置、路由/Skill、关键 Evidence、proof completion、仲裁、
  最终选择、预算和终态摘要。
- 公共投影不再复制完整 `effective_config_snapshot`；配置 profile、哈希和模型
  来源保留在 `session_started`，模型调用预算与时延保留在预算摘要中。
- `reasoning_state_initialized`、`long_horizon_planned`、
  `round_summary` 和 `reasoning_loop_completed` 记录公开长程状态版本、
  Subgoal/Claim/Obligation ID 变化、信息增益、下一步、停止及降级原因。
  `round_summary` 不包含私有思维链、原始响应或失败候选全文；高难度题只在
  调用数与 p95 时间储备均可行时进入 2–3 轮，简单题保持单轮。
- `skills_selected` 只记录实际纳入的 Skill 名称、角色、排序、评分和原因，
  不复制未选 Skill 目录和完整片段；`tool_feedback_completed` 记录 Host 构造的工作项数量、工具结果
  状态、结果摘要、摘要哈希、对下一步策略的影响和后续协议。公共投影不包含
  工具参数、完整 payload 或模型私有推理。
- `problem_obligations_planned` 在 Solver 之前记录题目级证明义务；Candidate
  生成后再绑定实际 Claim 并补充方法级义务。Verifier 只接收公开且
  Claim-linked 的解答切片，不接收私有 `solution_text`。
- Candidate 的答案、假设、关键 Claim 或义务发生冲突时，Trace 记录
  answer/claim 级 review target、已审阅与未审阅 target。软模型审阅只形成
  `model_review`，不能把 Proof 标记为硬 `complete`。
- 仲裁证据层级依次为 `hard_evidence`、`independent_corroboration`、
  `model_review`、`not_required`、`incomplete`；实质排名完全相同时使用
  公开 Candidate 内容摘要确定性破局，不使用生成顺序。
- Repair 只有在 Repair 与 Reverify 的调用数和时间均可原子预留时才启动。
  重验证缺失、验证不可用、质量下降或未严格改善时保留原 Candidate，并把
  新 Evidence 事务标记为 rejected。
- 选中 Candidate 的必要公开解题步骤位于首项 `solution_process`；
  `final_answer_selected` 通过 `solution_process_ref` 引用首项，不重复步骤或
  `final_response`，二者通过内容摘要绑定并校验一致性。
- `viable_not_selected` Candidate 额外保留受限的 `public_final_answer`、
  `public_solution_steps`、`proof_status` 和 `selection_reason`，用于审计候选
  对比；被硬门禁拒绝或生成失败的 Candidate 这些字段为空，不暴露 Claims、
  完整响应或私有推理。
- 每题恰有一个受保护的 `closed_loop_health`，汇总模型派发、Primary/Shadow、
  Candidate 数量、Evidence、Proof、Cross-review、Repair、最终选择及具体降级
  原因。该健康度只表示闭环完整性，不代表数学答案必然正确。
- `decision_summary` 以安全聚合形式记录 Frozen Lemma Cache、确定性 Shadow、
  自适应 fanout 和 Candidate Cross-review 决策。
- 最终缩进 UTF-8 JSON、Trace 事件数/字符数、单事件字符数和未选 Candidate
  数量均受命名配置预算约束。超限内容转换为带数量和摘要的结构化记录，不
  破坏 JSON 或裁掉关键终态事件。
- 模型调用失败只记录安全原因码（例如 `provider_5xx`、
  `network_read_timeout`、`candidate_json_incomplete`），不公开 API 密钥、
  绝对路径、原始异常、raw response 或私有推理草稿。

内部 Harness 的 Trace V2 保留完整交叉引用用于运行时验证；本地增量 journal
使用独立的脱敏 Debug Trace Schema。两者都不会由 `ReasoningAgent.solve()`
返回给 judger。

当模型没有返回任何候选内容时，Trace 不会伪造推理链；`status` 为
`failed`，并明确记录失败发生在模型调用阶段。

## 独立文件与即时写盘

```text
python scripts/run_case_outputs.py \
  --input cases.jsonl \
  --output-dir case-outputs \
  --config config/competition.json \
  --concurrency 1
```

运行器先完成输入与清单预检，再依次执行 L0/L1/L2：精确模型身份和 Client
可用性、短且严格的 JSON、缩短版真实数学 Candidate。L2 必须经生产 Parser、
Formatter、Trace 和公共输出契约完整验证。只有三级全部通过后，批量题目才会
启动；“返回了非空文本”不再构成通过。每级状态、耗时、输出上限和 Transport
尝试数写入 Manifest。

官方约 120 秒服务端生成边界、正式请求的 150 秒本地 HTTP 回传窗口和
165 秒 Harness 外层调用窗口相互独立。额外窗口只容纳代理、TLS、缓冲和响应
回传，不扩展服务端生成时间。只有在 10 秒内明确返回的限流、5xx 或连接错误
才允许重试一次；空响应、读超时、不完整 JSON 和 Schema 违约不重复发送同一
大 Prompt。
官方 Client 的内部尝试数固定为 1，外层每次尝试均进入结构化 Metrics。
竞赛配置的模型调用 Gate 并发数为 16；`ReasoningAgent` 同时把活跃题目限制
为 4，每题先调度 Primary，再启动可选 Alternative。本地逐题 runner 使用
滚动 4 题窗口，不会一次性提交完整数据集。
本地运行通过显式参数
`--model intern-s2-preview-397b` 使用官方精确版本字段；Legacy `intern-s2-preview`
当前指向 35B，不能作为 397B 验收结果。角色输出上限分别为
Router/Finalizer 4,096、Verifier 8,192、Repair 12,288、Lemma 16,384、
Alternative 24,576、Primary 32,768 Token；总上下文仍为 262,144 Token，
另保留 8,192 Token 安全余量。

每道题结束后立即：

1. 生成只含 `id`、`status`、`final_response`、`trace` 的
   `case-outputs/<id>.json`；
2. 刷新并同步同目录临时文件；
3. 原子替换目标文件；
4. 原子更新 `case-outputs/run_manifest.json`；
5. 输出并刷新 `CASE_COMPLETED` 行。

成功、失败和超时都会形成非空、可解析、带终态 Trace 的逐题 JSON。竞赛配置
watchdog 为 900 秒，其中 Harness 最迟在 850 秒交还控制权，预留 50 秒
完成序列化和写盘。Candidate 的精确答案最多 16,384 字符；
`answer_recovered` 路径最多 4,096 字符。该限制始终是 Admission 硬门禁，
不会因题型置信度较低而降为警告。如果仍有单题结果违反公共字符、Trace 或
字节契约，runner 会把该题转换为带终态 Trace 的 `failed` JSON 并继续其他
题，不会让一个异常答案中止整个批次。
每次模型排队最多使用 15 秒，角色调用超时从排队开始计算。
模型调用超时后，Python daemon thread 不会被伪称为已取消；它进入有上限的
provider background tail，达到上限后 circuit-open，后续调用快速失败。迟到线程
只能更新不含题目、Candidate 或 Session 引用的 provider 级登记，不能改写已经
返回或落盘的结果。

## 恢复运行

中断后使用同一命令并增加 `--resume`。恢复前会校验：

- 输入 JSONL 与配置文件的 SHA-256；
- case ID 集合、数量、随机种子与并发数；
- 内部指定的模型请求策略、代码 commit/dirty/source 指纹；
- Manifest/Judge Trace Schema 和四字段输出契约版本；
- 已有逐题 JSON 的精确四字段 Schema、ID、状态、非空回答和终态 Trace；
- 逐题文件与运行清单绑定的 SHA-256。

默认只跳过校验成功且状态为 `success` 的题目；`failed` 和 `timeout`
题目会重新执行并原子替换 canonical 结果。可以使用 `--rerun-status` 显式
调整重跑集合。Manifest 1.3 使用 `attempts` 数组，每个题目记录
`attempt_id`；Debug Journal 写入
`.trace-journal/attempt-000N/<id>.trace.jsonl`，因此旧 attempt 的失败证据
不会被重跑覆盖。恢复时，上一条仍为 `running` 的 attempt 会先收尾为
`interrupted`。未知文件、损坏文件、哈希变化或不兼容清单会在题目模型调用前
失败。

Runner 默认并最多允许 `concurrency=3`，滚动调度只为实际启动的题目创建
执行期限。Manifest 依次进入 `created`、`preflight_passed`、
`running`，并以 `completed`、`degraded`、`aborted` 或 `failed` 结束。
SIGINT/SIGTERM 会等待当前题安全写盘、阻止启动下一题并记录 `aborted`。
`--max-cases` 和 `--stop-after-case` 会在目标题写盘后以 `degraded`
终止，后续可用 `--resume` 继续。

## 冻结入口边界

官方 `main.py` 和 `llm_client.py` 不得修改。`main.py` 保留官方样例的
`idx/status/final_response/trace` 包装，并仍会把正常返回强制标为
`success`、在异常结果中增加 `error` 字段且默认并发为 8。本项目的精确
四字段、状态、单题期限、Manifest 和 Resume 契约由
`scripts/run_case_outputs.py` 提供。若要求两个入口完全一致，必须先取得
修改冻结基线的书面许可。
