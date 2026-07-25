# S6-A / E0 实施状态：安全、模型身份与基线冻结

日期：2026-07-24

对应计划：阶段 E0

提交目标：`S6-A: bind exact Intern model and secure run provenance`

## 结论

E0 的代码、自动化门禁与文档工作已完成。运行入口现在只接受环境变量
`INTERN_MODEL=intern-s2-preview-397b`；缺失、别名、大小写变体和前后空格均会在模型调用前失败。
调用方不能再通过 `--model-identifier` 或构造参数制造与实际请求不一致的展示标签。

平台侧 API Key 轮换无法由仓库代码执行或验证。此前在对话中出现的凭证必须由持有人在
Intern 平台撤销并生成新凭证；新凭证只能通过本地 `INTERN_API_KEY` 注入，完成轮换前不得
进行付费或正式 Live 测试。

## 基线

修改前基线：

- Git 工作树：clean，`main` 与 `origin/main` 一致；
- `python -m compileall .`：通过；
- `pytest -q`：255 passed；
- `python scripts/verify_baseline_files.py`：通过。

不可变文件 `main.py`、`llm_client.py` 未修改。

## 已实施内容

### 1. 精确模型身份门禁

- 新增 `mathforge.model_identity`；
- 唯一允许的模型 ID 为 `intern-s2-preview-397b`；
- 唯一可信来源为 `environment:INTERN_MODEL`；
- `ReasoningAgent`、逐题输出 Runner 和 benchmark Runner 均使用同一门禁；
- 在构造 Harness 和发起模型调用前完成校验；
- 删除两个 Runner 的 `--model-identifier` 自填标签入口。

### 2. 真实可观测性边界

官方注入接口只返回 assistant content，未返回响应模型标识和 thinking-mode 元数据。因此
provenance 只陈述“请求了哪个模型”，并固定记录：

- `response_model_observable=false`；
- `thinking_mode_observable=false`；
- `unobservable_reason=official_client_returns_assistant_content_only`。

Artifact 不再使用含义模糊的 `model_identifier`，也不生成虚构的 `response_model` 字段。

### 3. Provenance 与 Artifact

- RunProvenance：1.0 升级到 1.1；
- benchmark schema：3.1 升级到 3.2；
- 新增 `code_dirty`；
- 保留 Git commit、config、Prompt、Skill、RAG、Tool、内容审核和组件决策指纹；
- Artifact 顶层模型身份必须与嵌套 provenance 完全一致；
- 即使重新计算 Artifact hash，alias 模型仍会被验证器拒绝。

`code_dirty=true` 表示运行时提交之外仍有 tracked 或 untracked 变更；Git 不可用时为
`null`，不得伪装为 clean。

### 4. 凭证防泄露

- 新增 `scripts/scan_secrets.py`；
- 扫描 Git tracked 和未忽略的 untracked 文件；
- 命中时只输出类型、相对路径和行号，不回显凭证；
- `scripts/validate_submission.py` 已接入该门禁；
- `.env`、`.env.*` 和结果目录默认忽略；
- 提供不含真实凭证的 `.env.example`。

## 自动化验收覆盖

新增或更新的测试覆盖：

- 模型变量缺失时早失败且没有模型调用；
- Legacy `intern-s2-preview`、`intern-latest`、大小写变体和空白变体被拒绝；
- requested model 精确为小写 397B 版本 ID；
- 调用方伪造展示标签无效；
- response model 与 thinking mode 明确不可观测；
- provenance 记录 Git dirty 状态；
- Artifact 顶层与嵌套模型身份必须一致；
- alias Artifact 即使重新签名仍被拒绝；
- secret scan 能发现凭证模式但不回显凭证；
- 仓库当前扫描无凭证命中。

## C01-C26 对应验收

| 标准 | E0 结果 | 后续阶段 |
|---|---|---|
| C05 Competition 配置绑定 | 精确 397B 模型门禁完成 | E1 继续完成 256K 与 900 秒配置 |
| C20 终态和错误码 | 模型身份配置在调用前安全失败 | 完整 timeout 终态由 E1/E7 完成 |
| C21 Benchmark/污染 | 移除自填模型标签，模型身份和 provenance 同源 | Trace/逐题恢复由 E2/E7 完成 |
| C25 Provenance/人工审核 | commit、dirty、模型可观测边界与各组件 hash 已记录 | 平台 Key 轮换和最终人工签名仍需外部完成 |

## 运行要求

PowerShell：

```powershell
$env:INTERN_MODEL = "intern-s2-preview-397b"
$env:INTERN_API_KEY = "<rotated-key>"
python scripts/run_case_outputs.py --input cases.jsonl --output-dir case-outputs
```

提交前门禁：

```powershell
python -m compileall .
ruff check .
mypy mathforge user_agent.py
pytest -q
python scripts/scan_secrets.py
python scripts/verify_baseline_files.py
python scripts/validate_submission.py
git diff --check
```
