# Math-Agent S1 实施状态报告

日期：2026-07-23

范围：C05、C08、C09、C10

基线提交：`c94c991`

## 1. 结论

S1 的 Contract-first、Runtime 状态机与配置冻结前置工作已经完成工程实现。
这里的“完成”表示代码契约和自动化门禁闭环，不表示
`config/competition.json` 已经由真实重复消融冻结；其状态继续保持
`candidate-unvalidated`。

## 2. C05/C10：配置成为运行契约

- `ReasoningAgent` 与 `MathForgeHarness` 默认加载仓库内唯一的
  `config/competition.json`；
- benchmark 通过同一 `HarnessConfig.from_json()` 解析配置；
- 配置 Schema 版本为 `1.0`，语义哈希由规范化后的完整配置计算；
- 未知键、字符串布尔值、错误数值类型、越界值和非法 Feature 依赖在构造
  Harness 前失败；
- 新增完整展开的 `safe`、`balanced`、`competition` 三套配置；
- 测试仍可直接注入已校验的 `HarnessConfig`，公开入口不接受外部配置路径；
- 提交校验在配置仍为 `candidate-unvalidated` 时输出明确警告。

已实现的依赖规则：

```text
verifier -> evidence + proof_obligations
repair -> evidence + tools
lemma_loop -> memory + proof_obligations
rag -> skills
use_mcp -> tools
```

Deterministic formatter 与 post validator 是 Runtime 的固定组件，不是可关闭
Feature，因此启用 finalizer 时天然满足对应依赖。

## 3. C08：版本化 Schema 与宿主所有权

- ProblemIR、RoutePlan、Claim、CandidateSolution 和运行期记录携带 Schema
  版本；
- ProblemIR、RoutePlan、Claim、CandidateSolution 提供统一
  `validate()`，跨字典边界使用严格 `from_dict()`；
- 模型无法覆盖 `candidate_id`、`role`、`answer_type`、
  `planned_method_family` 和 `version`；
- 被覆盖的宿主字段、未知字段和局部类型降级均写入
  `contract_deviations`；
- 字符串不再被当成字符串列表逐字符展开；
- Claim 数量、单项长度、总长度、ID、悬空依赖和依赖环均受约束；
- Problem parser、Router、Solver parser 和 Repair 合并后均执行 Schema
  校验。

## 4. C09：显式 Runtime 状态机

成功路径固定为：

```text
CREATED -> PARSED -> ROUTED -> CONTEXT_READY -> CANDIDATES_READY
-> EVIDENCE_READY -> OBLIGATIONS_READY -> VERIFIED -> LEMMA_EXPANDED
-> REVERIFIED -> ARBITRATED -> FORMATTED -> FINALIZED -> COMPLETED
```

任何非失败终态都可进入：

```text
FAILED -> FALLBACK_COMPLETED
```

只有 `MathSession.transition(expected, target, reason=...)` 能改变 phase。
Feature 关闭时仍执行合法的显式 skip transition。公共 trace 仅记录
from/to phase 与原因；fallback 同时记录失败 phase，不记录私有推理。

## 5. Provenance

公开运行首条 trace 与 benchmark 元数据均记录：

- 配置 Schema、profile、status 与语义哈希；
- Prompt 内容树哈希；
- Skill 内容树哈希；
- RAG SQLite 数据库哈希；
- Tool Registry 语义哈希。

因此公开入口与离线 benchmark 可核对同一组运行输入。

## 6. 验收

- S1 契约、状态和配置反例测试：通过；
- 全量 pytest：192 项通过；
- `python -m compileall .`：通过；
- Ruff：通过；
- mypy：78 个源文件通过；
- 分支覆盖率测试：192 项通过，总覆盖率 80%；
- 官方冻结基线完整性校验：通过；
- 公开提交校验：通过，并明确输出未冻结警告；
- `pip check`：无损坏依赖；
- `git diff --check`：通过；
- competition 配置仍为 `candidate-unvalidated`，未越权标记 frozen。
