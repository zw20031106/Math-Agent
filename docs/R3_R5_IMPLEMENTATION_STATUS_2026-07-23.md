# Math-Agent R3–R5 实施状态报告

日期：2026-07-23  
审查基线：`docs/DEEP_IMPLEMENTATION_AUDIT_2026-07-22.md`

## 1. 阶段结论

R3、R4、R5 已按深度审查后的整改计划完成实现，并分别形成可审计提交：

| 阶段 | 提交 | 结果 |
|---|---|---|
| R3 方法独立性与 Prompt Contract | `ce81ef3` | 已完成 |
| R4 CEPC、角色视图与 Memory 主链路 | `fead2da` | 已完成 |
| R5 Deadline 与并发稳定性 | `430ae94` | 已完成 |

阶段完成后的自动化测试数量从 R2 的 99 项增加到 110 项。不可修改的官方基线文件和赛题提交结构仍通过校验。

这表示 R3–R5 计划中的工程验收项已经闭环，但不表示最终榜单配置已经冻结。R6 的 RAG/MCP 整改和 R7 的真实数据集重复消融尚未执行，`config/competition.json` 因此继续保持 `candidate-unvalidated`。

## 2. R3：方法独立性与 Prompt Contract

已完成：

- `RoutePlan` 显式输出有序 `method_families`；
- Primary 和 Alternative 分支分别获得一个必选方法族及互斥的禁用方法族；
- 模型输出的实际方法签名参与重复检测，不能只依赖计划标签；
- 重复方法候选标记为 `duplicate_method`，仲裁时不再贡献独立答案一致性分；
- Router、Primary、Alternative、Verifier、Repair 和 Finalizer 的 system/user messages 统一通过 `PromptContractLoader.messages()` 构建；
- Prompt Contract 的可见上下文、禁止上下文、工具、失败策略、停止条件和最大字符预算进入生产消息；
- 增加方法族分配、重复降级、合同字段和静态上下文边界测试。

关键验收：

- 多分支获得不同的核心方法族；
- Alternative prompt 明确禁止 Primary 使用的方法族；
- 两个实际方法签名相同的候选，即使答案相同，独立一致性贡献仍为 0；
- 所有生产 LLM 角色不再各自硬编码 system prompt。

R3 提交前验证：101 项测试通过。

## 3. R4：CEPC、角色视图与 Memory 主链路

已完成：

- 新增 `RoleContextView` 和 `RoleContextFactory`，在生产角色调用前从当前题目状态构建独立快照；
- Blackboard `view(role)` 成为角色读取 memory 的授权入口；
- Router、Primary、Alternative、Verifier、Repair 和 Finalizer 均接收角色化上下文视图；
- Alternative 不能读取 Blackboard working memory，也不能看到 Primary 的完整推导；
- Verifier 只接收结构化 claims、evidence 和 obligations，不接收 `solution_text`；
- Repair 只接收失败 Claim 的依赖/影响闭包和局部证据；
- Finalizer 只接收最终选中候选及其相关证据和 obligations；
- 所有角色消息受 Prompt Contract 硬字符预算约束；
- 压缩无法满足硬预算或不变量时抛出 `ContextBudgetExceeded`，记录 `context_budget_infeasible`，不再静默回退到超大原始快照；
- 删除未接入生产链路的 `StaticKnowledgeStore` 以及声称存在 static/experience 后端的死映射。

Memory 边界：

- 当前实现只有每题独立的 `SessionMemory` 和 `LemmaMemory`；
- 不宣称存在跨题 Static/Experience 持久记忆；
- 每次 `solve()` 创建独立 memory，避免跨题污染；
- 若未来确需跨题经验记忆，必须作为新阶段实现来源、版本、权限、清理和评测闭环，不能只增加类定义。

关键验收：

- 任一生产角色 messages 总字符数不超过相应合同预算；
- Alternative 上下文中不存在 Primary 私有推导；
- Verifier 上下文中不存在 `solution_text`；
- Repair 上下文只包含局部 Claim 闭包；
- Blackboard 读权限按角色生效；
- 不可压缩上下文显式拒绝，不返回超预算内容。

