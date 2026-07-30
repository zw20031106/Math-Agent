# Phase 6 执行报告：Output、Manifest、闭环健康度与恢复

日期：2026-07-29  
状态：已完成  
依据：
`MathForge_Harness未执行整改与创新融合详细实施方案_2026-07-29.md`

## 1. 执行结论

Phase 6 的 14 项任务均已落地。公共输出仍严格保持
`id/status/final_response/trace` 四字段；Judge Trace 升级为 V3.1，每道终态
结果恰有一个 `closed_loop_health`。原 Phase 0 中 LaTeX、Journal、stale
Manifest 三项 XFAIL 均已转为正常 PASS。

最终离线验收：

- `python -m compileall .`：通过；
- `pytest -q`：`552 passed in 137.85s`，无 failed、无 xfailed；
- `python scripts/verify_baseline_files.py`：通过；
- `main.py`、`llm_client.py`：未修改。

Phase 6 不包含真实 Intern-S2 API 调用；真实模型验证属于 Phase 7。

## 2. 任务完成情况

| 序号 | 计划任务 | 实施结果 |
|---|---|---|
| 1 | 修复 Judge proof summary | 无选中 Candidate 时固定为 `not_available`，不再由空图误判为 complete |
| 2 | 修复路径脱敏误伤 LaTeX | Windows 盘符增加左边界约束；`\int`、`\in`、`\lim` 全部保留，真实绝对路径仍被删除 |
| 3 | 输出 viable Candidate 公共内容 | `viable_not_selected` 输出受限公共答案、公共步骤、proof 状态和选择原因；硬拒绝 Candidate 保持空内容 |
| 4 | 增加 `closed_loop_health` | 新增确定性健康度构建器并接入正常、fallback、timeout 和最小终态 |
| 5 | Health 与公共终态一致 | Judge Trace 校验 health、outcome、selected Candidate、answer availability 和 proof status |
| 6 | attempt-scoped Journal | Journal 改为 `.trace-journal/attempt-000N/<id>.trace.jsonl` |
| 7 | Manifest attempts 数组 | Manifest 升级为 1.3，保存 attempt id、状态、PID、host hash、heartbeat、契约和题目记录 |
| 8 | stale running 恢复 | Resume 获取新 attempt 前，将上一条仍为 running 的记录收尾为 `interrupted` |
| 9 | 重跑不覆盖旧 attempt | Canonical JSON 可原子替换；旧 attempt Manifest 记录和 Journal 目录永久分离 |
| 10 | Console failure 隔离 | `BrokenPipeError`、`OSError`、`UnicodeError` 不再反向污染已经写盘的题目状态 |
| 11 | Resume 完整校验 | 校验输入、配置、模型请求策略、并发、seed、case IDs、代码身份、Manifest/Judge Schema 和四字段契约 |
| 12 | 保留根因错误码 | 具体 transport failure 优先于 `all_candidates_failed` 等聚合错误 |
| 13 | Trace 压缩保护闭环 | health、selection、proof、budget、terminal 均为受保护事件 |
| 14 | 创新决策进入安全 Trace | Cache、Shadow、Adaptive Fanout、Cross-review 汇总为 `decision_summary` |

## 3. 闭环健康度

新增 `mathforge/output/loop_health.py`，健康度只评价 Harness 闭环是否完整，不
替代数学正确性判断。

输出结构包括：

- `model_dispatch`：调用数、上限、transport attempts、具体根因码；
- `candidate_flow`：Primary 恢复状态、Shadow 状态、Alternative 数量、viable
  数量和最终 Candidate；
- `verification_flow`：硬 Evidence、required obligations、Cross-review 和
  Repair 终态；
- `closure`：是否有答案、proof 状态、选择依据和降级原因。

健康等级：

- `healthy`：成功选中并完成闭环，无未解释关键退化；
- `degraded`：有答案，但存在 Shadow-only、Provider/Verifier 不可用或 proof
  不完整；
- `failed`：无最终可用答案；
- `timeout`：达到单题边界；
- `interrupted`：Manifest attempt 被外部中断或恢复接管。

若某个 Candidate 曾在中间阶段被选中，但最终进入 fallback，健康摘要会清空
最终 selected id 和 proof 终态，避免把中间状态冒充公开闭环。

## 4. Judge Trace V3.1

Judge Trace 新增：

- `closed_loop_health`：每题恰好一次；
- `decision_summary`：安全聚合 Cache、Shadow、Fanout 和 Cross-review；
- viable Candidate 字段：
  `public_final_answer`、`public_solution_steps`、`proof_status`、
  `selection_reason`。

安全边界保持不变：

- 不输出私有思维链；
- 不输出 raw response、完整失败 Candidate、原始异常或 traceback；
- 不输出 API 密钥和绝对路径；
- rejected/generation-failed Candidate 不公开答案与步骤；
- 公共步骤按事件预算结构化压缩，不截断关键终态事件。

## 5. Manifest 1.3 与恢复

每个 attempt 保存：

- `attempt_id`；
- `status`、`started_at`、`updated_at`、`heartbeat_at`、`ended_at`；
- `run_pid` 和脱敏的 `host_fingerprint`；
- 模型请求策略、代码身份和输出契约；
- 当前 attempt 的逐题状态、输出 hash 和 `attempt_id`。

Resume 契约新增：

- 固定请求模型 `intern-s2-preview-397b` 的内部策略；
- 只允许注入 Client 的 `client.chat` 接口；
- Git commit、dirty 状态和受控 Python 源树 SHA-256；
- Judge Trace 3.1、Manifest 1.3 和四字段输出契约。

这使“配置相同但代码/模型策略/输出 Schema 已改变”的续跑在模型派发前失败，
避免混合不可比结果。

## 6. 主要文件

新增：

- `mathforge/output/loop_health.py`
- `tests/test_phase6_0729_output_recovery_health.py`

重点修改：

- `mathforge/output/judge_trace.py`
- `mathforge/harness/events.py`
- `mathforge/harness/trace.py`
- `mathforge/harness/trace_journal.py`
- `mathforge/harness/terminalizer.py`
- `mathforge/runtime.py`
- `scripts/run_case_outputs.py`
- `docs/PUBLIC_OUTPUT_CONTRACT.md`
- `README.md`
- `CHANGELOG.md`

## 7. 验收映射

| 验收项 | 结果 | 证据 |
|---|---|---|
| Phase 0 三项 XFAIL 转 PASS | 通过 | 全量测试无 xfailed |
| 每题独立即时 JSON | 通过 | 既有原子写盘回归 + Manifest 绑定回归 |
| 顶层仅四字段 | 通过 | Phase 6 公共结果测试和生命周期测试 |
| 每题一个 health summary | 通过 | Health 唯一性与一致性测试 |
| failed/timeout/interrupted 准确 | 通过 | fallback、watchdog、stale attempt 回归 |
| 重跑保留历史 | 通过 | 两个 attempt Journal 与 Manifest 历史回归 |
| 根因不被聚合错误覆盖 | 通过 | `network_connect_failure` 保留回归 |
| Trace 压缩保护关键事件 | 通过 | 紧缩事件预算回归 |
| 无秘密、路径、原始异常、私有推理 | 通过 | 既有安全测试与 LaTeX/路径新增回归 |

## 8. 后续边界

Phase 7 需要在离线门禁保持通过的前提下，使用真实 Intern-S2 Preview 397B
完成分级 canary、失败注入、A/B 对比和配置冻结。Phase 6 未读取 API key、未
创建额外在线 Client，也未把模型 ID 依赖于环境变量。
