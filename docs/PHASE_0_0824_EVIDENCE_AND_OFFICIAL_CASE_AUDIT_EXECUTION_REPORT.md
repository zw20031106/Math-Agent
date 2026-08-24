# Phase 0（0824）执行报告：证据冻结与官方逐题审计门

日期：2026-08-24

运行时代码修改：无

真实模型调用：无

结论：Phase 0 的代码与治理能力已实现；由于没有与冻结版本指纹绑定的官方逐题导出，`active_baseline_id` 诚实保持为空。

## 1. 冻结对象

冻结候选为实施 Phase 0 前的干净提交：

```text
100133435fde1db2bdcd6f62a047437f40de9719
```

`data/evidence/phase0_0824_snapshot.json` 固定了：

- Competition config 语义指纹；
- Prompt 编译结果指纹；
- Skill 注册表指纹；
- `main.py`、`llm_client.py`、`user_agent.py` 与 `mathforge/**/*.py` 共 171 个 Python 源文件的内容指纹；
- Phase 0 要求的十类逐题错误 taxonomy；
- 当前官方证据的资格结论与未满足条件。

源文件指纹可直接从冻结 commit 的 Git archive 重算，不依赖当前工作区，也不受后续 Phase 修改影响。

## 2. 官方日志资格结论

已导入用户提供的 `eval_log_2e87215a108649b08cd784f8ba81adaa.log` 的去敏摘要和原文件 SHA-256。该日志记录：112 题中 8 correct、21 incorrect、83 invalid，869 次请求中 673 次 truncated。

它只能登记为 `diagnostic-only`，不能成为 active baseline，原因是：

1. 日志记录的提交 `d3210e5074c141f58142f4aa48d1ed75f0666411` 在当前仓库中不存在，无法验证源码；
2. 日志没有当前 config、Prompt、Skill、source 指纹；
3. 日志只有聚合统计，没有逐题输入、公开输出、候选谱系和模型调用时间线；
4. 日志不含证明题双人独立复核记录。

因此，本阶段没有用日期、文件名或“官方”标签替代可验证证据，也没有把旧提交结果伪装成当前准确率。

## 3. 新增逐题审计能力

`scripts/audit_official_cases.py` 接收完整 benchmark artifact、冻结快照和可选的证明题复核表，输出每题：

- 原始题目、题型、答案类型、response mode 与期望答案；
- 最终公开输出与 JSON 合法性；
- 被选 Candidate、所有 Candidate 的来源、版本、最终答案、状态和父谱系；
- 所有模型调用的 Agent/Turn/Candidate、阶段、起止时间、排队/执行时间、finish reason、截断和错误码；
- 非证明题的确定性自动评分，或证明题的人工裁决；
- 主错误类别与全部次级标签。

统一 taxonomy 为：

```text
parser_error
router_error
solver_wrong
protocol_invalid
truncated
provider_timeout
candidate_rejected
wrong_arbitration
trace_invalid
fallback
```

当错误同时存在时，审计保留全部标签，并按最早可识别的因果阶段确定 primary，不会用最终 `fallback` 覆盖更早的 Provider/Protocol/Candidate 原因。

## 4. 证明题复核契约

证明题不使用自动答案等价分数作为最终裁决。复核输入格式如下：

```json
{
  "case-id": {
    "reviews": [
      {"reviewer_id": "reviewer-a", "verdict": "correct", "signature": "..."},
      {"reviewer_id": "reviewer-b", "verdict": "incorrect", "signature": "..."}
    ],
    "adjudication": {
      "reviewer_id": "reviewer-c",
      "verdict": "correct",
      "signature": "..."
    }
  }
}
```

- 两名 reviewer 必须不同且各自签名；
- 两人一致时直接形成 verdict；
- 两人冲突时，必须由不同的第三人裁决；
- 输出只保留签名 SHA-256，不回显原始签名。

## 5. 激活门

只有同时满足以下条件时，审计结果才会给出 `active_baseline_eligible: true`：

1. 来源明确为 `official-platform-export`；
2. artifact 自身完整且哈希未被篡改；
3. Git commit、clean state、config、Prompt、Skill 与 source 指纹全部匹配冻结候选；
4. 逐题记录完整且 ID 唯一；
5. 每题能追到最终 Candidate 或明确 fallback；
6. 每次已消费模型调用都有时间线，数量与 RunMetrics 一致；
7. Trace 以 `run_completed` 闭合；
8. 非证明题完成自动评分；
9. 所有证明题完成人工双评/必要时第三人裁决。

运行方式：

```powershell
python scripts/audit_official_cases.py `
  --artifact <official-benchmark-artifact.json> `
  --snapshot data/evidence/phase0_0824_snapshot.json `
  --proof-reviews <proof-reviews.json> `
  --origin official-platform-export `
  --output <phase0-official-case-audit.json>
```

## 6. 验收状态

| 验收项 | 状态 | 证据 |
|---|---|---|
| HEAD/config/Prompt/Skill/source 冻结 | 通过 | `phase0_0824_snapshot.json` 与 commit 重算测试 |
| 十类 taxonomy | 通过 | 常量、快照与分类回归 |
| 非证明题自动评分 | 通过 | wrong-arbitration 回归 |
| 证明题双评/第三人 | 通过 | pending、冲突、裁决三路径回归 |
| per-case 调用时间线 | 通过 | 两次独立调用谱系回归 |
| Candidate 谱系 | 通过 | selected/viable-not-selected 回归 |
| 旧日志不误激活 | 通过 | official diagnostic-only 快照与 origin/fingerprint gate |
| 当前官方逐题结果导入 | 外部证据缺失 | 现有日志仅含聚合统计 |
| active baseline | 未激活（正确行为） | `active_baseline_id: null` |

当前唯一未闭环项不是代码缺口，而是缺少冻结版本对应的完整官方逐题导出。在该证据出现前，项目不能声明当前官方准确率，也不能进入 release 的 frozen 状态。
