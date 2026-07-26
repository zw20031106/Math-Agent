# Phase 0 证据冻结与安全治理实施状态

日期：2026-07-26
实施基线：`1a9b10c7d44c3a641972d79ff5e4936829af90fa`

## 1. 已完成

1. 只读检查运行进程，未发现仍在执行的 88 题批测。
2. 对三组现有结果计算了确定性目录指纹，没有移动、删除或重写原文件。
3. 新增 `data/evaluation_evidence_registry.json`，采用 `explicit-allow`：
   - 未明确标为 `eligible-baseline` 的结果不能作为准确率基线；
   - 只有精确模型、当前 commit、当前 config、四字段输出且 Manifest 为
     `completed` 的证据才可能被激活；
   - 当前 `active_baseline_id` 为 `null`。
   - `baseline_candidate_git_commit` 记录待评测代码基线，不把登记表自身的
     后续治理提交误当成被评测提交。
4. 新增登记表 Schema、路径安全、唯一 ID、Hash、模型、配置、提交、输出合同和
   Manifest 状态校验。
5. 新增可选的本地目录复验：

   ```powershell
   python scripts/verify_evidence_registry.py `
     --results-root "D:\研究生阶段的课件和资料\揭榜挂帅擂台赛\Agent开发\测试结果"
   ```

6. 将登记表校验接入 `scripts/validate_submission.py`。

## 2. 当前证据分类

| ID | 内容 | 分类 | 基线资格 |
|---|---|---|---|
| `legacy-run1-88` | 旧提交的 88 个三字段结果 | historical-ineligible | 否 |
| `aborted-uppercase-model` | 大写模型标识、两个 running Manifest 的中止结果 | historical-ineligible | 否 |
| `provider-failure-diagnostic-2-cases` | 当前提交下两题 Provider fallback | diagnostic-only | 否 |

这些结果仍可用于复盘历史输出、Transport 故障和回归风险，但不得用于声明当前提交
的准确率。

## 3. 没有越权执行的事项

- 没有修改冻结的 `main.py`、`llm_client.py`。
- 没有创建新的在线模型客户端。
- 没有读取、写入或打印 API Key。
- 没有删除或移动历史测试结果。
- 没有把 Competition 状态改为 frozen。

## 4. 外部待办

用户曾公开粘贴过 API Key。密钥轮换只能在 Intern 平台完成，无法由仓库代码代替。
在新密钥生成后应撤销旧密钥，并仅用当前 PowerShell 进程环境变量注入，不写入仓库、
Markdown、JSON、命令历史或结果 Trace。

## 5. Phase 0 完成条件

- 证据登记表 Schema 和目录指纹校验通过；
- Secret Scan 通过；
- 冻结基线文件校验通过；
- 全量测试通过；
- `active_baseline_id` 保持为空；
- 用户在平台侧完成旧 API Key 撤销后，安全项才完全闭环。
