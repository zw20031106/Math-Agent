# Task Report: R0 — Evidence Freeze and Current HEAD Baseline

日期：2026-08-31

## Status

BLOCKED（T01/T02 已完成；T03 等待三次真实重复运行）

## Baseline Commit

`873ce51f6d7415a64fc729309598be6d5f6bad8f`（v3 审查基线）

## Result Commit

`378af8ad1d06cbf37ba50587743c538745d15951`（R0 实现）

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

`data/evidence/historical_official_references.json` 登记了 v3 文档中两次 112 题官方聚合结果：2026-08-25 的 20/112（17.8571%）和 2026-08-29 的 14/112（12.5%）。两条记录均明确标记为 `historical_official_reference`，且 `eligible_for_baseline=false`。登记包含 v3 文档 SHA-256 和数据集 SHA-256，不包含 API key、绝对路径或私有推理文本。

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

## Accuracy Impact

无模型调用、无行为变量变化；无法给出当前 HEAD Accuracy。

## Context / Truncation / Provider Impact

无运行时行为变化；T03 工件 schema 会保留 prompt/completion、truncation、timeout、tail、calls、latency、zero-candidate 和 invalid 缺口。

## Regression Check

R0 定向测试 11/11 通过；最近一次全量测试为 1007/1008，唯一失败是既有 Windows 并发慢客户端 P95 的 0.3 秒严格断言（本机约 0.30–0.32 秒，隔离重复仍可复现），不涉及 R0 逻辑；不放宽该性能断言。compile、immutable baseline、content review、build provenance、secret scan 和 submission validation 均通过（submission 仅保留 candidate-unvalidated/human-review warnings）。

## Rollback Decision

KEEP。实现不改变 solve 行为；T03 未完成时保持 fail-closed，不执行后续 AR Task。

## Next Allowed Task

完成三次同一当前 HEAD 的真实 112 题工件并通过 R0-T03 后，才允许执行 `AR-01`。
