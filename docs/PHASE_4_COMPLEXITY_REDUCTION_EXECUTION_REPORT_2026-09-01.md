# Phase 4：复杂度削减与准确率门禁执行报告

日期：2026-09-01

## 范围与判定原则

本阶段对应 0901 全项目重审计划的 Phase 4（复杂度削减与制度化）。本报告把
“代码/测试不变量”与“真实 Intern 模型准确率”分开记录：本阶段没有调用外部
模型，也没有把旧日志或本地模拟结果当成数学准确率证据。

## 已执行的整改

### 4.1 公共 Judge Trace 投影精简

- 将 `mathforge/output/_judge_trace_projection.py` 从历史约 3,001 行实现替换为
  单一声明式投影：字段白名单、候选摘要、证据/证明闭环、修复历史、模型活动、
  诊断、隐私过滤和边界裁剪均由同一入口生成。
- 保留 `project_judge_trace`、`validate_judge_trace`、`minimal_judge_trace`、
  `JudgeTraceLimits` 及固定 13 字段候选摘要契约，避免修改官方公共结果接口。
- 公开投影仍禁止原始响应、提示词、私有推理、绝对路径、密钥和异常堆栈；所有
  事件继续经过大小、序号、阶段和 JSON 可序列化校验。
- 精简后的文件当前为 564 个物理行、469 个非空行。它已显著小于历史实现，
  但尚未达到计划中“≤400 行”的目标，后续应在不改变公共契约的前提下继续拆分
  或删除低价值投影字段。

### 4.2 兼容路径与多智能体约束

- `config/competition.json` 中 `enable_rag`、`enable_finalizer`、`enable_shadow`
  和 `enable_frozen_lemma_store` 保持关闭；启动测试确认关闭组件不会被导入。
- 这些模块仍保留为已覆盖的兼容性配置和历史回归测试所需的代码，不能在当前
  版本直接删除：删除会破坏既有配置合同和对应测试。它们不属于 competition
  profile 的执行路径，报告不把它们误报为已获得收益。
- `RouterPlanner` 的真实注入式模型调用保持不变。项目级 `AGENTS.md` 要求每题
  经过 RouterPlanner 且被准入的角色必须通过注入的 `client.chat` 产生可观测调用，
  因此本阶段没有按计划文字删除路由器模型分支；只保留了现有规则回退作为失败
  时的确定性路径。若要切换到纯规则路由，必须先更新该高优先级合同和相应证据。

### 4.3 从内部记账转向数学正确性门禁

- 新增 `mathforge/evaluation/accuracy_gate.py`，固定总题数为分母，缺少公共答案、
  不可评分结果和重复题号均 fail-closed；允许的回归下降阈值默认是 2 个百分点。
- 新增 `data/evidence/local88/golden30.jsonl`，固定 30 题，覆盖数学分析、高等
  代数、概率论、抽象代数以及 symbolic/integer/tuple/interval 评分器。
- 新增 `scripts/check_accuracy_regression.py`。它既可读取显式的
  `{case_id: final_response}` 映射，也可直接读取 `run_case_outputs.py` 生成的逐题
  公共 JSON 目录，因而门禁消费的是端到端交付答案而不是内部候选计数。
- 新增测试覆盖：固定题集和跨领域覆盖、全正确响应通过、单题错误超过 2pp 失败、
  缺失响应即使扩大阈值也失败，以及逐题公共结果目录解析。

### 4.4 复杂度 CI 门禁

- 新增 `scripts/check_complexity_budget.py`，统计 `mathforge/**/*.py` 的非空源代码
  行数并忽略缓存目录；默认硬上限取主计划 S8 的 55,000 行，支持 CLI 显式覆盖。
- 新增测试确认统计口径和上限约束。当前工作树测量为 60,209 个非空 Python 源码行，
  因而 55,000 行门禁仍失败；没有通过调整阈值或伪造清单来掩盖该事实。
- 详细版计划另写了 45,000 行目标，与主计划 S8 的 55,000 行硬约束不一致；本阶段
 以主计划的 55,000 行作为 CI 默认，并在后续阶段单独处理该文档冲突。

## 验证结果

- 投影、修复历史、证明闭环、答案来源和准确率门禁的定向回归：通过。
- 完整单元测试：最终 `1046 passed`。首次运行发现 3 项失败，其中 1 项是精简
  投影遗漏 `accepted` 派生字段，已修复；另外 2 项是内容审查指纹尚未随本阶段
  改动更新，已在收尾时刷新治理指纹。
- 本阶段最终提交前仍必须执行：

  ```text
  python -m compileall .
  pytest -q
  python scripts/verify_baseline_files.py
  python scripts/verify_content_reviews.py
  python scripts/verify_build_provenance.py
  python scripts/validate_submission.py
  ```

## Gate G4 状态

| 门禁 | 结果 | 证据 |
|---|---|---|
| 准确率回归门禁存在并可 fail-closed | 通过 | `tests/test_accuracy_regression.py` |
| 公共投影大幅精简 | 部分通过 | 564 物理行 / 469 非空行，未达 ≤400 |
| `mathforge` ≤55,000 非空行 | 未通过 | 当前 60,209 行 |
| 真实 30/88 题数学准确率不低于 Phase 3 | 未执行 | 需要注入 Intern API 的真实跑批，不能由单测推导 |

因此，本报告只确认 Phase 4 的复杂度治理和准确率门禁基础设施已经落地，
不宣称 Gate G4 已全部通过，也不宣称任何官方 112 题或本地 88 题准确率提升。

## 后续与回滚

- 若复杂度预算仍超限，优先在 `runtime.py`、`reasoning_state.py`、
  `scheduler_flow.py` 和 `harness/truncation.py` 做逐文件、可回归验证的拆分；
  不在没有调用图和测试覆盖的情况下批量删除核心运行逻辑。
- 若真实评测显示降级答案污染或准确率回退，可关闭准确率门禁之外的兼容路径，
  或回退本阶段的投影实现；`accuracy_gate`、golden set 和测试本身可独立保留。
