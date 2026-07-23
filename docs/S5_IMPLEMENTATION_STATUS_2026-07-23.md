# S5 RAG、内容与依赖治理实施状态

日期：2026-07-23

范围：C24–C26

状态：工程实现与自动化验收完成；人工双签和 S6 真实消融待执行

## 1. 验收结论

| 缺陷 | 实施结果 | 自动化验收 |
|---|---|---|
| C24 中文题无法可靠命中英文卡 | 增加受控中英术语归一化，覆盖当前 8 个生产领域 | 8 条双语检索基准全部命中预期卡，超过 87.5% 门槛 |
| C24 构建失败破坏旧 DB | 在同目录临时库完整写入，执行 integrity 和 cards/FTS 行数校验后 `os.replace` | 重复主键注入使构建失败时，旧库 SHA-256 不变且无临时文件残留 |
| C24 失败静默 | 版本化返回 `matched/no_match/missing_db/fts_unavailable/query_error`，Runtime Trace 记录状态 | 缺库、空库、无命中和 Runtime 传播测试通过 |
| C24 `verified` 缺双人门槛 | RAG Schema 升级至 1.1；`verified` 卡必须有两个不同审核者 | 单人或重复审核者在替换 DB 前被 builder 拒绝；现有 8 卡保持 `reviewed` |
| C25 运行不可完整复现 | 新增 RunProvenance 1.0，记录代码、公开模型标识、配置、Prompt、Skill、RAG、Tool、内容审核和组件决策 | 每次 solve 与 benchmark artifact 均包含完整指纹，嵌套非法值和篡改均被拒绝 |
| C25 内容缺统一审核门 | 新增内容审核 manifest，覆盖 18+6 Skills、7 Prompts、Obligation、Capability、Router、黄金 E2E 和 RAG 内容 | 工程 reviewer/date/version/hash 校验通过；`--require-human` 按设计阻止冻结 |
| C25 依赖不可离线复现 | 新增 CPython 3.13 精确 lock 和 clean-venv/no-index 安装脚本 | 临时 wheelhouse、全新虚拟环境、离线安装和公开入口 smoke test 已通过 |
| C26 MCP 生命周期未决 | 固化 Direct 默认、StdIO MCP 关闭、HTTP 禁止、不引入常驻进程 | 配置和机器可读决策测试通过；Direct/MCP 既有等价与回退测试继续通过 |

## 2. RAG 1.1

数据库构建顺序为：

```text
validate cards
  -> build same-directory temporary SQLite/FTS5 database
  -> PRAGMA integrity_check
  -> validate cards and FTS row counts
  -> atomic os.replace
```

任一步失败都会保留原数据库。检索兼容旧的 `search()`/`retrieve()` 列表接口，
同时通过 `search_with_status()` 给 Runtime 提供结构化状态。中文归一化仅使用仓库内
受控术语映射，不访问网络，也不做不受控翻译。

现有 8 张卡全部来自内部 Skill，信任等级仍为 `reviewed`。`verified` 不再只是一个
可自由填写的字符串：builder 要求两个去重后的 `verification_reviewers`。该门槛
只证明双签记录存在，审核者的领域资质仍需项目负责人线下确认。

## 3. 运行与 Benchmark 溯源

RunProvenance 1.0 至少包含：

```text
code_commit
public model_identifier
config schema/profile/status/hash
7 prompt names/versions/hashes
24 skill names/versions/hashes
RAG schema/database hash
9 tool names/versions/capabilities/limitation hashes
content review manifest status/hash
component decision manifest status/hash
```

Benchmark schema 升级至 3.1。artifact 增加全对象语义 SHA-256，并可用
`scripts/verify_benchmark_artifact.py` 独立检查。A0–A10 文件均以
`config/competition.json` 为基底加载为严格、完整的实验配置；本阶段只验证配置
可运行，不生成或虚构消融收益。

## 4. 内容审核边界

`docs/content_review_manifest.json` 已完成工程级目录、数量、版本、日期和哈希
校验。其状态有意保持：

```text
status = pending-human
human_signatures = []
```

因此：

- `python scripts/verify_content_reviews.py` 应通过工程完整性检查；
- `python scripts/verify_content_reviews.py --require-human` 必须失败；
- `validate_submission.py` 必须输出人工签署尚未完成的警告；
- 任何人不得据此声称已经完成数学专家审核。

需要线下签署的范围包括 18 个领域 Skill、6 个通用 Skill、7 个 Prompt
Contract、Proof Obligation 模板、Tool capability/limitation、Router 校准集和
低/中/高风险黄金 E2E。

## 5. 可选组件决策

`config/component_decisions.json` 和 ADR-002 固化以下 S6 前默认：

| 组件 | 默认 | 当前处理 |
|---|---:|---|
| RAG | 关闭 | 保留实现，等待 A8 稳定净收益 |
| MCP | 关闭 | Direct 默认；仅保留一次性本地 StdIO；无 HTTP/常驻 |
| Finalizer | 关闭 | 确定性 Formatter 默认，等待 A10 语义与收益门 |

这些是证据不足时的安全默认，不是组件效果优劣的最终结论。

## 6. 依赖与离线安装

`requirements-lock.txt` 精确固定正式和开发依赖。已执行：

```text
python scripts/verify_offline_install.py --prepare-wheelhouse
```

脚本先准备临时 wheelhouse，随后在全新虚拟环境中仅使用 `--no-index` 安装，并从
源码工作区调用 `ReasoningAgent`，检查非空响应、成本指标和 provenance。临时目录
在成功后自动清理。

## 7. 自动化结果

- 全量 pytest：252 passed；
- Ruff：通过；
- Mypy：85 个源文件通过；
- 全局分支覆盖率：81.32%，达到 80% 门槛；
- Runtime/Completion/Evidence/Config/Formatter 五个关键模块门槛通过；
- 内容审核 manifest：工程校验通过，人工冻结门按设计失败；
- baseline：官方冻结文件完整；
- submission：通过并保留 `candidate-unvalidated`、`pending-human` 两项警告；
- `pip check`：无损坏依赖；
- 离线 clean-venv 安装与公开入口 smoke test：通过。

## 8. 剩余边界

S5 没有执行、也没有伪造以下外部工作：

1. 数学领域专家的人工作者双签和资质确认；
2. 代表性隐藏验证集上的真实 A0–A10 多次重复实验；
3. 使用官方公开模型标识的配对置信区间、显著性、P50/P95 和成本报告；
4. 根据真实证据冻结 `config/competition.json`。

上述工作属于 S6。当前 competition 状态继续为 `candidate-unvalidated`。
