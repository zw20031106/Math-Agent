# Math-Agent R0–R2 实施状态报告

日期：2026-07-22  
基线审查：`docs/DEEP_IMPLEMENTATION_AUDIT_2026-07-22.md`

## 1. 结论

R0、R1、R2 已按深度审查后的整改计划完成代码实现和自动化验证。三个阶段关闭了以下最高优先级问题：

- Benchmark 后缀误判、fallback 成本漏计、并发归属不可核验和结果缺少来源元数据；
- VerifierSkeptic 未进入生产链路、required proof obligations 不构成完成硬门槛；
- 工具证据不可复现、符号反例忽略定义域、Repair 漏验失败 Claim 和复用旧推导文本。

完成 R0–R2 后，项目的评测可信度、证明完成条件和修复事务完整性已经显著提高；但项目仍不能标记为“最终榜单配置已冻结”。真实 A0–A9 重复消融、deadline 强制执行、Prompt Contract 统一驱动、CEPC 全角色接入、RAG 排序和方法独立性仍属于后续 R3+ 范围。

## 2. R0：评测可信度

状态：已实施并提交（`b8219a6`）。

已完成：

- 删除 `actual.endswith(expected)` 判分，新增按答案类型选择的 scorer；
- choice/integer 严格匹配，fraction 精确有理数比较，expression 符号等价，set/interval/matrix 结构比较；
- proof/text 默认不自动判分，只有显式 scorer 才参与 accuracy；
- 区分模型答错、未评分和评分器错误，新增 unscored 与 scoring failure 指标；
- 每个样本均进入调用/token 均值，fallback 路径写入最终 `budget_summary`；
- 每个 Benchmark 请求携带确定性 nonce，Harness 独立计算并回传 request fingerprint；
- 检测重复 session、缺失 fingerprint 和 fingerprint mismatch；
- Benchmark 产物写入 schema version、dataset/config SHA-256、Git commit 和配置状态；
- `config/competition.json` 标记为 `candidate-unvalidated`，不再宣称已经证据冻结。

关键验收：

- 期望 `2`、实际 `42` 判错；
- `(x+1)^2` 与 `x^2+2*x+1` 判为等价；
- fallback 样本成本进入均值；
- 错误请求 fingerprint 被计为并发污染。

## 3. R1：Verifier 与证明完成硬门槛

状态：已实施并提交（`a78596d`）。

已完成：

- 新增生产 `VerifierSkepticAgent`，对同一题全部候选执行一次批量模型调用；
- Skeptic 只接收原题、结构化 Claims、假设、定理、答案和 obligations，不接收候选完整私有推导；
- Skeptic 所有结论固定为 soft evidence，不能覆盖确定性 hard fail；
- pass 必须绑定真实 candidate、真实 Claim 和该 Claim 已映射的 obligation；
- 新增 `ProofCompletionGate`，proof/derivation 只有 required obligations 全部获得映射证据才可进入仲裁与 Finalizer；
- Router 已占用调用时压缩候选数，为一次批量 Skeptic 调用保留预算；
- verifier 无预算、输出非法或 obligations 未完成时保守 fallback。

关键验收：

- claimless 的 `Assertion only / QED` 即使 Skeptic 虚报 pass 也被拒绝；
- 结构化 definition/sufficiency/boundary Claims 与 findings 正确映射时通过；
- 非法 verifier 输出不能完成证明；
- hard fail 不能被 soft pass 覆盖；
- Router + 两个 solver + 一次 batch verifier 在四次调用预算内完成。

## 4. R2：可复现 Evidence 与完整 Repair

状态：已实施（本报告所在 R2 提交）。

已完成：

- `EvidenceRecord` 新增 invocation；工具证据保存 tool name/version、实际 arguments、assumptions、domains、timeout、duration 和稳定 input digest；
- `ToolResult`/`ToolDefinition` 增加版本并在 Direct、隔离 worker、StdIO MCP 间一致传递；
- `symbolic_equivalence` 升级为版本 2：全局化简为零仍是 hard pass，反例只有满足全部已解析假设和定义域时才是 hard fail；
- 多符号反例使用独立笛卡尔积取值；无法完整解析上下文时降级为 medium unknown；
- ProblemIR 与 Candidate assumptions、domains 进入 Claim 工具调用和证据摘要；
- Repair scope 覆盖失败 Claim、上游前提和全部下游消费者；
- 每个原 hard-failed Claim 必须获得新版本 hard pass；changed 及此前 verified 的受影响 Claim 也必须重新 hard pass；
- Repair 重新执行候选级 answer type hard gate；
- 接受 Repair 后从合并后的 Claim 图确定性重建 solution text，不再复用旧推导；
- Router 和 Repair 模型响应补入 token 统计。

关键验收：

- `sqrt(x^2)=x` 在 `x>=0` 下不会 hard fail；
- `x<0` 下可产生定义域有效 hard counterexample；
- 同一 invocation 的 input digest 不受执行耗时影响；
- 只重验依赖而漏掉原失败 Claim 必须回滚；
- 漏验此前已验证的受影响依赖必须回滚；
- 修复后答案类型错误必须回滚；
- 被接受修复的最终文本包含新 Claim，且不包含旧的错误推导。

## 5. 当前验证结果

R2 提交前验证：

```text
pytest -q
99 passed

python scripts/verify_baseline_files.py
Official immutable baseline files verified.

python scripts/validate_submission.py
Submission validation passed.
```

同时通过 `python -m compileall mathforge tests` 和 `git diff --check`。

## 6. 尚未关闭的风险

以下事项没有被 R0–R2 掩盖或错误标记为完成：

1. 尚无真实官方评测数据与重复 A0–A9 消融，因此 `competition.json` 仍是候选配置；
2. hard deadline 仍不是底层模型调用可中断的强制超时；
3. Prompt Contract 尚未统一构造全部生产角色消息；
4. CEPC/Blackboard 尚未成为所有角色唯一上下文入口；
5. RAG 的 BM25/trust/condition 复合排序和连接释放仍待整改；
6. Alternative 方法独立性与重复候选降权仍未形成可靠闭环；
7. domain/assumption parser 只覆盖受限常见语法，复杂谓词会保守返回 unknown；
8. 仍需真实长时并发、慢客户端、P50/P95 和故障注入测试。

因此，当前结论是：R0–R2 的计划目标已完成，项目继续满足赛题基本接口与安全约束，但“competition-grade 最终完成”和“榜单配置冻结”仍需后续阶段及真实评测证据。
