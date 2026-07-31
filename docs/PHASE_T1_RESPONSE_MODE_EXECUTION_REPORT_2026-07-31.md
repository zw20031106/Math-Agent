# Phase T1 Response Mode 执行报告

日期：2026-07-31  
阶段：T1——题型感知的公开输出模式契约

## 1. 阶段结论

Phase T1 已完成。`ProblemIR` 已由 2.0 升级为 2.1，并新增 Host 所有的
`response_mode`：

- `answer_only`：选择、填空、判断、普通计算和可直接作答的简答题；
- `worked_solution`：题目明确要求过程、推导、解释或理由；
- `proof_full`：题目明确要求证明。

本阶段只决定输出模式，尚未改变 `final_response` 和 Judge Trace 的实际格式。

## 2. 实现内容

1. 新增 `ResponseMode` 枚举并纳入 `ProblemIR` 序列化、反序列化和严格校验。
2. `ProblemParser` 使用中英文显式指令进行确定性判定，不为题型判定增加模型
   调用。
3. 允许官方公开 metadata 提供经过枚举校验的 `problem_type`、`answer_type` 和
   `response_mode`；无效值被忽略，不进入公开状态。
4. `problem_parsed` 内部事件开始记录 `response_mode`，供 T2/T3 消费。

## 3. 判定优先级

```text
有效公开 metadata
    -> 显式证明指令
    -> 显式过程/解释指令
    -> answer_only
```

显式证明包含“证明、证实、试证、prove、show that”；显式过程包含“写出过程、
推导、说明理由、解释原因、show your work、derive、explain、justify”。

## 4. 测试覆盖

新增测试覆盖：

- 中英文选择、填空、判断、计算和简答；
- 中英文证明；
- 推导、解释和过程要求；
- metadata 优先级；
- ProblemIR 2.1 round-trip；
- 非法 response mode 拒绝。

提交前执行：

```text
python -m compileall .
pytest -q
python scripts/verify_baseline_files.py
```
