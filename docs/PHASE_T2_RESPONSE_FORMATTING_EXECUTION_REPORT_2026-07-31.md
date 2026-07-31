# Phase T2 题型感知输出格式执行报告

日期：2026-07-31  
阶段：T2——`final_response` 题型分流与 LaTeX 规范

## 1. 阶段结论

Phase T2 已完成。Host Formatter 现在直接消费 T1 的 `response_mode`，不再把
所有题目统一输出成“正文 + Final answer”。

## 2. 输出契约

### `answer_only`

仅输出一个最终答案行，例如：

```text
Final answer: $-\frac14$
Final answer: $\mathrm{B}$
Final answer: $\text{正确}$
```

候选中的 `solution_text` 不再进入此类题目的 `final_response`，但会在 T3/T4
进入公开 Trace。

### `worked_solution`

保留题目明确要求的公开推导，并附加唯一的 LaTeX 最终答案块。

### `proof_full`

保留候选的完整公开证明正文，并附加唯一的规范答案块；不会因为它属于文本型
答案而删除证明。

## 3. LaTeX 规则

- 数值、分数、表达式、集合、区间、矩阵等使用 `$...$`；
- 选择项使用 `$\mathrm{...}$`；
- 判断和纯文本答案使用 `$\text{...}$`；
- 已带 `$...$`、`\(...\)` 或 `\[...\]` 的答案不会被重复包裹；
- runtime 的最终规范化和长度边界使用同一个 response mode，不能重新引入已被
  `answer_only` 删除的正文。

## 4. 回归覆盖

新增或调整测试覆盖：

- 选择、填空、判断、计算的一行 LaTeX 答案；
- 显式过程题保留公开推导；
- 证明题保留完整证明；
- Finalizer 保持规范答案；
- public interface 和并发会话的直接答案契约；
- 原有答案行去重和答案长度保护。

提交前执行：

```text
python -m compileall .
pytest -q
python scripts/verify_baseline_files.py
```
