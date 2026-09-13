# Phase S7：MechMath 风格 Prompt/Skill 格式迁移执行报告

日期：2026-09-13  
范围：MathForge 全部 Prompt 合同、V2/V3 Skill 源文件、加载器、运行时 Skill 投影与回归测试

## 1. 目标与边界

本阶段把 MechMath Agent Team 公开资料中体现的“专职角色卡 + Dispatch/Input/Workflow +
工件交接 + 验证/修订边界”格式原则，迁移为 MathForge 自己可运行的协议。参考资料是
[MechMath Agent Team README](https://github.com/MechMath/MechMath-agent-team) 和
[MechMath Agent Team 开源说明](https://mechmath.github.io/blogs/mechmath-agent-team-open-source/)。

这里仅借鉴文档组织方式和生成—验证—修订的交接思想，没有复制 MechMath 的模型客户端、
工具、命令、运行时或字段。MathForge 的 `client.chat` 注入边界、TaskGraph 调度权、证据
门、候选 lineage、通信 ACK 规则、并发/限流配置和公开 JSON 合同保持不变。

## 2. 已完成的源文件改造

### 2.1 七个固定角色 Prompt

已改造以下文件：

```text
prompts/router_planner/contract.md
prompts/primary_solver/contract.md
prompts/alternative_solver/contract.md
prompts/lemma_curator/contract.md
prompts/verifier_skeptic/contract.md
prompts/repair/contract.md
prompts/finalizer/contract.md
```

每份合同新增 `format: mmat-role-card-v1`，并统一为以下可审计顺序：

1. `Dispatch Mode`：角色何时准入、是否可解题、与其他角色的边界；
2. `Input`：可见的 ProblemIR、公开状态、工件和禁止读取的私有/Host 字段；
3. `Workflow`：从前提门到 Claim/Step、证据和交接的实际动作；
4. `Communication and Artifacts`：允许发布什么公共语义，哪些 ID/版本/ACK 仍由 Host 管理；
5. `Verification Boundary`：Unknown、弱证据、定理前提、定义域和证明义务的处理；
6. `Failure and Escalation`：局部修复、全局方法失败、abstain 和重规划边界；
7. `Output Contract`：与各角色现有编译协议严格对齐的字段和中文/LaTeX/JSON 要求。

保留了原有协议所需的 RouterIntentV1、Candidate/Progress、Lemma、Finding、Repair 和
Finalizer 约束；没有让 Prompt 生成工作流 ID、候选 ID、预算、工具结果或伪造 ACK。

### 2.2 全部 Skill 方法卡

已覆盖：

- `skills/domains/*.md`：35 个 legacy V2 Skill；
- `skills/general/*.md`：包含在上述 35 个 V2 Skill 集合中；
- `mathforge/skills/packages/**/SKILL.md`：60 个 V3 Skill。

每个 Skill frontmatter 增加 `format: mmat-method-card-v1`，正文在原有数学章节前增加：

```text
Quick Dispatch
Input Contract
Workflow
Shared Artifacts
Verification Boundary
Failure Routing
Output Contract
```

原有 V2 的方法决策树、定理前提、常见错误、反例检查、兼容检查类型、答案规范化和 trace
指导，以及 V3 的 Recognition、Exact Preconditions、Procedure、Branch Conditions、
Failure Modes、Counterexample Patterns、Verification Recipe、Alternative Strategy 和
Stop/Escalate 条件全部保留。因此这不是把数学 Skill 压缩成关键词，而是在数学内容外补齐
可执行的角色/工件生命周期。

### 2.3 加载、注册和运行时投影

新增 `mathforge/skills/mechmath_format.py`，提供统一 `render_method_card()` 和格式常量。
`SkillPackage`、V2 适配器、Skill manifest 和选择 trace 现在携带
`format_version=mmat-method-card-v1`。

生产 `DynamicSkillSelector` 的输出顺序改为：

```text
Router 选中的 Skill（路由契约）
    → 通用 method-card 生命周期段
    → 当前角色允许的数学章节
    → 已准入的参考片段
```

在 6000 字符的 Skill 投影上，legacy V2 的数学章节采用有界摘要，保证多个路由卡可共存；
V3 方法卡保留完整已审计章节。通用生命周期段由确定性渲染器生成，不伪造数学 Claim、
Evidence、状态、工具调用或 Agent 回执。路由 Skill 置于通用 utility 排序之前，避免被
宽泛 Skill 挤出上下文。

旧 `mathforge/agents/registry.SkillRegistry` 仍作为 V2 兼容适配器存在；生产路径仍以
`mathforge/skills/registry.SkillRegistry` + `DynamicSkillSelector` 为唯一 Skill 投影来源。

## 3. 可重复维护工具与测试

新增：

- `scripts/migrate_mechmath_format.py`：对 Prompt/Skill 做确定性、幂等迁移；再次运行不会
  重复插入章节；
- `scripts/regenerate_prompt_snapshots.py`：按角色/协议模式矩阵重建编译 Prompt golden；
- `tests/test_phase_s7_mechmath_prompt_skill_format.py`：验证七个 Prompt、95 个 Skill、
  frontmatter、公共章节、生产投影、路由 Skill 优先级和 6000 字符预算。

`tests/fixtures/e2_compiled_prompt_snapshots.json` 已按当前合同重新生成，未放宽 golden
断言。

## 4. 验证结果

已通过：

```text
pytest -q tests/test_phase_s7_mechmath_prompt_skill_format.py \
  tests/test_phase_p1_p2_prompt_skill_reform.py \
  tests/test_s6_e4_prompt_contracts.py \
  tests/test_s6_e5_skills_router.py \
  tests/test_phase4_skill_packages.py \
  tests/test_phase_s3_p0_skill_rewrite.py \
  tests/test_phase_s4_external_skill_rewrite.py
33 passed

pytest -q
1069 passed, 2 failed
```

剩余 2 个失败均为既有治理清单阻塞：`docs/content_review_manifest.json` 的多个旧内容
哈希/数量没有在本阶段伪造重建，因此：

- `test_content_review_manifest_covers_all_scopes_but_blocks_human_freeze` 仍要求旧清单通过；
- `test_submission_validator_passes_repository` 依赖同一旧清单。

这是待人工数学/Prompt/Skill 审查后才能更新的发布证据，不是运行时 Prompt/Skill 格式错误。
本阶段没有把 `pending-human` 改成 `human-approved`，也没有编辑 release manifest 来掩盖门禁。

待执行的标准门禁（提交前）：

```bash
python -m compileall .
pytest -q
python scripts/verify_baseline_files.py
```

`main.py` 与 `llm_client.py` 未修改。当前变更没有真实模型准确率、官方测试分数或成本改善
声明；需要在人工内容审查完成、manifest 重新绑定后，再进行真实模型对照运行。

## 5. 人工复核与后续实施计划

1. 由数学/Prompt 专家逐卡检查 V3 的 `Exact Preconditions`、`Verification Recipe`、
   反例边界，以及新增通用段是否与该卡方法一致；重点关注所有 proof、收敛、复分析、
   线性代数和概率卡。
2. 复核角色卡是否与编译器最终协议一致，尤其是证明题 `final_response`、非证明题答案-only、
   trace 公开步骤和不泄露私有推理四项规则。
3. 以干净 commit、配置/依赖/数据集指纹和完整 per-case 输出重新生成
   `docs/content_review_manifest.json`；状态继续保持 `pending-human`，直到真实人工签署。
4. 运行真实 Intern-S2 FULL、必要的 C0–C7/组件消融以及 invalid/timeout/P95/成本门禁，
   再判断格式迁移对准确率和延迟的实际影响。

