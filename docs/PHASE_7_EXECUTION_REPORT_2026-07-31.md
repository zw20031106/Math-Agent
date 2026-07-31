# Phase 7 执行报告

日期：2026-07-31
阶段：画像自校准、分级真实验证与配置冻结

## 1. 阶段结论

Phase 7 的实现、真实运行取证、画像生成和配置提案已经完成；配置冻结被正式
拒绝。当前状态继续为 `candidate-unvalidated`。

本阶段没有把“脚本执行结束”等同于“验收通过”。真实 88 题运行只落盘
82 题，并在第 80 题公共写盘时因超长恢复答案终止。该问题已经形成回归测试
并完成代码修正，但修正后的物理模型并发 16 和 LaTeX 输出契约尚未重新完成
4→16→88 真实验证，因此不能宣称 Phase 7 的 Live 门禁通过。

## 2. 本阶段完成内容

### 2.1 真实验证与画像

- 使用官方 Intern Client 和精确模型字段
  `intern-s2-preview-397b`；
- 使用 88 题 `dev_set_2.jsonl`；
- 题级并发为 4；
- 生成第三、第四、第五次测试的类型感知画像；
- 生成第五次测试 Evidence Manifest；
- 生成配置冻结提案并保持 `freeze_eligible=false`；
- 画像中的外部路径统一脱敏为 `<external>/<name>`；
- 画像绑定运行清单配置 SHA-256 与当前配置 SHA-256。

### 2.2 稳定产出修正

- Competition 物理模型并发和 background-tail 上限由 4 调整为 16；
- Candidate 最终答案增加 16,384 字符硬上限；
- `answer_recovered` 最终答案增加 4,096 字符硬上限；
- 超长答案在低题型置信度下仍然硬拒绝；
- 单题公共输出契约错误转为当前题 `failed`，不再击穿整个 runner；
- 分析 JSON 不再被画像脚本误当作题目输出；
- 画像终端只打印紧凑 ASCII 摘要，避免 Windows GBK 控制台因数学 Unicode
  再次异常退出。

### 2.3 数学答案与评分契约

- 数学型 `Final answer:` 使用 `$...$` LaTeX；
- Primary、Alternative、Repair Prompt 要求数学答案返回标准 LaTeX 源；
- Host Formatter 唯一化最终答案块并避免重复定界；
- 类型感知评分修复 `-\pi i=-i\pi`、Unicode 数域集合和 LaTeX 列向量的
  等价误判；
- 评分画像同时报告“已评分准确率”和“全部落盘题正确覆盖率”，不再把缺失
  答案从分母中静默删除。

### 2.4 冻结治理

- 配置哈希不一致时自动拒绝冻结；
- 答案评分覆盖不足 100% 时自动拒绝冻结；
- 人工审核状态或签名不完整时自动拒绝冻结；
- Frozen Lemma Store 没有审核记录，继续关闭；
- Prompt、输出格式和验证闭环纳入内容哈希与 Build Provenance。

## 3. 真实运行验收

| 验收项 | 结果 |
|---|---|
| 88 题独立 JSON | 82/88，未通过 |
| 状态成功率 | 75/82 = 91.46%，未通过 |
| 模型派发成功率 | 129/208 = 62.02%，未通过 |
| Candidate 接收率 | 75/82 = 91.46%，未通过 |
| 已评分答案正确率 | 75/75 = 100%，通过但不代表全量稳定性 |
| 单题调用最大值 | 5，满足 ≤6 |
| 单题最大耗时 | 497.60 秒，满足 ≤900 秒 |
| Health Trace 完整率 | 82/82 = 100% |
| 当前配置冻结 | 拒绝 |

详细数据见 `PHASE_7_LIVE_PROFILE_REPORT_2026-07-31.md`。

## 4. A/B 与人工审核状态

按计划的“前一级失败立即停止”约束，本阶段没有在基础稳定性失败后继续消耗
真实模型调用执行 Fanout、Shadow 或 Frozen Lemma Store A/B。离线机制保留，
但不能用离线测试替代真实 A/B 结论。

人工数学审核和治理签名仍为 pending。本阶段只完成工程复核，没有伪造人工
签名。

## 5. 配置状态

当前候选配置为：

- 题级并发：4；
- 模型物理并发：16；
- 单题模型调用硬上限：6；
- 单题外层墙钟：900 秒；
- 单次最终回答字符上限：20,000；
- 总上下文：262,144 Token；
- Frozen Lemma Store：off；
- Competition status：`candidate-unvalidated`。

其中并发 16 是用户指定且已完成离线回归的候选配置，本次真实运行使用的是
变更前并发 4，因此仍需新的同哈希 canary 验证。

## 6. 自动化验证

```text
python -m compileall -q .                  passed
pytest -q                                  625 passed in 162.97s
python scripts/check_coverage_gates.py     passed
python scripts/verify_baseline_files.py    passed
python scripts/verify_content_reviews.py   passed
python scripts/verify_build_provenance.py  passed
python scripts/validate_submission.py      passed with two expected warnings
python scripts/scan_secrets.py             passed
ruff check .                               passed
git diff --check                           passed
```

`validate_submission.py` 的两项预期警告分别是 Competition 配置尚未被真实
数据冻结，以及数学内容尚缺人工签名。正式冻结还需要覆盖率门禁、修正后的
真实 4→16→88 数据和人工签名；这些阻断项没有通过修改状态字段绕过。
