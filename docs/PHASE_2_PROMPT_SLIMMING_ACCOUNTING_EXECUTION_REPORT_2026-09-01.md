# Phase 2：Prompt 瘦身与记账修复执行报告

日期：2026-09-01

## 范围与目标

本阶段严格对应 0901 全项目重审实施计划的 Phase 2（Prompt 瘦身与记账
修复）。目标是把题目本身置于模型输入的最高优先级，禁止全量会话状态和
解释性 schema 散文进入每一回合，并以真实 observed 输出更新预算观测。实现、
不变量测试和真实 Intern 模型证据分开记录；本报告不把本地测试当作数学准确率。

## 已完成的实现

### 2.1–2.2 状态切片化

- `PromptCompiler` 新增不可变的 `REQUIRED_STATE_FIELDS` 与
  `REQUIRED_REASONING_FIELDS` 表，每个角色明确可见的公开状态字段。
- 编译器识别 `Authorized context view` 与 `Public ReasoningState JSON` 段，
  用声明字段重建 JSON；未声明字段（包括私有状态）不会发送给模型。
- `metadata` 虽属于声明字段，也只投影 `public_metadata` 与题目条件包；压缩时
  保留真实 `context_snapshot_id`、benchmark 关联标识，避免污染探针失去归属信息。
- 编译结果记录 `required_state_fields`、`state_slice_applied` 和
  `state_trimmed`，可在 Prompt 快照中审计。

### 2.3 协议与合同瘦身

- AgentTurn、进展、同行评审、答辩、交叉审查和最终审计协议改为紧凑中文
  system 指令；保留公共协议标识和机器字段名，避免对解析器造成兼容破坏。
- `PromptContract.render_compact_system()` 只发送目标、输入/输出字段、可见/禁止
  状态、工具、失败和停止条件；旧的完整渲染 API 保留供审查和兼容调用。
- runtime protocol 位于 system message，不再在 user 状态段重复编排；输出 schema
  示例只出现一次。

### 2.4–2.5 schema 散文和问题占比门禁

- `strip_prompt_descriptions()` 递归移除模型不需要的 `description` 散文；证据和
  证明义务的描述转换为紧凑 `statement`，不丢失数学语义。
- `RoleContextView.to_prompt_json()` 和 Prompt 编译状态段均应用该清理。
- Prompt 组件按问题、状态、技能、schema 记账；若含状态的动态部分中
  `problem_tokens / total < 0.45`，编译器先裁剪状态，再允许 Provider dispatch。
  没有状态时短题仍可正常完成，不伪造推导内容。

### 2.6 真实用量记账

- 新增 `CallBudget.record_model_call_finished(...)`，以 observed 输出完成记录、
  释放预测预留并更新滑动窗口；旧 `record_model_call_completed` 保留为兼容别名。
- Provider 已切换到 finished API，并记录 tokenizer fallback 次数；输出准入继续
  使用 observed 滑动均值而非申请上限。

### 2.7 tokenizer 预警与预检硬失败

- Intern-S2 tokenizer 无法加载或调用失败时记录 fallback invocation 并发出一次
  明确 warning。
- `run_production_preflight(..., require_official_tokenizer=True)` 在模型调用前以
  `official_tokenizer_unavailable` 于 L0 失败；生产批处理入口已启用该硬门禁。
- 单元测试和离线诊断仍可显式使用多语言估算，不把离线估算冒充官方 token 证据。

### 2.8 上下文自适应输出

`effective_output_tokens()` 继续统一执行
`min(stage_cap, configured_cap, context_window - prompt - safety_margin)`；
Provider 对该值和 `ModelContextBudget.allocate()` 做一致性校验。

## 验证结果

- Phase 2 新增不变量测试：6 项通过。
- Prompt、上下文、预检、预算和长期回归定向测试：103 项通过。
- Prompt 快照已按新 system contract/protocol 指纹更新。
- 提交前全量验证：`python -m compileall .`、`pytest -q`（1026 passed）、
  `verify_baseline_files.py`、内容审查指纹、构建 provenance 和 submission
  validation 均通过；submission 仅保留“candidate-unvalidated/待人工审查”的治理
  警告，不将其误记为数学准确率证据。

## Gate 2 证据边界

当前代码已提供 `prompt_component_tokens`、token counting mode、fallback 次数、
状态裁剪标记和 observed/requested 原始记录，具备本地 30 例 Gate 2 的采集条件。
本阶段尚未运行同一 HEAD、同一 Competition 配置和完整 manifest 约束下的真实
Intern 30 例或官方 112 例；因此不声称平均 prompt、官方 token 占比、截断率或数学
准确率达标。若没有固定 tokenizer，生产 preflight 会按设计失败而不是生成伪造的
`official_prompt_tokens`。

## 风险与回滚

- 状态裁剪只作用于带明确标记的公开 JSON，失败或无法解析时不会伪造部分 JSON；
  原始 checkpoint 仍由 Solver 请求对象保留用于确定性恢复。
- 协议机器标识和旧 API 保持不变；若真实模型显示协议理解下降，可只回滚 compact
  system/protocol 文本，不影响 observed 记账和 tokenizer 门禁。
- 生产入口的官方 tokenizer 硬门禁可能暴露部署缺少固定 tokenizer 的环境问题；应
  安装并校验计划指定 revision，而不是关闭门禁。
