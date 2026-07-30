# Phase 4 执行报告：公开长程 ReasoningState

日期：2026-07-30  
依据：`MATHFORGE_FULL_PROJECT_STABILITY_ACCURACY_AND_LONG_HORIZON_AUDIT_2026-07-30.md`

## 1. 阶段结论

Phase 4 已完成。项目现在具备有限、公开、版本化、预算感知的单题长程推理
闭环：

```text
ProblemIR
  → ReasoningState v1
  → explore ProgressDelta
  → [continue ProgressDelta]
  → synthesize CandidateSolution
  → 原有 Evidence / Verify / Arbitrate / Emit
```

简单题仍走一次 `synthesize`；高难度题只有在调用数、Provider 健康状态和
阶段 p95 时间储备同时满足时才进入 2–3 轮。进展协议、状态转换或压缩失败
不会淘汰已有答案，也不会把整题直接判为失败：首轮失败回到原直接 Candidate
生成，后续轮失败则从最后一个合法公开状态执行综合。

本阶段没有修改冻结的 `main.py` 和 `llm_client.py`，没有新增模型客户端、
API Key、模型环境变量或网络依赖。所有模型调用仍只经过注入的
`client.chat(messages, temperature, max_tokens)`。

## 2. 已完成内容

### 2.1 版本化公开状态

新增 `mathforge/harness/reasoning_state.py`，定义并严格验证：

- `ProblemFrame`：完整保留原题、规范题面、定义、量词、约束、假设、目标、
  目标类型和答案类型；
- `SubgoalLedger`：保存 Subgoal、依赖、状态和可观察退出条件，依赖必须存在
  且无环，已关闭 Subgoal 不允许重新打开；
- `ClaimLedger`：保存公开原子 Claim、依赖、所属 Subgoal、状态和重要性，
  禁止未知依赖和依赖环；
- `RoundDelta`：保存每轮公开摘要、策略、Subgoal/Claim/Obligation 变化、
  矛盾、下一步、停止原因和 Host 计算的信息增益；
- `ReasoningState`：使用稳定 `state_id` 和单调 `version` 绑定
  `ProblemFrame`、两个 Ledger、开放义务、Evidence 引用、矛盾与轮次历史。

模型只能提出公开 `pending` Claim，不能自报 hard verified、修改 Host
版本字段或写入私有思维链字段。状态更新采用新对象提交，不共享可变题内状态。

### 2.2 三种 Prompt 协议

PrimarySolver Prompt 合同升级到版本 3：

1. `explore`：分解精确目标，建立第一批公开 Subgoal、Claim 和开放义务；
2. `continue`：只消费上一版本公开状态，推进少量未完成目标，不重复未变化
   内容；
3. `synthesize`：从公开状态闭包生成完整 `CandidateSolution`，保留所有原题
   条件和 Claim 依赖，并列出仍未完成的义务。

`ProgressDeltaParser` 拒绝 `scratchpad`、`chain_of_thought`、
`private_reasoning`、raw response/prompt/completion 等字段。Alternative
保持独立单轮 `synthesize`，不会看到 Primary 的公开状态全文。

### 2.3 预算感知轮次决策

`LongHorizonPolicy` 同时检查：

- 路由必须为 `high`，且 RoutePlan 允许至少两轮；
- Provider 必须健康；
- 必须给 Verifier、请求的 Alternative 和一次 Primary 恢复保留调用；
- `primary` 阶段序列的冻结 p95 与排队储备必须小于剩余时间。

竞赛配置 `max_model_calls=6` 时，高难题默认最多使用
`explore + synthesize` 两轮，同时保留两个候选分支、Verifier 和 Primary
恢复容量。调用预算达到 7 以上且其他条件满足时，可进入
`explore + continue + synthesize` 三轮。所有路径仍受 850 秒 Harness
硬截止和 900 秒外层边界约束。

### 2.4 Token 压缩和 256K 不变量

`ReasoningStateCompressor` 使用固定 Intern-S2 tokenizer 或已记录的多语言
估算器按 Token 计数，状态预算为 32,768 Token。压缩顺序只移除旧轮次的重复
公开摘要和多余矛盾记录，不删除：

- 原题、定义、量词、约束和目标；
- Subgoal 及其依赖；
- Claim 及其依赖；
- 开放义务。

若数学核心本身超过状态预算，长程扩张停止并回到稳定求解路径。每次实际模型
调用继续由 Provider 强制：

```text
prompt_tokens + max_output_tokens + safety_margin_tokens <= 262144
```

Trace 同时公开 Prompt Token、输出上限、8,192 Token 安全余量、计数模式和
实际输出 Token。

### 2.5 Trace 3.3

Judge Trace 升级为 3.3，增加：

- `reasoning_state_initialized`；
- `long_horizon_planned`；
- 每轮一个 `round_summary`；
- `reasoning_loop_completed`。

