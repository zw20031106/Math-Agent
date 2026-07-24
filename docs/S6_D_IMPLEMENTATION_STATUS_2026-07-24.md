# S6-D / E3 实施状态：Parser、AnswerType 与 Scoring

日期：2026-07-24

对应计划：阶段 E3

提交目标：`S6-D: fix problem target parsing and benchmark scoring`

## 结论

E3 已修复上一次 88 题测试中复现的 19 个输出类型误判，并把原始
`idx/problem/answer/subject/source` 数据规范化为带明确评分事实的
`data/dev_set_2_gold.jsonl`。

确定性预检结果：

```text
case_count              88
expected_count          88
auto_scored_count       88
manual_count             0
invalid_expected_count   0
auto_score_coverage      1.0
parser_type_agreement   88/88
```

对用户原始 `dev_set_2.jsonl` 直接使用 `answer` 兼容字段执行同一预检，也得到
88/88 expected、0 invalid expected 和 100% auto-score coverage。

## 1. Requested-target-first Parser

Parser 不再扫描整个题面并把任意名词当成输出类型。新顺序是：

1. 提取最后一个完整请求句；
2. 从最后一个“求/计算/确定/写出/给出/判断”请求动词开始提取
   `target_phrase`；
3. 先识别目标对象，再决定 `answer_type`；
4. 无法高置信识别时回落为宽容的 `expression`；
5. 输出 `parser_confidence`，取目标提取置信度与类型识别置信度的较小值。

`ProblemIR` Schema 升级为 1.3；序列化、反序列化和校验现在包含：

- `target_phrase: str`；
- `parser_confidence: float`，范围 `[0,1]`。

`problem_parsed` Trace 2.0 事件同步记录两个字段。

### 19 个已复现反例

回归 ID 为：

```text
10, 11, 12, 13, 15, 17, 49, 60, 63, 64,
68, 69, 74, 75, 76, 81, 83, 86, 87
```

覆盖：

- 矩阵是输入对象、输出是标量/多项式/向量/整数/tuple；
- 区间只是条件、输出是误差/期望等标量；
- “解释变量”是回归术语，不是 explanation 请求；
- “整数同调群”要求 algebraic structure，不是 integer；
- “谱半径”是标量，“谱”是集合。

88 题的 `problem_type` 与 `answer_type` 均与金标一致。

## 2. AnswerType 与输出形状

保留原类型并新增：

- `vector`；
- `tuple`；
- `polynomial`；
- `algebraic_structure`。

标量仍使用 `expression`，避免对概率、含常数表达式和一般计算结果施加过早
的整数/分数限制。Router 会为 `expression/polynomial` 选择符号等价工具；
AnswerValidator 与 Host 的 answer-type 工具增加 vector、tuple、interval、
set 和 matrix 的安全形状检查。

## 3. Scorer

评分器新增：

- vector：逐坐标安全符号等价；
- tuple：逐项安全符号等价；
- polynomial：受限符号等价；
- algebraic structure：规范化后的结构表达匹配。

受限数学规范化新增：

- `\frac` 与简写 `\frac7{16}`；
- 平方根与 n 次根；
- `\pi`、Euler 常数、虚数单位；
- `\ln`、`zeta`；
- 常见 LaTeX 幂与隐式乘法；
- 向量转置后缀；
- `\mathbb` 与 `\oplus` 结构记号。

所有表达式仍进入受限 AST 解析器，不使用 `eval`，不允许属性访问、任意
函数或代码执行。

无效 actual answer 现在区分：

- `invalid_actual_syntax`；
- `invalid_actual_unsafe_expression`；
- `invalid_actual_value:<type>`；
- `invalid_actual_vector/tuple/set/interval/matrix/...`；
- 各类型的 shape/length/equivalence mismatch。

无效 expected answer 仍标记为评测事实错误，不计为模型数学错误。

## 4. Loader 与 Preflight

JSONL Loader 规则：

1. 优先读取 `expected_answer`；
2. 缺失时兼容 `answer`；
3. 两者同时存在且规范化文本不同，立即失败；
4. 显式 `answer_type/scorer` 优先于 Parser 推断。

`preflight_benchmark_cases()` 在任何在线调用前检查：

- Case ID 不重复；
- expected answer 完整；
- expected answer 能被声明的 scorer 解析；
- 自动评分覆盖率不低于 95%；
- manual/rubric 项显式计数。

`run_benchmark.py` 和 `run_case_outputs.py` 都在创建在线 Case 任务前执行
预检。Benchmark artifact schema 升级到 3.4，并保存结构化 preflight。
Summary 增加：

- `manual_count`；
- `invalid_expected_count`；
- `auto_score_coverage`；
- `score_reason_counts`。

## 5. 金标与测试

`data/dev_set_2_gold.jsonl` 为 88 题逐题保存：

- `expected_answer`；
- `problem_type`；
- `answer_type`；
- `scorer`；
- 原 subject/source。

`tests/test_s6_e3_parser_scoring.py` 覆盖：

- 88/88 金标字段和 Parser 一致；
- 19 个历史反例；
- `answer` 兼容与冲突拒绝；
- 88 题 expected/scored summary；
- LaTeX、向量、tuple 与代数结构等价；
- invalid actual 细分；
- Trace target/confidence。

本阶段没有再次调用真实 397B；计划明确要求 E0–E4 完成前不执行昂贵的
88 题全量在线测试。
