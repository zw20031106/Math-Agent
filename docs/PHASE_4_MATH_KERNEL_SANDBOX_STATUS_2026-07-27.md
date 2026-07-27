# Phase 4 数学工具正确性与沙箱实施状态

日期：2026-07-27

范围：P4-01 至 P4-05

## 结论

Phase 4 已完成。数学工具由“敏感语法一律保守拒绝”的临时策略升级为最小
Domain-aware Expression IR，并在正式 ToolExecutor 路径中把全部 SymPy-backed
工具放入资源有界的独立 Worker。数值采样仍只提供 medium evidence。

## P4-01：Domain-aware Expression IR

新增的最小 IR 保留：

- `source_text` 与 `normalized_source`；
- 受限 Python AST 与 SymPy expression；
- 自由 symbols 和显式 domain；
- denominator、log、sqrt、分数幂、负指数和 tan 奇点条件；
- singularities、未满足条件、题面上下文完整性和约定歧义。

只有两侧源定义域一致、题面条件完整且共同定义域上的差值为零时，才产生
unconditional hard pass。可去奇点会返回带 `required_conditions` 的
conditional unknown；明确条件可解除对应义务。未明确自然数是否含零，或
复杂数分支语义未完整时，不构造 hard 结论。

第一版仍严格限定在既有 grammar：数值、symbol、`+ - * / ** %` 和
`abs cos exp log sin sqrt tan zeta`。没有开放 `sympify`、任意函数或任意
SymPy 语法。

## P4-02：独立数值采样

`numerical_residual` 不再给全部变量代入同一个数，而是按变量 domain 使用
确定性的独立笛卡尔样本。结果记录：

- symbol count；
- attempted、valid、rejected samples；
- maximum residual；
- `deterministic_independent_product` 策略。

real、integer、rational、natural-positive、natural-zero 和 complex 使用不同
样本池；自定义样本也按变量独立组合。该工具无论通过或失败都保持 medium。

## P4-03：SymPy 隔离与资源限制

- `safe_parse_expression`、`symbolic_equivalence`、`simplify_expression`、
  `numerical_residual`、`density_normalization` 和
  `small_case_enumeration` 全部标记为 isolated。
- Worker 启动前限制表达式字符数、AST nodes、整数位数、指数绝对值、嵌套
  深度和估算成本。
- Worker 请求、响应和 stderr 均有字节上限；工具 stdout/stderr 被丢弃，
  不进入协议。
- Linux/POSIX Worker 使用 CPU、address-space 和 file-size rlimit；
  Windows 仍由 wall timeout、输入复杂度和协议大小限制保护。
- timeout、进程失败、畸形响应和资源拒绝只产生 `unknown/error`，不会成为
  hard pass。

## P4-04：确定性性质测试

测试覆盖展开/因式分解、交换律、结合律、变量重命名、常数/符号扰动、
removable singularity、log、sqrt、分数幂、实数/复数域、自然数歧义、
非对角样本、变量置换、有限枚举 0/1/128/129 边界、density 不可判定和
matrix 维度错误。所有数据固定且不访问网络。

## P4-05：关键覆盖率门

Coverage 配置启用 branch、parallel 和 subprocess patch。关键门为：

- `mathforge/tools/symbolic.py` ≥ 80%；
- `mathforge/tools/numerical.py` ≥ 80%；
- `mathforge/tools/worker.py` ≥ 80%；
- `user_agent.py` ≥ 90%；
- `mathforge/verification/completion.py` ≥ 90%；
- `mathforge/harness/terminalizer.py` ≥ 90%。

本阶段实测分别为 92.31%、98.15%、93.44%、100%、95.45% 和 100%。
原有 Runtime、Evidence、Config 与 Formatter 关键门继续保留。

## 明确边界

SymPy Worker 无法在 Windows 提供 POSIX rlimit，但仍有统一 wall timeout、
请求/响应上限和计算前复杂度拒绝。Linux Python 3.10 的实际禁网 CI 属于
Phase 5；Competition 配置是否冻结仍必须等待 Phase 6 的真实模型证据与人工
签名。
