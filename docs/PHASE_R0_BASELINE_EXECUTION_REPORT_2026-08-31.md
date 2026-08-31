# Phase R0 执行报告：证据冻结与当前 HEAD 基线

日期：2026-08-31

本阶段只建立可复现的证据边界，不把历史官方聚合结果或未完成的模型运行登记为当前基线。求解行为、Prompt、Provider 和调度策略留到后续阶段修改。

## R0-T01：Current HEAD Identity

新增 `mathforge.evaluation.r0` 和 `scripts/capture_current_identity.py`。身份工件记录：

- Git commit 与工作树状态；
- 源码树、Competition 配置原始 SHA-256 与语义 fingerprint；
- Prompt/Skill 树 fingerprint；
- 精确 Intern-S 模型身份；
- token counting mode 及 tokenizer/fallback provenance；
- Python 与平台信息。

采集命令（不发起模型请求）：

```text
python scripts/capture_current_identity.py
```

输出：`artifacts/current_candidate_identity.json`。

身份工件中的 `git_commit` 和 `code_dirty` 是采集时的权威值；若工作树不是 clean，工件只能作为当前候选的诊断快照，不能直接进入 active baseline。提交本阶段后应重新运行采集命令，使身份快照绑定本阶段提交。

## R0-T02：历史官方结果登记

`data/evidence/historical_official_references.json` 登记了计划文档中两次 112 题官方聚合结果：2026-08-25 的 20/112（17.8571%）和 2026-08-29 的 14/112（12.5%）。两条记录均明确标记为 `historical_official_reference`，且 `eligible_for_baseline=false`。登记包含计划文档 SHA-256 和数据集 SHA-256，不包含 API key、绝对路径或私有推理文本。

这两次结果只能用于回归参考，不能证明当前 HEAD 的准确率，也不能改变 `active_baseline_id`。

## R0-T03：当前 HEAD 112 题基线

新增 `scripts/build_r0_baseline.py`。它只接受带有可比身份、数据集 fingerprint、Competition timing profile 和 summary 的已完成 Benchmark 工件；默认要求至少 3 次重复运行。任何缺失、混用 commit/config/dataset、错误 timing profile 或不足 3 次重复都会输出 `status=blocked`，不会补造 accuracy、truncation 或 Provider 指标。

每次重复会把 `accuracy`、`prompt_tokens`、`completion_tokens`、`truncation`、`timeouts`、`tails`、`calls`、`latency`、`zero_candidate` 和 `invalid` 归一化保存；若原始工件无法提供某项，则显式保留为缺口并阻止基线完成。

示例命令：

```text
python scripts/build_r0_baseline.py \
  --dataset <official-112-dataset> \
  --artifact <run-1.json> \
  --artifact <run-2.json> \
  --artifact <run-3.json>
```

输出：`artifacts/current_head_baseline.json`。R0 工件即使收集齐 3 次重复，也只记录 `active_baseline_eligible=false`；正式激活仍需后续 Release Gate。

本次工作区实际解析到的 `math_agent_boundary_112_v2.json` SHA-256 为
`eeff43c395f2a94260bdffdd5bf7bf9de9f62509ec549b6475a0867fe070738a`。计划中历史聚合表绑定的是
`7f2499c53f52cbcb17dcab7cc4b99c9e79f53e23c1392587289a02695284201f`；两者不一致时不能合并准确率或声称复现，基线工件会以实际输入文件 hash 为准。

## Exit Gate 状态

| 检查项 | 状态 |
|---|---|
| 当前候选身份可验证 | 已实现并有定向测试 |
| 历史官方结果与当前 HEAD 分离 | 已完成 |
| 三次真实 112 题重复运行 | 尚未提供完整工件 |
| 当前 HEAD active baseline | 未激活（fail-closed） |
| API key 写入仓库或工件 | 未读取、未写入 |

因此本阶段的结论是：基线登记链路已经可复现，但在获得同一当前 HEAD、同一配置/数据集、同一模型身份的至少三次完整真实运行前，不对当前准确率作数值结论，也不宣称准确率提升。
