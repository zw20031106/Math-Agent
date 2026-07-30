# Phase 0 执行报告：基线冻结、等价评分与故障分类

日期：2026-07-30
阶段结论：完成，可进入 Phase 1
真实模型调用：未执行（本阶段只建立离线、可复现证据）

## 目标与实施

本阶段遵循
`MATHFORGE_FULL_PROJECT_STABILITY_ACCURACY_AND_LONG_HORIZON_AUDIT_2026-07-30.md`
的 Phase 0 计划：先校正评测和冻结基线，不改变官方模型接入边界。

已完成：

- 将 `\pi^2/6-(\ln2)^2` 与 `\frac{\pi^2}{6}-(\ln2)^2`、
  `8\pi^6/63` 与 `\frac{8\pi^6}{63}` 固化为 symbolic scorer golden tests。
  当前评分器已正确处理这些形式，因此没有为了制造改动而重写评分代码。
- 固定三组去敏、可追溯的基线数据：
  - `tests/fixtures/phase0_reliability.jsonl`：连接失败、读取超时、空响应、
    Candidate Schema 错误与成功响应；
  - `tests/fixtures/phase0_general_high_difficulty.jsonl`：12 题，覆盖分析、代数、
    概率、离散、数论、几何、优化、线性代数、特殊函数、参数分析等一般数学领域；
  - `tests/fixtures/phase0_contract_adversarial.jsonl`：行首 `A `、长条件、多目标、
    工具 Claim、候选冲突和结构化输出压力。
- 新增 `scripts/build_phase0_baseline.py`，生成
  `data/phase0_baseline_manifest.json`。清单仅保存仓库相对路径、哈希、样本数、
  指标定义和去敏的历史可靠性摘要。
- 将 transport、schema、logic、verification、formatting 五类故障纳入清单的
  `failure_taxonomy`；其中 transport 与 schema 均有实际注入回归，logic、
  verification、formatting 由契约对抗集覆盖。

## 产物

| 产物 | 作用 |
|---|---|
| `data/phase0_baseline_manifest.json` | 固定配置与三个数据集的内容哈希、样本规模、指标口径和故障分类 |
| `scripts/build_phase0_baseline.py` | 重新生成并验证基线清单 |
| `tests/test_phase0_phase1_0730.py` | 等价评分、可靠性故障注入、Schema 边界和基线隐私回归 |

## 验收结果

- 等价评分 golden tests：通过，2/2。
- 基线 manifest：可由构建脚本逐字再生；数据集规模为 reliability 5、
  general_high_difficulty 12、contract_adversarial 6。
- 故障分类：五类均在 manifest 中有明确归属；连接、超时、空响应与 Schema
  注入均返回稳定、非敏感的错误码。
- 安全边界：清单不含 API key、Authorization、绝对路径或私有推理文本。
- 不修改 `main.py`、`llm_client.py`，且没有建立新的在线模型客户端。

## 验证记录

```text
python scripts/build_phase0_baseline.py
python -m pytest -q -p no:cacheprovider --basetemp <external-temp> <all 69 test modules>
python -m compileall -q mathforge user_agent.py
python scripts/verify_baseline_files.py
```

结果：全量测试按两个无重叠分组完成，`150 passed + 417 passed = 567 passed`；
编译和不可变基线校验通过。临时目录置于仓库外，避免 Windows 默认 `%TEMP%` 权限和
安全扫描的测试样本相互干扰。

## 对 C01–C26 的相关贡献

本阶段直接支撑 C01（数学答案评测可信）、C07（传输失败可分类）、C22（离线回归）、
C23/C25（模型边界、去敏与不可变文件）。并发、长程推理和复杂工具闭环仍由后续阶段验收，
本报告不将其提前宣称为完成。
