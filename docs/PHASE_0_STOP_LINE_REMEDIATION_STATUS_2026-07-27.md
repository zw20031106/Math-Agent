# Phase 0 停止线整改实施状态（2026-07-27）

## 结论

状态：**Engineering Stop-line Passed**

本状态只表示 P0-01 至 P0-06 的工程停止线已关闭；不表示配置已冻结，
也不替代真实 Intern 模型基准、数学内容人工签署或竞赛验收。

## 已完成任务

| 任务 | 实施结果 | 回归证据 |
|---|---|---|
| P0-01 正式入口与模型身份解耦 | 正式 `ReasoningAgent` 仅使用注入的官方 client，缺少 `INTERN_MODEL` 与 `INTERN_API_KEY` 仍可构造和求解；本地 benchmark/case runner 继续执行精确模型 ID 门禁 | `test_formal_entry_does_not_require_local_model_or_api_environment`、既有模型门禁测试 |
| P0-02 严格 Candidate 冒烟 | 新增唯一严格冒烟 fixture，检查四字段、`success`、答案 2、列表 trace 和无 fallback；提交校验与离线安装复用同一 fixture | `test_formal_smoke_is_a_true_non_fallback_success` |
| P0-03 元数据隔离 | LLM 运行时白名单缩减为 `idx`、`id`、`case_id`、`benchmark_nonce`，答案、标签和 split 不进入 context/memory/prompt/trace | metadata canary 回归 |
| P0-04 有限枚举 fail-closed | 空输入和超过 128 项返回 `unknown`；取消切片截断；payload 记录 `input_count`、`checked_count`、`truncated=false`；Schema 同步 1–128 边界 | direct、registry、executor 三层回归 |
| P0-05 符号等价定义域守卫 | 普通多项式仍可 hard pass；变量分母、根式、对数和非多项式幂在定义域等价未证明时不得无条件 hard pass；自然数约定不明确时返回 `unknown` | 定义域矩阵回归及既有工具测试 |
| P0-06 集成门禁与状态 | 更新工具能力边界、内容审查哈希和 Changelog；保持 `candidate-unvalidated` / `pending-human` 治理状态 | 全量门禁 |

## 验收口径

- 正式入口不读取 API key，不建立第二模型 client，不修改 `main.py` 或
  `llm_client.py`。
- 冒烟成功必须来自严格 Candidate 主路径，fallback 不能冒充成功。
- answer-bearing metadata 金丝雀不得出现在任何模型消息或公开 trace。
- 空枚举、超限枚举、静默截断不得生成 hard pass。
- 符号化简不得通过消去奇点或忽略实数定义域制造无条件 hard pass。

## 门禁记录

- Phase 0 定向回归：28 passed。
- 全量 `pytest -q`：400 passed。
- `python -m compileall .`：通过。
- `python scripts/verify_baseline_files.py`：通过。
- `python scripts/validate_submission.py`：通过。
- `python scripts/scan_secrets.py`：通过。
- `ruff check .`、`mypy mathforge user_agent.py` 及本阶段脚本、
  `git diff --check`：通过。
- `python scripts/verify_offline_install.py --prepare-wheelhouse`：通过。

以上记录以本阶段提交前的最终门禁输出为准。

补充说明：`mypy .` 仍报告 26 个阶段前既存问题，位于不可变 baseline、
旧测试类型标注及既有 runner；Phase 0 没有越界修改这些文件。项目生产源码
及本阶段新增/修改脚本的类型检查已通过。
