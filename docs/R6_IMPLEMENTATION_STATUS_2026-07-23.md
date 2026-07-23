# Math-Agent R6 实施状态报告

日期：2026-07-23  
审查基线：`docs/DEEP_IMPLEMENTATION_AUDIT_2026-07-22.md`

## 1. 结论

R6 的 RAG 与可选 MCP 组件整改已经完成工程实现和自动化验收：

- BM25 分数不再在 Python 重排时丢失；
- trust、condition 和 BM25 使用显式、稳定的复合排序；
- SQLite 读写连接均显式关闭；
- 知识卡具备来源版本、审核者、审核日期和内容哈希；
- 建立了知识卡人工审核与发布门禁；
- MCP Schema 具有明确 JSON 类型，Direct/MCP 结果保持一致；
- MCP 在运行时和竞赛配置中继续默认关闭。

R6 完成不等于 RAG 或 MCP 已被证明能提高竞赛成绩。是否在最终配置保留这些可选组件，仍由 R7 的真实重复消融决定。

## 2. RAG 排序

新增 `SearchHit`，保留：

- `bm25_score`；
- 显式 `trust_priority`；
- `condition_score`；
- 完整 `KnowledgeCard`。

最终顺序固定为：

1. subject/type/trust 可见性过滤；
2. trust：`verified` 优先于 `reviewed`，`conflicted` 仅 VerifierSkeptic 可见；
3. precondition 与查询的重合度降序；
4. BM25 分数升序；
5. card ID 仅作为稳定并列项；
6. 按 statement 去重后截取 top-k。

运行时通过 `Retriever.search()` 获取 SearchHit，并在 trace 中记录 card ID、trust、condition score、BM25 和 source version。发送给 Solver 的卡片同时标注 `source_ref @ source_version`。

关键反例已经覆盖：查询 `equation exactterm` 时，ID 靠后的高可信精确卡优先于 ID 靠前的弱匹配卡；同 trust 和 condition 下，BM25 更精确的卡优先。

## 3. SQLite 生命周期

`builder.py` 和 `retriever.py` 均使用 `contextlib.closing`：

- 构建完成后立即关闭写连接；
- 检索完成或异常后立即关闭只读连接；
- 构建前先验证所有卡片，避免无效卡先删除已有数据库。

Windows 验收测试在 `retrieve()` 返回后立即重命名并删除数据库文件，操作成功。

## 4. 来源与人工审核

`KnowledgeCard` 新增：

- `source_version`；
- `reviewer`；
- `review_date`；
- `content_hash`。

构建器强制校验 trust 值、来源版本、ISO 审核日期和 SHA-256 内容哈希。正文、条件、排除项、常见错误或来源版本改变后，旧哈希失效，数据库构建会拒绝该卡。

当前 8 张卡来自项目内部 Skills，全部维持 `reviewed`，不升级为 `verified`。详细审核规则和库存见 `docs/KNOWLEDGE_CARD_REVIEW_CHECKLIST.md`。

## 5. MCP 决策

已完成：

- 9 个已注册工具均有显式 JSON Schema 参数类型；
- 9 个工具逐一执行 Direct 与 StdIO MCP 比较，完整 `ToolResult` 一致；
- MCP 失败仍回退到 Direct；
- `HarnessConfig.use_mcp` 默认是 `False`；
- `config/competition.json` 的 `use_mcp` 保持 `false`。

未实施常驻 MCP 进程。原因是当前没有真实消融证据证明 MCP 相比 Direct 有准确率或成本收益，而 R6 计划明确要求默认关闭、由后续消融决定是否保留。当前 StdIO 实现只作为协议兼容候选，不进入默认竞赛路径。

## 6. 当前边界

仍未完成：

1. 权威外部教材、论文或正式标准来源卡；当前卡仅为内部 reviewed；
2. RAG/MCP 对真实准确率、成本和 P95 的贡献；
3. A0–A9 多次重复消融与置信区间；
4. 最终榜单配置冻结。

因此 `config/competition.json` 必须继续保持 `candidate-unvalidated`。下一阶段是 R7，而不是继续扩充未经评估的知识卡或工具数量。

## 7. 自动化验收

R6 增加了以下测试：

- 复合 trust/condition/BM25 排序；
- SearchHit 分数保留；
- Windows SQLite 文件立即移动/删除；
- stale content hash 构建拒绝；
- 生产知识卡来源版本和审核记录；
- 全工具 Direct/MCP 等价；
- MCP Schema 类型完整；
- MCP 默认关闭。

最终门禁命令：

```text
python -m compileall mathforge tests
pytest -q
python scripts/verify_baseline_files.py
python scripts/validate_submission.py
git diff --check
```

最终结果：

```text
python scripts/build_rag.py
Built data/math_knowledge.sqlite with 8 reviewed cards.

pytest -q
124 passed

python scripts/verify_baseline_files.py
Official immutable baseline files verified.

python scripts/validate_submission.py
Submission validation passed.

git diff --check
passed
```