`round_summary` 记录 `state_id/version`、轮次和模式、新增/更新/关闭的
Subgoal ID、Claim ID 与依赖引用、Evidence ID、开放/关闭义务、信息增益、
下一步、停止/降级原因和状态 Token。它不保存完整失败候选、原始模型响应、
绝对路径、秘密或私有推理稿。

### 2.6 稳定产出回退

- `explore` 协议无效：保留安全原因码，立即回到原直接 Primary 求解；
- `continue` 失败：保留最后一个合法状态并进入 `synthesize`；
- 长程 `synthesize` 失败：原 CandidateOrchestrator 仍可运行直接 Primary
  或 Alternative；
- 状态投影失败不会否定已经生成的 Candidate；
- 简单题不增加 Progress 调用。

## 3. 验收结果

| Phase 4 验收门 | 结果 | 证据 |
|---|---|---|
| 必须跨两轮的任务能引用第一轮状态 | 通过 | 第二轮 Prompt 包含第一轮 `r1-c1` 和 `o1`；三轮路径继续引用 `r2-c1` |
| 条件、定义、量词、目标和关键依赖不丢失 | 通过 | State round-trip 与压缩投影逐字段相等测试 |
| Prompt + 输出 + 安全余量始终不超过 256K | 通过 | 每个 `model_call_record` 的硬不等式回归测试 |
| 不出现私有 CoT | 通过 | 协议拒绝私有字段，Judge Trace 敏感字段扫描通过 |
| 单题仍在 15 分钟内 | 通过 | 850 秒 Harness 硬截止、900 秒外层边界保持不变；轮次按 p95 时间准入 |
| 简单题保持单轮 | 通过 | 简单题只产生一次模型调用和一个 `synthesize` 摘要 |
| 跨题状态零污染 | 通过 | 同一 Harness 连续两题的 `state_id`、题面和公开状态相互隔离 |
| Progress 失败仍稳定产出 | 通过 | 无效首轮 Delta 后直接 Candidate 回退，`final_response` 非空 |

## 4. 自动化验证

最终验证结果：

```text
python -m compileall .                         passed
pytest -q                                      598 passed in 130.94s
python scripts/verify_baseline_files.py        passed
python scripts/validate_submission.py          passed（仅保留冻结前治理警告）
python scripts/verify_build_provenance.py      passed
python scripts/verify_content_reviews.py       passed
python scripts/scan_secrets.py                 passed
git diff --check                               passed
```

新增 8 项 Phase 4 回归覆盖 Schema round-trip、非法依赖、私有字段拒绝、Token
压缩、两轮、三轮、简单题单轮、Progress 故障回退、Judge Trace 和跨题隔离。
全量 598 项测试全部通过。

本机可用的 mypy 对新增 `reasoning_state.py` 未报告类型错误；全项目仍有既有
的 `math_ir`、SymPy 类型、Runtime Optional 窄化等静态类型债务，属于计划
Phase 7 的全仓类型治理范围，不在本阶段混入无关重构。当前 Python 环境未安装
ruff 模块，因此没有伪报 ruff 通过。

## 5. 配置与治理

- `competition.json` 启用 `enable_long_horizon=true`；
- `safe.json`、`balanced.json` 保持关闭，避免未经真实 A/B 就改变这些画像；
- `effective_config_snapshot` 公开三种协议、最大轮次、状态 Token 上限及
  “只保存公开状态”边界；
- Phase 0 配置基线 manifest 已重建；
- Prompt 合同、PromptCompiler 和 ReasoningState 的工程审查哈希已更新；
- 构建 provenance 已重新绑定内容审查 manifest；
- 配置状态仍为 `candidate-unvalidated`。

## 6. 未提前执行的后续阶段

本阶段未调用真实 Intern-S2-Preview-397B，也没有声称准确率已经提升。真实
模型的温度、输出长度、两轮/三轮收益、调用次数和一般高难度集正确率必须在
Phase 8 使用官方注入 Client 做冻结 A/B 后才能把配置改为 `validated`。

以下内容继续按原计划留给后续阶段：

- Phase 5：根据 Subgoal/FailureCode 动态选择 Skill、Host 中介工具结果回注；
- Phase 6：题目前置 Proof Obligations、完整公开解答复审、冲突交叉审阅和
  原子 Repair/Reverify；
- Phase 7：拆分 Runtime、全仓 mypy/ruff/coverage 治理和 Runner 复用；
- Phase 8：真实模型重复实验和发布候选判定。

## 7. 版本控制状态

阶段实现、测试和提交前校验均已完成。报告生成时，当前 Codex 会话将 `.git`
挂载为只读，`git add` 无法创建 `.git/index.lock`，因此尚未产生 Phase 4
提交；最新仓库提交仍为 Phase 3。该限制不影响上述工作区改动和测试结论。
