# Phase 7 配置校准与冻结建议

日期：2026-07-31

## 1. 冻结决定

`freeze_eligible = false`。

Competition 配置必须继续保持：

```json
{
  "status": "candidate-unvalidated",
  "model_max_concurrency": 16,
  "max_background_model_tails": 16,
  "max_model_calls": 6,
  "enable_frozen_lemma_store": false
}
```

题级并发保持 4。模型名称由智能体/runner 明确指定为
`intern-s2-preview-397b`，不依赖环境变量注入模型名称；环境只负责官方
Client 所需的认证信息。

## 2. 未通过门禁

自动提案记录以下失败项：

- 真实运行配置哈希与当前配置不一致；
- 88 题输出覆盖不足 100%；
- 状态成功率低于 98%；
- 模型派发成功率低于 98%；
- Candidate 接收率低于 95%；
- 答案评分覆盖不足 100%；
- 人工数学审核和治理签名未完成。

此外，第 80 题暴露的超长恢复答案和写盘异常已成为新的明确阻断项。

## 3. 已实施的校准修正

1. 将物理模型调用 Gate 和 provider background-tail 上限调整为 16，同时
   保持 runner 的四题滚动窗口。
2. 为 Candidate 增加最终答案长度硬门禁；即使题型置信度较低，超长答案也
   不能作为软警告绕过 Admission。
3. 对 `answer_recovered` 设置更小的 4,096 字符答案上限，避免把完整解题
   文本误认作精确答案。
4. 公共输出契约失败只降级当前题为结构化 `failed`，不再终止同批其他题。
5. 数学型最终答案统一渲染为 `$...$` LaTeX；Solver/Repair 输出标准 LaTeX
   源，Host 负责添加唯一的最终定界符。
6. 画像绑定运行时配置哈希；哈希不一致时禁止冻结。
7. 画像只读取数据集内的题目 JSON，不把画像/提案文件误计为题目。
8. 评分使用题型感知等价判断，并覆盖虚数乘法、Unicode 数域、LaTeX 向量。
9. 配置提案显式检查人工审核状态；无签名时不允许提出
   `live-validated`。

## 4. A/B 决策

本轮没有继续启动 Adaptive Fanout、Shadow 和 Frozen Lemma Store 的真实
A/B。原因不是省略计划，而是 Phase 7 明确要求 Live 按 4→16→88 分级且
前一级失败立即停止；当前基础稳定性已经失败，继续 A/B 会把 Transport、
输出契约和策略变量混在一起，无法形成可信因果结论。

- Adaptive Fanout：保留现有离线实现，等待基础 canary 通过后再比较静态/
  动态调用数、P95 和正确率。
- Shadow：继续关闭；后续 A/B 必须证明不会把 unsupported 结果当成硬证据。
- Frozen Lemma Store：审核 Store 记录数为 0，继续关闭，不执行无意义的
  off/on 测试。

## 5. 下一轮验证顺序

下一轮必须在同一代码提交、同一配置哈希和同一模型字段下执行：

1. 4 题 canary，并发 4；
2. 只有输出覆盖、状态成功、模型派发和逐题写盘全部达标后，扩到 16 题；
3. 16 题达标后再执行 88 题；
4. 基础 88 题通过后，按一次只改变一个变量的方式运行 Fanout、Shadow A/B；
5. 人工抽查数学正确性、Cross-review 可执行性和 Closed-loop Health；
6. 完成人工签名后重新生成 Evidence Manifest 和配置提案；
7. 只有所有门禁通过，才把状态改为 `live-validated`。

并发 16 是待验证的当前候选值，不是已经由本轮数据证明的冻结值。
