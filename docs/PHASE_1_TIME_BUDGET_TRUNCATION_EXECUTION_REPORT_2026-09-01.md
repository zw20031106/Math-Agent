# Phase 1：时间预算与截断判定执行报告

日期：2026-09-01

## 范围与目标

本阶段严格对应 0901 全项目重审实施计划的 Phase 1，目标是移除 700 秒
死亡线、避免阶段超时造成的后台僵尸调用，并把截断识别从末字符启发式改为
保守的三态判定。代码与测试证据和真实 Intern 模型证据分开记录；本报告不把
本地单测结果当作数学准确率。

## 已完成的实现

### 1.1–1.4 时间预算与阶段准入

- `DeadlineController.can_start_stage_call(stage_timeout=...)` 现在以具体阶段
  timeout、hard deadline 和 deterministic-finalize reserve 判断是否可以启动。
- `CallBudget.consume()`、Provider gate、TaskGraph 各模型 wave 和所有 Agent
  调用点均传递 `stage_execution_policy` 中的真实阶段 timeout。
- Provider 的实际等待窗口为
  `min(阶段 timeout, remaining_for_model_call())`，不会因配置的长 timeout
  把调用延伸到 case 已结束之后。
- timeout 不超过 60 秒的确定性末期步骤仍可在 exploration boundary 之后启动，
  但必须保留最终化 reserve；普通长阶段不能在 exploration boundary 之后启动。
- Competition 配置改为 `exploration_deadline_seconds=770`、
  `model_call_start_margin_seconds=30`，hard deadline 仍为 850 秒、最终化
  reserve 仍为 50 秒。

### 1.5 Provider 熔断

- 批处理熔断器只把网络连接/读取、限流、服务端错误、鉴权、空响应和未知
  Provider 错误作为连续 Provider 故障。
- `model_response_deadline_exceeded`、并发等待耗尽、响应 schema/JSON/候选
  校验失败不再计入 Provider 熔断。
- 默认连续失败阈值从 3 调整为 6，并加入 cooldown 后的 half-open 探针恢复。

### 1.6–1.7 三态截断与消费

- `_looks_truncated()` 删除末字符规则，返回 `complete`、`suspect` 或
  `truncated`。空响应、未闭合 `<think>`、达到 98% 输出上限、首层 JSON/数组
  容器未闭合属于硬截断；长文本半词/半命令结尾只记录为 `suspect`。
- `suspect` 仅进入公开调用记录，不触发拒绝、重试或截断计数；只有硬
  `truncated` 进入原有部分结果/重试路径。
- `ObservedModelResponse`、CallBudget ledger 和 judge trace projection 保存
  `truncation_status`，保证分类可审计。

### 1.8 上下文约束

`effective_output_tokens()` 接受 prompt token 数、context window 和 safety
margin，并按
`min(stage_cap, configured_cap, context_window - prompt - safety_margin)`
计算有效输出上限。Provider 将该结果与 `ModelContextBudget.allocate()` 的
不可变分配进行一致性校验，并记录胜出的 context 限制。

### 1.9 观测输出准入

CallBudget 保留最近 8 次实际 completion token 的滑动窗口，下一次准入使用其
观测均值的向上取整进行输出 token 预留，不再用请求上限作为预测值；完成、失败、
超时或未派发退款都会释放预留。

## 验证结果

### 定向不变量测试

- Phase 1 新增测试：6 项通过。
- 时间预算、Provider 稳定性、阶段执行策略、截断恢复、调度与取消回归测试：
  57 项通过。
- Solver/lemma/protocol 长期截断相关回归：33 项通过。

### 全量回归

阶段实现初版全量执行为 1015 passed、5 failed；失败原因已分别修正（阶段配置
旧断言、合成短时 Deadline 兼容性、治理指纹同步）。最终全量执行结果为
**1020 passed in 166.88s**。

提交前必须执行：

```text
python -m compileall .
pytest -q
python scripts/verify_baseline_files.py
python scripts/verify_content_reviews.py
python scripts/verify_build_provenance.py
python scripts/validate_submission.py
```

## Gate 1 证据边界

本阶段已用确定性测试覆盖阶段准入、三态分类、上下文上限、观测均值准入和
熔断半开恢复。尚未在本阶段自动声称本地 30 例或官方 112 例的真实模型准确率、
P95、截断率或执行覆盖率；这些指标必须来自同一提交、同一 Competition 配置、
同一模型身份和完整 run manifest 的真实 Intern 客户端运行。未获得完整的本地
30 例 + 官方 112 例 Gate 1 工件前，candidate-unvalidated 状态保持不变。

## 风险与回滚

- 三态规则保留 `suspect` 观测，避免把放宽判定误当成数学正确性；如真实运行
  显示真截断漏检，只需调整硬信号阈值或消费策略，不恢复末字符规则。
- 阶段 timeout 与剩余窗口双重约束保留 850 秒 hard deadline；若 Provider
  延迟异常，熔断器只对真实服务故障动作，不会把本地时间预算问题扩大成全局
  停摆。
- 所有改动都在可回滚的单独 Phase 1 提交中，官方冻结/基线状态不被本阶段改变。
