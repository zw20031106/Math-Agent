# Phase S4 执行报告：外部 Skill MathForge 化改写

日期：2026-09-12
状态：实现完成，阶段校验通过，已提交

## 目标与范围

按 0907 方案的 Phase S4，将外部 GitHub Skill 作为知识来源审计后，重写
为当前项目可加载、可选择、可审计的 V3 `method` 包。新增 9 个包：

- `general/strategy-progress-assessment`：公共状态进展评估与下一步决策；
- `numerical_analysis/root-finding`：括区间、正则性、重根和残差边界下的
  标量求根方法选择；
- `logic/proof-strategy-selection`：按命题外层逻辑选择证明架构；
- `logic/mathematical-induction`：普通、强和结构归纳的前提与义务；
- `logic/contradiction-contrapositive`：反证与逆否命题的精确否定变换；
- `logic/existence-uniqueness`：存在性见证与任意见证对的唯一性分离；
- `logic/case-split-wlog`：穷尽互斥分情况与 WLOG 对称性证明；
- `logic/proof-theory`：规则、前提、证明依赖和元理论边界审计；
- `logic/lean-proof-workflow`：statement-first、top-down design、
  bottom-up proof 的形式化工作流。

## 外部来源审计

来源、解析到的提交、许可证状态和知识提取范围记录在
`mathforge/skills/packages/references/source_attribution.md`。本阶段固定了
以下提交，避免随分支漂移：

- `parcadei/Continuous-Claude-v3`：
  `d07ff4b06b62f43771bc0c927d0211b734d6149e`，MIT License；
- `Tibsfox/gsd-skill-creator`：
  `e179dfe911f3b3c2ff8bcd90ecd6ee4738648d17`，仓库 LICENSE 为 MariaDB
  派生许可证文本，发布前需保留条款并完成兼容性审查；
- `trailofbits/skills`：
  `321ccfe628eca0d314b0ee4eaffcdd8a05639aaf`，CC BY-SA 4.0。

改写采用“来源审计 → 数学知识提取 → V3 重写 → 能力审计”的流程。没有
直接复制外部 frontmatter、prompt 或运行时；外部的 Claude 专属交互、
`Bash`、`Read`、SciPy/Z3 命令和不存在于本项目的工具均未进入可执行 Skill。

## 数学与工具边界

每个包均保留 V3 12 个标准章节、固定五类角色、S1 元数据，并把
`exact preconditions`、`failure modes`、`counterexample patterns` 写成
可审阅的公共义务。验证配方只引用当前 `ToolRegistry`：

- 求根、进展评估、有限基例分别把残差、答案形状、有限枚举标成有界支持；
- 公式等价仅用于声明定义域/假设下的规范化，不替代定理证明；
- `lean-proof-workflow` 明确当前没有 Lean Host Capability，语法解析不能
  变成编译器或内核验收，正式状态只能为 `unsupported`/`incomplete`。

## 自动化验证

新增 `tests/test_phase_s4_external_skill_rewrite.py`，覆盖：

1. 9 个包的 V3 完整章节、元数据、前提/失败边界；
2. ToolRegistry 映射和 hook strength audit，无未知工具或未声明弱边界；
3. 根求解正触发、归纳负触发、Lean 对抗/不可用分支；
4. 来源提交、许可证和转换控制的 provenance 记录。

阶段定向测试：`4 passed`。当前目录加载结果为 `95` 个 Skill，其中 `60`
个 V3；S4 新包均无 hook audit error，既有目录保留 28 个历史弱配方 warning。

提交前验证结果：

- `python -m compileall -q .`：通过；
- `pytest -q`：`1061 passed, 2 failed`；失败仍为历史内容审查 manifest 的
  Skill 包哈希陈旧（P0/S3 重写后需正式重建 review manifest），没有通过手工
  修改 manifest 绕过；
- `python scripts/verify_baseline_files.py`：通过。

上述失败是既有发布治理工件的待办，不是 S4 Skill 加载或 hook 映射失败。
本阶段不声称真实模型准确率提升，S5 仍需对新增包执行正例、负例、对抗例、
选择和 Skill ON/OFF 的真实评估。

## 提交与后续

本阶段使用独立提交 `Phase S4: rewrite external Skills for MathForge`，不
与 S3 合并。下一阶段应在固定提交、配置和数据指纹下执行 Skill benchmark
与消融；在此之前不得把本地单测绿灯当作官方准确率或证明正确率证据。
