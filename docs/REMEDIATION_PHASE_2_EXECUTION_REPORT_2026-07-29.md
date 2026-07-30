# MathForge 整改阶段 2 执行报告

日期：2026-07-29  
阶段目标：修正调用预算、响应上下文处理、中文 token 估算和截止预留语义。

## 一、完成项

### F1(c)：未派发调用自动退款

- `ModelCallRejected` 新增 `dispatched` 标记，区分“排队/熔断时拒绝”和
  “请求已派发后超时”。
- Provider 对未派发拒绝调用执行 `CallBudget.refund(stage=...)`。
- 退款同时回退总调用数和对应角色分桶，不影响已经真实派发的超时调用。

采用报告允许的 `(a)+(c)` 组合：阶段 1 已将模型并发提升为 3，本阶段补齐拒绝退款，
避免在未取得 Provider permit 时白白消耗调用预算。

### F4：已完成响应不再因角色软上限直接丢弃

- 区分角色输出软上限和 256K 总上下文硬边界。
- 响应超过角色上限、但 `prompt + response + safety margin` 仍在上下文窗口内时：
  - 保留完整响应供 Candidate Parser 使用；
  - 在 Model Call Record 中记录 `output_budget_exceeded=true`。
- 只有真实超过总上下文窗口时才抛出 `ContextBudgetExceeded`。
- Orchestration 将真正的上下文错误归因为 `context_budget_exceeded`，不再记录为模糊的
  `solver_branch_failed`。

### P3：修正中文 UTF-8 三倍高估

- 保留可选的、哈希固定的 Intern-S2 官方 Tokenizer 本地加载路径。
- 本地没有 Tokenizer 快照时，回退由“一字节一 token”改为可审计的多语言估算：
  - ASCII 非空白：0.5；
  - ASCII 空白：0.25；
  - CJK：1.0；
  - 其他 Unicode：1.5。
- counting mode 改为 `multilingual_estimate`，版本和算法说明参与 provenance 哈希。
- 256K 上下文安全余量仍然保留，不把估算结果冒充官方精确 token 数。

### F7：模型调用预留和本地定稿窗口分离

- `remaining_for_model_call()` 同时扣除确定性定稿预留和模型启动余量。
- `exploration_allowed()` 不再重复扣除启动余量。
- `must_finalize()` 只由真正的确定性定稿预留触发。
- 本地验证/格式化阶段可在剩余硬截止时间内继续执行，模型调用则提前停止。

## 二、验证结果

阶段定向回归：

```text
38 passed
```

覆盖：

- 调用预算和角色分桶；
- 排队拒绝退款；
- 模型截止与本地阶段截止；
- 背景尾单完成记账；
- 多语言 token 估算；
- 角色输出软上限与上下文硬上限；
- Candidate fanout 编排。

## 三、阶段结论

阶段 2 已完成。调用预算现在按“是否真实派发”结算；已经取得的完整模型内容优先进入
解析，而不是因内部软上限被丢弃；中文上下文不再按 UTF-8 字节系统性放大约三倍；
模型探索停止与确定性输出窗口也已分离。

## 四、边界与遗留项

- 仓库中没有可验证哈希的官方 Tokenizer 文件，因此采用报告允许的改进估算方案；
  若部署镜像提供官方快照，系统仍优先使用精确 Tokenizer。
- 阶段 3 将处理 terminalizer 可观测性、Finalizer 空串、证明完备性降级和低优先级清理。
- 配置仍保持 `candidate-unvalidated`。
- `main.py`、`llm_client.py` 保持冻结，未修改。
