# ADR-003：真正多 Agent 改造 Phase F0 基线与治理冻结

> 状态：Accepted
> 日期：2026-08-07
> 审查源提交：`b5a743426a85c7d843215dec590497a61f0067f2`
> 实施范围：Phase F0，仅治理与基线，不改变运行行为

## 背景

`MATH_AGENT_TRUE_MULTI_AGENT_FINAL_ARCHITECTURE_AND_IMPLEMENTATION_PLAN_2026-08-02.md` 已将目标定义为：每题强制 RouterPlanner 首调用、固定认知角色各自独立调用模型、显式 Message/Artifact 通信、至少两个独立 Candidate、Solver 交叉审阅、Verifier/Repair/Final Audit 闭环，并受题目并发 3、全局 200 RPM、题级有限调用上限和 Deadline 约束。

审查源提交仍是中央 Harness 驱动的多角色流水线。`config/competition.json` 仍为 `candidate-unvalidated`，`max_model_calls=6`，`enable_router=false`；这些是整改前事实，不是目标设计。Phase F0 若直接修改这些字段，就会把治理冻结与运行时重构混在同一阶段，破坏阶段可验证性。

## 决议

1. 将 2026-08-07 日志驱动修订后的最终方案同步到仓库并作为后续 F1–F8 的唯一权威设计。
2. 2026-08-01 方案保留为历史审查材料，但状态标记为 superseded；其中六次调用闭环不再是目标架构。
3. 新增 `data/true_multi_agent_phase0_baseline.json`，记录审查源提交、运行配置快照、Prompt/Skill/Data 哈希、模型可观测性和目标约束。
4. 保存 `data/true_multi_agent_phase0_competition_snapshot.json`，使后续 F1 修改正式配置后仍可复核整改前事实。
5. 恢复并扩展 `tests/test_phase0_0730_baseline.py`，重新纳入既有 Phase 0 数据、符号等价、传输和 Schema 基线，并增加本 ADR、权威方案与基线登记的一致性测试。
6. F0 不修改 `main.py`、`llm_client.py`、`user_agent.py`、`mathforge/**`、Prompt、Skill 或活动 Competition 配置。

## 真正多 Agent Definition of Done

最终 DoD 以权威方案第 39 节为准。任何“真正多 Agent 已完成”的声明至少要求：

- 每题第一个认知模型调用属于 RouterPlanner；
- Router、Primary、Alternative、Lemma、Peer Review、Verifier、Repair（触发时）和 Final Audit 使用独立 Agent 身份与独立模型调用；
- Agent Action 能实际改变 Task，通信具备 sender、recipient、thread、reply 和 Artifact 引用；
- 每题至少形成两个首次发布前相互隔离的 Candidate，并完成双向 Solver Peer Review；
- hard evidence、proof obligation、claim-local Repair、重新验证、回滚和 Final Audit 因果闭合；
- 长程推理由多轮 Progress 推进，不受旧六次或固定轮数限制，但受显式有限题级上限、软检查点、Deadline、并发与 RPM 治理；
- 阶段超时和输出 Token 按 Turn 类型校准，`finish_reason=length` 不得伪装为完整 Candidate；
- 三题并发、全局 200 RPM、题内状态隔离、公共 Trace 隐私和不可变入口契约全部通过测试。

F0 只冻结上述 DoD，不满足这些运行时条件，因此 F0 完成后项目仍不得宣称已经是真正多 Agent。

## 模型身份解释

正式不可变 `llm_client.py` 的默认请求模型为 `intern-s2-preview`，并允许官方环境通过 `INTERN_MODEL` 覆盖；注入的 `client.chat` 只返回 assistant content，响应模型和 thinking mode 不可观测。自定义 benchmark 对 `intern-s2-preview-397b` 的精确模型校验是另一入口事实，不能反推正式注入客户端实际响应身份。

## 后果

- F1 必须先实现并发 3、200 RPM、48 次题级有界预算、分层阶段超时与后台尾调用治理；F0 的登记不等于这些能力已经存在。
- F4 才实施多轮 Progress、分类型 Candidate Token Contract 和真正的 Solver/Lemma Agent 自主循环。
- Competition 状态继续为 `candidate-unvalidated`，只有 F8 真实并发测试和消融通过后才能晋升。
- 每一后续阶段必须更新测试和 CHANGELOG，并单独提交；不得修改 `main.py`、`llm_client.py`。
