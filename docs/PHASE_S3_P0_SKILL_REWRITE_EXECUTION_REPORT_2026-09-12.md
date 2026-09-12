# Phase S3 执行报告：高风险 P0 Skill 重写

日期：2026-09-12  
状态：实现完成，阶段校验通过，已提交

## 范围

按方案重写 13 个高风险 Skill：

- 收敛与极限：`dominated-convergence`、`uniform-convergence`、
  `lhopital-limit`、`epsilon-delta`、`taylor-remainder`；
- 复分析：`branch-cut-integral`、`argument-principle`、
  `rouche-zero-count`、`residue-theorem`；
- 线性代数：`jordan-form`、`spectral-theorem`、
  `eigenvalue-diagonalization`；
- 概率：`conditional-expectation`。

## 改造内容

每个包保持 Skill V3、固定角色和现有 Tool 名称，重写了：

1. `Recognition` 与 `Do Not Use When`：从关键词命中改为结构识别和反例
   边界，补充不应选择该方法的情况；
2. `Core Theorem` 与 `Exact Preconditions`：明确量词、定义域、可测性/可积
   性、分支、边界、字段、重数、可逆性等定理前提；
3. `Procedure`、`Branch Conditions`、`Failure Modes`、`Counterexample
   Patterns`：将常见形式正确但数学错误的跳步显式化；
4. `Verification Recipe`：逐项说明现有 hook 的最大证据范围。尤其明确：
   numerical residual 只能提供有限样本支持，matrix shape 不能证明矩阵恒等
   式/可逆性，density normalization 不能证明非负性或条件期望，symbolic
   equivalence 也不替代定理前提；
5. 补充 S1 的 `description`、`negative_triggers`、`required_observables`，
   使高风险方法在选择阶段可降权和触发前提核对。

## 结果

13 个 P0 包均通过 V3 Schema、内容质量门和运行时 hook policy：

- 全部具备非空描述、负触发条件和必需观测量；
- 完整保留 12 个标准章节；
- 0 个 capability/claim-state mapping error；
- 全目录的未声明验证边界 warning 从 S2 的 39 个降至 28 个，且不再包含
  13 个 P0 包的 `recipe_strength_undeclared`。

## 验证

新增 `tests/test_phase_s3_p0_skill_rewrite.py`，覆盖 P0 包清单、元数据、
定理前提和失败模式长度、弱 hook 支持性措辞以及全量审计结果。

阶段定向测试：`18 passed`（P0、S2 审计、E3 和现有 Skill 包回归）。  
完整仓库 `pytest -q`：`1057 passed, 2 failed`；失败项仍是既有内容审查
manifest 的 Skill 包内容哈希陈旧（本次 P0 重写使 `math-skill-v3-packages`
等条目需要重新进行正式内容审查），未通过手工修改 manifest 规避。  
`python -m compileall -q .` 与 `python scripts/verify_baseline_files.py` 均通过。  
本阶段不声称真实模型准确率提升；必须由 S5 的正例、负例、对抗例和
Skill ON/OFF 消融实验验证实际收益。

## 后续

保留剩余 28 个非 P0 包的边界 warning，下一阶段将引入外部来源的内容时按
同一 V3 模板、现有 Tool 能力和 provenance 要求改写，禁止直接复制外部
运行时指令或工具调用。
