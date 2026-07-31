# Phase T0 公开输出基线执行报告

日期：2026-07-31  
阶段：T0——第六次测试公开输出契约基线固化

## 1. 阶段结论

Phase T0 已完成。第六次真实测试的 88 个独立 JSON 已被固化为可复现的聚合
基线；基线只保存统计、状态和内容哈希，不保存 API、题目正文、原始模型响应、
绝对路径或私有推理。

本阶段没有修改 `main.py`、`llm_client.py` 或 MathForge 运行时行为。

## 2. 基线结果

| 指标 | T0 基线 |
|---|---:|
| 结果覆盖 | 88/88 |
| 顶层公开契约有效 | 88/88 |
| 成功/失败 | 86/2 |
| `final_response` 字符数 P50/P95/Max | 564.5 / 1050.6 / 1770 |
| Trace 字符数 P50/P95/Max | 24517 / 27990.45 / 31703 |
| Trace 事件数 P50/P95/Max | 19 / 20 / 22 |
| 首事件为 `solution_process` | 0/88 |
| 含公开候选内容 | 24/88 |
| `skills_selected` 字符数 P50/Max | 11181.5 / 11588 |

这些数据确认了 T1–T5 的三个直接整改目标：按题型收紧 `final_response`、把
公开解题步骤移动到 Trace 首项、删除 Judge Trace 中未实际需要的 Skill 正文与
重复状态。

## 3. 新增文件

- `scripts/profile_public_output_contract.py`：对独立 JSON 结果生成稳定、脱敏的
  公开输出画像。
- `data/t0_output_contract_baseline_2026-07-31.json`：第六次测试的聚合基线和
  Evidence 哈希。
- `tests/test_t0_output_contract_baseline.py`：验证画像确定性、顶层契约、候选
  内容统计和外部路径脱敏。

## 4. 验收口径

T1–T5 完成后使用同一脚本复测，并检查：

1. `trace[0].event == "solution_process"`；
2. 可直接作答题不再输出冗余过程；
3. 每个成功候选均有安全的公开内容或显式引用；
4. Trace P50 字符数相对 24517 至少下降 40%；
5. 88 题独立落盘和顶层 `id/status/final_response/trace` 契约不退化。

## 5. 验证

提交前执行：

```text
python -m compileall .
pytest -q
python scripts/verify_baseline_files.py
```
