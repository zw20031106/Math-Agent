# MathForge 知识卡人工审核清单

版本：1.1
生效日期：2026-07-23

## 1. 强制元数据

每张进入离线知识库的卡必须包含：

- 唯一 `id`、`subject`、`type`；
- `title` 和单一、可核验的 `statement`；
- 完整的 `preconditions`、`exclusions` 和 `common_failures`；
- `source_type`、可定位的 `source_ref` 和不可变 `source_version`；
- 审核者角色或姓名 `reviewer`、ISO 日期 `review_date`；
- 仅当等级为 `verified` 时，至少两个不同的 `verification_reviewers`；
- `trust_level`；
- 对正文、适用范围和来源版本计算的 SHA-256 `content_hash`。

缺少来源版本、审核记录或内容哈希的卡不得构建到生产数据库。内容发生变化但哈希未更新时，`scripts/build_rag.py` 必须失败。

## 2. 数学审核步骤

审核者需要逐项确认：

1. statement 在给定 preconditions 下成立，没有省略定义域、非退化性或存在性条件；
2. exclusions 覆盖已知不适用情形；
3. common failures 包含该方法最常见的错误使用方式；
4. 卡片不会把数值样例、启发式或图形直觉表述为一般性证明；
5. source_ref 可在离线仓库或权威出版物中定位，source_version 可复现；
6. 与现有卡片不存在语义重复或冲突；
7. 若存在冲突，必须标记为 `conflicted`，不得给 Solver 使用；
8. 修改后重新计算 content hash，并由审核者重新签署日期。

## 3. Trust 等级

| 等级 | 使用范围 | 最低证据 |
|---|---|---|
| `draft` | 不进入生产检索 | 尚未完成审核 |
| `reviewed` | Primary/Alternative 可见 | 项目维护者完成数学与适用条件审核 |
| `verified` | Primary/Alternative 可见且优先 | reviewed 基础上，再由权威教材、论文或正式标准交叉核验 |
| `conflicted` | 仅 VerifierSkeptic 可见 | 已知存在冲突或适用范围尚未解决 |

内部 Skill 只能达到 `reviewed`。若要升级为 `verified`，source_ref 必须改为
可核验的权威 URL、DOI、书目信息或带版本的正式资料，并由两个不同的领域审核者
签署。builder 会强制双人记录，但审核者资质仍需项目负责人确认。

## 4. 当前库存

当前 8 张生产卡均来自仓库内领域 Skill：

| 卡片 | 来源 | 来源版本 | 审核者 | 审核日期 | Trust |
|---|---|---|---|---|---|
| `skill-algebra-equivalence` | `skills/domains/algebra.md` | `mathforge-skill-contract-v1` | `project-maintainer` | 2026-07-23 | reviewed |
| `skill-geometry-nondegeneracy` | `skills/domains/geometry.md` | `mathforge-skill-contract-v1` | `project-maintainer` | 2026-07-23 | reviewed |
| `skill-number-theory-integrality` | `skills/domains/number-theory.md` | `mathforge-skill-contract-v1` | `project-maintainer` | 2026-07-23 | reviewed |
| `skill-combinatorics-disjointness` | `skills/domains/combinatorics.md` | `mathforge-skill-contract-v1` | `project-maintainer` | 2026-07-23 | reviewed |
| `skill-probability-normalization` | `skills/domains/probability.md` | `mathforge-skill-contract-v1` | `project-maintainer` | 2026-07-23 | reviewed |
| `skill-calculus-interchange` | `skills/domains/calculus.md` | `mathforge-skill-contract-v1` | `project-maintainer` | 2026-07-23 | reviewed |
| `skill-linear-algebra-dimensions` | `skills/domains/linear-algebra.md` | `mathforge-skill-contract-v1` | `project-maintainer` | 2026-07-23 | reviewed |
| `skill-differential-equations-substitution` | `skills/domains/differential-equations.md` | `mathforge-skill-contract-v1` | `project-maintainer` | 2026-07-23 | reviewed |

这些卡是内部审核的过程性建议，不是独立数学证明证据。Verifier、ProofCompletionGate 和 hard evidence 不能用 RAG 命中代替。

## 5. 发布门禁

```text
python scripts/build_rag.py
pytest -q tests/test_retrieval.py
python scripts/verify_content_reviews.py
```

发布前还必须确认：

- 数据库构建成功且卡片数量符合预期；
- 构建失败时旧数据库哈希保持不变，临时数据库无残留；
- 中英检索基准至少达到 87.5% 预期卡 Recall@3；
- 精确高可信卡优先于 ID 靠前的弱匹配卡；
- 检索后 SQLite 文件可立即移动和删除；
- `data/knowledge_cards.json` 与 `data/math_knowledge.sqlite` 同时提交；
- S6 A8 重复消融没有稳定收益时，竞赛配置中的 RAG 应保持关闭。
