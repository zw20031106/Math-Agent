# MathForge 整改阶段 3 执行报告

日期：2026-07-29  
阶段目标：完成可观测性、终稿保护、证明验证降级和低优先级一致性清理。

## 一、完成项

### F10：Terminalizer 故障可观测且 outcome 一致

- `RunMetrics` 新增 `terminalizer_failed_steps`。
- Trace、Metrics 或 Provenance 构造/类型契约异常会记录稳定步骤码，不再静默消失。
- Terminalizer 使用 Runtime 的真实 `outcome`、`final_phase`、`error_code` 覆盖兜底指标，
  避免“真实答案 + fallback 指标”或“fallback 答案 + primary 指标”。
- `fallback_used` 严格与 `outcome=fallback` 对齐。

### F6：Finalizer 空串保护

- 保存终稿前已经验证为非空的确定性格式化结果。
- 即使 Finalizer 错误返回 `used_llm=true` 和空文本，也回滚到确定性结果。
- Trace 记录 `used_llm=false, reason=finalizer_empty`。

### P4：证明完整性与运行成功状态解耦

Proof Completion Gate 由“strict 全删”改为分级处理：

- `complete`：完全验证，优先进入仲裁；
- `incomplete`：没有硬失败，降级保留并参与仲裁；
- `failed`：存在硬证据失败，禁止进入仲裁。

如果 Verifier 超时、不可用、返回非法 JSON，或工具无法覆盖所有证明义务：

- Candidate 不再被当作不存在；
- 仲裁选择最佳非反证 Candidate；
- 顶层运行 `outcome=primary` / `status=success`；
- Trace 记录 `fully_verified`、`degraded_accepted`、
  `selected_verification_status` 和未解决证明义务。

风险分级同时放宽：

- 不再由单个 `long_reasoning` 或仅三个复杂度标志直接判 high；
- high 需要至少四个复杂度标志，或 long reasoning 与至少两个复杂度标志共同出现。

### F5 / F8 / F9

- F5：删除 Provider 已保证不可达的 Solver 空响应重复判断。
- F8：Router 可达性预检改为直接基于静态总调用预算，不再读取此时恒为零的
  `used_calls`。
- F9：Hard Evidence Trace 改按 `candidate_id` 和修复替换关系判定 rejected，
  成功修复后的源 Candidate 不再被误标为拒绝。

### E1：删除陈旧 `build/` 重复树

- 删除被 Git 忽略的本地 `build/` 生成副本，共 218 个文件。
- 该目录不是源代码，无法从工作区恢复，但可以通过标准构建流程重新生成。
- 删除后只保留仓库真实源树，避免“改了源码但运行到 build 副本”的混淆。

## 二、验证结果

阶段定向回归：

```text
105 passed
```

覆盖：

- 完整、验证不完整、Verifier 非法输出和硬失败 Candidate；
- 证明义务与仲裁；
- Repair 回滚后仍保留原始可用候选；
- Finalizer 空串回滚；
- Terminalizer/RunMetrics 序列化；
- 路由风险、并发 benchmark 污染检查和可观测性。

## 三、阶段结论

阶段 3 已完成。系统现在遵循“验证用于评价和排序，而不是因为验证设施不可用就抹掉
答案”的原则：只有被硬证据否定的 Candidate 才被淘汰；验证不完整会降低置信度并在
Trace 中公开，但不会把已经存在的数学答案改成通用失败串。

## 四、边界与遗留项

- `status=success` 表示成功输出一个可用、未被硬证据否定的答案，不表示形式化证明已完成。
- 数学可信度必须读取 Trace 中的 `verification_status`、证明覆盖和未解决义务。
- 阶段 4 仍需执行全量回归、冻结文件校验、治理哈希与构建 Provenance 更新。
- 配置在没有真实 397B 环境验证前保持 `candidate-unvalidated`。
- `main.py`、`llm_client.py` 保持冻结，未修改。
