# Math-Agent E1：Source-of-Truth 与协议一致性执行报告

## 1. 执行结论

E1 已按 2026-08-27 整改计划落地。本阶段不修改冻结的
`main.py` 或 `llm_client.py`，并保持 `ReasoningAgent.solve(problem, metadata)`
的公开 JSON 契约。competition 配置仍保持 `candidate-unvalidated`；本报告中的
回归证据是工程/确定性证据，不替代真实模型 FULL run、官方平台评分或人工数学复核。

## 2. Source-of-Truth 收敛

- `AgentRegistry.default()` 的七个固定角色版本全部从
  `PromptContractLoader` 合同 frontmatter 读取，不再维护 Prompt version 字典。
- `ActionRegistry` 统一声明角色能力、阶段/Prompt Action enum、Action handler
  路由和注册校验；权限矩阵与各 Agent parser 均从该 registry 获取允许动作。
- 新增不可变 `ProblemConditionEnvelope` 与统一 builder，将 definitions、
  quantifiers、constraints、assumptions、domains、target、ambiguities 作为同一
  条件投影提供给 Solver、Lemma、Verifier、Repair 和 Final Audit。
- `mathforge/skills/selector.py` 保留唯一 `DynamicSkillSelector` 类定义，
  `mathforge/agents/skill_selector.py` 仅保留兼容别名。

## 3. 协议与错误边界

- Provider 在任何 `client.chat` 之前完成 stage、turn kind、role、artifact、
  Plan/ACK barrier 等 begin 校验；invalid task、unknown role、missing artifact
  和 stale plan 均 fail-closed。
- 内部错误被归类为 `EXPECTED_DEGRADATION`、`PROVIDER_FAILURE`、`DEADLINE`、
  `INVARIANT_VIOLATION` 或 `PROGRAMMING_ERROR`，并写入内部 trace、run metrics
  与 sanitized debug record。
- competition 保持安全返回并保留精确类别；test/CI 对 invariant/programming
  错误重新抛出，避免测试绿灯掩盖实现缺陷。

## 4. 验收证据

当前确定性回归结果：

```text
pytest -q                         934 passed
python -m compileall .            passed
python scripts/verify_baseline_files.py       passed
python scripts/verify_content_reviews.py      passed
python scripts/verify_build_provenance.py     passed
python scripts/validate_submission.py          passed
```

新增 E1 专项测试覆盖 Prompt version、Action/handler 对齐、条件 canary、单一
Skill selector、四类 Provider begin fail-closed 场景以及错误分类/竞赛安全返回/
test mode re-raise。官方形式化烟雾入口也已回归通过；其使用的是仓库内确定性
`FormalSmokeClient`，因此不构成真实模型正确率或官方平台证据。

## 5. 后续门禁

只有完成真实 FULL/C0–C7/component ablation、invalid/timeout/P95/cost gates、
证明双评和可复现 provenance 检查后，才允许把 competition 状态从
`candidate-unvalidated` 改为 `frozen`。
