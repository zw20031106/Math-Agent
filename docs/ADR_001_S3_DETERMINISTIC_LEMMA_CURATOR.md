# ADR-001：LemmaCurator 保持确定性宿主服务

- 状态：Superseded by ADR-004 / Phase F4
- 日期：2026-07-23
- 阶段：S3 / C15–C16

## 背景

> 本 ADR 仅记录 S3 历史决策。2026-08-07 起，正式自主管线依据
> ADR-004 使用独立 LLM LemmaCurator；确定性 Curator 只保留为验证与回退服务。

仓库保留了 `prompts/lemma_curator/contract.md`，但生产链路中的
`LemmaCurator` 实际执行的是从已解析 Claim 到 problem-local LemmaCard 的
确定性转换。若为了角色命名而增加一次模型调用，会增加调用预算、上下文泄漏面和
不可复现性，并且不会替代后续的 evidence capability 校验。

## 决策

S3 保留 `LemmaCurator` 作为确定性宿主服务：

1. 不调用 `client.chat()`，也不加载 Prompt Contract 构造生产消息；
2. Lemma source、ID 和 dependency 全部使用候选命名空间；
3. 只有携带匹配 active Evidence capability 的 Lemma 才能进入 verified
   memory；
4. 第二轮 Solver 只接收原题、必要 conditions 和 verified LemmaCard；
5. `prompts/lemma_curator/contract.md` 仅作为待 S5 人工内容审核的非活动模板，
   不计入“Prompt Contract 驱动的生产角色”。

## 后果

- Lemma 抽取不消耗额外模型调用，行为可以离线复现；
- 角色数量与生产模型调用数量不再混为一谈；
- 若未来真实消融证明模型化 Curator 有稳定净收益，必须通过新的 ADR、调用预算、
  RoleContextView 和完整回归门禁后才能启用；
- 当前 `competition` 配置仍为 `candidate-unvalidated`。
