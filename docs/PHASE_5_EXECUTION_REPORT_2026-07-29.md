# Phase 5 执行报告

日期：2026-07-29

## 执行范围

本阶段覆盖融合实施方案 Phase 5：确定性 Shadow Solver、题内 L0/L1 memo、只读 Frozen Lemma Store、Host 参数所有权、Context 响应恢复复核、分层时间边界、900 秒 Competition 候选配置、约 20K Final Response 与增量 Internal Trace。

## 已完成内容

### 1. Deterministic Shadow

- 新增独立来源 `deterministic_shadow` 和角色 `DeterministicShadow`，不会伪装成 LLM Candidate。
- 新增 allowlist capability registry，首批支持：
  - 受限代数表达式；
  - 单方程、多项式方程与简单方程组；
  - 矩阵行列式、秩和特征值；
  - 可由受限 SymPy 表达式安全处理的极限；
  - 定积分与不定积分；
  - 有限和与基础收敛级数。
- Runtime 在 Primary 之前执行 Shadow，但只保存在当前 `solve()` 的局部变量中；Primary/Alternative 的 Context、Prompt 和 Blackboard 均不包含 Shadow 答案。
- Shadow 通过隔离 Host 工具子进程运行，单次硬超时不超过 5 秒；不支持的题型返回 `unsupported`，不会形成 Candidate。
- Primary 返回后才公开 Shadow trace、生成 ShadowCandidate 和 Evidence。
- Shadow exact 可进入正常 Admission、Evidence、Proof 与 Arbitration；模型分支全部失败时仍可输出具体答案，并在 trace 中标记 `degraded_shadow_only`。
- Shadow 与 Primary 冲突时进入显式冲突矩阵并触发预算允许的 Alternative，不会静默覆盖。

### 2. L0/L1 与 Frozen L2

- 新增每题独立的 `ProblemMemo`：
  - L0：当前题 Shadow 纯函数结果；
  - L1：当前题 Frozen Lemma 检索结果。
- memo 在每次 `solve()` 内创建，终态前清空，不跨题共享。
- 新增 `FrozenLemma` 严格 Schema、记录级 content hash、验证 artifact hash、审核状态和 Store manifest hash。
- Runtime Store 只暴露读取和检索，不提供 `add`、`write` 或运行期 freeze 接口。
- 每个命中重新检查当前题 assumptions/preconditions；缺少条件时拒绝命中。
- Frozen 内容仅作为带来源的 Context，不直接把 proof obligation 标为 complete。
- Competition Store 当前为空库，避免把未经真实验证和人工数学审核的引理带入正式路径。
- 新增离线 `staging → human_approved → freeze` 构建脚本；未审核记录、重复 ID、hash 篡改和 case-specific 字段均被拒绝。

### 3. Host 所有权与 Context 恢复

- Shadow 工具参数由 Host 从 `ProblemIR` 重建，模型无法提供可执行 Shadow 参数。
- 通用 Candidate 工具参数继续由 `ClaimToolRequestBuilder` 从受控 Candidate/Claim/ProblemIR 重建；模型的自由文本建议不能直接执行。
- 复核既有 Context 边界：已经完整接收、超过角色软输出上限但仍位于 256K 总上下文内的响应会被保留；只有真正越过上下文边界才进入安全恢复/终态。

### 4. 时间与输出边界

Competition 候选配置已调整为：

```text
outer per-case limit        900 s
Harness hard deadline       850 s
soft deadline               600 s
exploration deadline        720 s
deterministic final reserve  50 s
model call start margin     100 s
local tool total budget      30 s
shadow isolated probe       <=5 s
```

- 外层与 Harness hard deadline 之间保留 50 秒用于确定性终态、序列化和原子落盘。
- Final Response 上限保持 20,000 字符。
- Competition Internal Trace 的 `trace_max_chars` 和 `trace_max_events` 均为 0；本地增量 Journal 继续逐事件写入。
- Judge Trace 仍保留独立公共输出治理边界，避免单题 JSON 失控。

## 关键文件

- `mathforge/tools/shadow_solver.py`
- `mathforge/tools/registry.py`
- `mathforge/memory/problem_memo.py`
- `mathforge/memory/frozen_lemma_store.py`
- `scripts/build_frozen_lemma_store.py`
- `data/frozen_lemmas.jsonl`
- `data/frozen_lemmas_manifest.json`
- `mathforge/runtime.py`
- `mathforge/config.py`
- `config/competition.json`
- `tests/test_phase5_0729_shadow_cache_deadline.py`

## 验收证据

定向覆盖包括：

- 首批 8 类 Shadow 计算；
- unsupported 不产生候选；
- 模型完全离线时 exact Shadow 输出具体答案；
- Primary Prompt 无 Shadow 答案、Candidate ID 或 trace 事件泄漏；
- Shadow 冲突触发 Alternative 并进入冲突矩阵；
- 并发 4 下答案与 nonce 不跨题；
- Frozen Store 只读、hash 校验、人工审核门禁和假设重验；
- Competition 900/850/600/720/50 秒边界；
- Final Response 20K 与 Internal Trace 无低字符上限。

最终全量回归：

```text
542 passed, 3 xfailed
```

3 个 `xfail` 均为计划中明确归属 Phase 6 的 Windows 路径脱敏和历史
Trace Journal 恢复问题。

## 未越权声明

- 本阶段未调用真实在线模型，也未使用或读取 API Key。
- 未执行正式数据集正确率、P50/P95 或缓存开关 A/B，因此不能宣称 Frozen Cache 已在真实样本上降低平均调用且正确率不降。
- `competition.json` 继续保持 `candidate-unvalidated`；真实画像、调用下降和正确率门禁应在后续正式验证阶段完成。
- 未修改 `main.py`、`llm_client.py`。
- 工作区包含进入本阶段前已有的未提交改动，因此没有把混合状态伪装为 Phase 5 独立提交。

## 结论

Phase 5 的工程实现与离线不变量验收已完成。真实模型画像、Cache A/B 和配置冻结仍属于后续验证阶段。
