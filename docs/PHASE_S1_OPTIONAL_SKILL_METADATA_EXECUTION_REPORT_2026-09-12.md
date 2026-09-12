# Phase S1 执行报告：V3 Skill 可选元数据

日期：2026-09-12  
状态：实现完成，已提交  
范围：`schema.py`、`loader.py`、`selector.py` 及对应不变量测试

## 目标

在不改变 Skill 版本 3.0、既有必填字段和 Host/Compiler/Candidate 协议的
前提下，为 Skill 提供三类可选的检索与选择上下文：

| 字段 | 作用 | 约束 |
| --- | --- | --- |
| `description` | 一行说明适用的问题/用途 | 仅用于上下文与可解释排序，不替代数学前提 |
| `negative_triggers` | 表面命中但不应优先选择的情形 | 仅有界扣分，第一版不作为硬 veto |
| `required_observables` | 值得先寻找的题目/状态观测量 | 与 `exact preconditions` 分离，命中加分、缺失降权 |

## 实现内容

1. `SkillPackage` 增加三个默认空值字段，并在初始化时规范化空白、去重和
   空项目；旧 V3 包和 V2 适配包无需增加 frontmatter 即可加载。
2. Loader 保持原 frontmatter 必填字段检查，同时支持简单 YAML 子集：
   inline 列表、缩进块列表以及 `>`/`|` 描述；缺失可选字段稳定解析为空值。
3. `DynamicSkillSelector` 将元数据接入现有确定性评分：
   - 描述完全匹配时增加低权重可解释信号；
   - 每个命中的负向触发条件最多累计有界惩罚；
   - 已出现的观测量增加有限分值，缺失观测量降低有限分值；
   - 负向触发不会直接阻断带有路由/主题证据的 Skill。
4. `SkillFragmentDecision.to_trace_dict()` 输出元数据，使选择原因可以与
   包内容指纹一起审查；旧包字段为空且不改变已有 trace 结构语义。

## 验证

新增 `tests/test_phase_s1_optional_skill_metadata.py`，覆盖：

- inline 与缩进块 frontmatter 的三字段解析；
- 未声明元数据的真实 V3 包向后兼容；
- 负向触发、观测量命中/缺失和描述匹配的选择评分；
- “元数据降权而非直接 veto”的不变量。

阶段定向测试：`15 passed`。  
仓库校验：`python -m compileall .` 通过；`python scripts/verify_baseline_files.py`
通过（官方冻结文件未被修改）。完整 `pytest -q` 为 `1049 passed, 2 failed`；
两项失败均为既有 `docs/content_review_manifest.json` 内容哈希陈旧
（`math-skill-v3-runtime` 等），不是 S1 行为失败，未通过手工修改 manifest
规避。

## 边界与后续

本阶段不把 `required_observables` 当作定理成立条件，也不把
`negative_triggers` 当作不可恢复的路由拒绝。S2 将审计 `requires`、
`verification_hooks` 与 Tool Capability/证据强度的对应关系，避免弱工具被
误读为普遍数学证明。