R4 提交前验证：105 项测试通过。

## 4. R5：Deadline 与并发稳定性

已完成：

- 新增单题共享 `DeadlineController`，统一维护 soft、exploration、hard cutoff 和 deterministic finalize reserve；
- `CallBudget`、Router、fanout、模型调用守门器、Repair、Lemma expansion、Verifier 和 Finalizer 共享同一控制器；
- soft cutoff 后禁止启动额外候选、RAG、Lemma、Repair 和 LLM Finalizer；
- hard deadline 前预留确定性 fallback/formatting 窗口；
- `CandidateOrchestrator` 改为 deadline-aware `wait`，到期只收集已完成候选；
- fanout 不再使用会等待所有线程退出的上下文管理器；
- 官方客户端调用无法被 Python 强制取消时，底层调用被隔离到 daemon 调用线程；超时后主流程立即返回，但并发许可保持到真实调用结束，避免突破共享客户端并发上限；
- 截止后未完成分支不会再写入候选、token 或 session trace；
- fanout trace 记录每个失败分支及 `deadline_cutoff` 原因；
- 增加 100 ms hard deadline、慢客户端、8 题并发、P95 和返回后 trace 稳定性测试。

关键验收：

- 300 ms 慢客户端配合 100 ms hard deadline 时，`solve()` 在 200 ms 测试容差内返回非空 fallback；
- fanout 在截止点返回，不等待 300 ms 分支完成；
- 8 题共享慢客户端并发测试的 P95 小于 200 ms；
- 返回后等待慢客户端结束，已返回的候选集合、token 计数和各题 trace 均不变化；
- 8 个会话具有不同 session ID，没有跨题 session 写入。

需要明确的限制：

- Python 不能终止已经进入官方客户端内部的阻塞调用；当前方案保证 Harness 按时返回、保持并发上限并隔离会话写入，但底层网络调用可能在 daemon 线程中继续到客户端自行返回；
- 200 ms 是针对 100 ms hard deadline 的自动化测试容差，不是对真实官方服务网络 P95 的最终声明；
- 真实服务 P50/P95、重试行为和 15 分钟赛题窗口仍需在 R7 使用官方环境测量。

R5 提交前验证：110 项测试通过。

## 5. 当前赛题符合性判断

截至 R5，项目继续满足已知赛题工程约束：

- 未修改官方不可变文件 `main.py` 和 `llm_client.py`；
- 保持公开 `solve(problem, metadata)` 返回 `final_response` 与 `trace` 的接口；
- 使用注入的官方客户端，不绕过公开 chat 接口；
- 模型并发、调用次数、token 和时间窗口均有显式控制；
- 每条路径保证非空结果或确定性 fallback；
- `python scripts/verify_baseline_files.py` 通过；
- `python scripts/validate_submission.py` 通过。

当前可以称为：

> R0–R5 工程整改完成，Harness、多智能体生产链路、角色上下文隔离和运行时截止控制已形成可验证闭环。

当前仍不能称为：

> 最终竞赛配置已通过真实数据消融并冻结，或已证明达到官方服务下的最终准确率、成本和 P95 目标。

## 6. 后续实施边界

下一阶段仍应按原计划执行：

1. R6：修复 RAG 的 BM25/trust/condition 复合排序、连接释放和来源审核；继续验证 Direct/MCP 一致性；
2. R7：使用真实验证集执行 A0–A9 多次重复消融，报告置信区间、准确率、成本、fallback、P50/P95、lemma/repair/CEPC 指标；
3. 只有 R7 证据支持时，才把 `config/competition.json` 从 `candidate-unvalidated` 更新为冻结配置；
4. 若可选模块没有稳定正确率收益或显著增加成本，应删除或默认关闭，而不是保留为“展示性组件”。

## 7. 最终自动化验证

```text
python -m compileall mathforge tests
passed

pytest -q
110 passed

python scripts/verify_baseline_files.py
Official immutable baseline files verified.

python scripts/validate_submission.py
Submission validation passed.

git diff --check
passed
```
