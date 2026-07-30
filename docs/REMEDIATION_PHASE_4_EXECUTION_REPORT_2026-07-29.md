# MathForge 整改阶段 4 执行报告

日期：2026-07-29  
阶段目标：完成全量回归、冻结边界校验、构建来源一致性和正式离线入口验收。

## 一、完成项

### 全量回归与兼容性收口

第一轮全量测试为 `494 passed, 4 failed`。4 项失败均已定位并处理：

1. 旧测试仍假设 Verifier 不可用时必须删除原始 Candidate，现已按
   `best_available` 语义更新；
2. `content_review_manifest.json` 更新后，构建来源清单中的 SHA-256 尚未同步，
   现已刷新；
3. 引理扩展 Candidate 在没有完成 VerifierSkeptic 复核时一度可能以
   `incomplete` 身份进入仲裁，现已恢复安全边界并记录
   `expanded_candidate_not_skeptic_reviewed`；
4. 风险分级放宽后，原“六类通用 Skill 均可到达”测试题只会被判为 medium，
   测试样例已改为确实具有四项复杂度标志的 high-risk 证明题。

第二轮全量测试全部通过：

```text
498 passed in 113.22s
```

### 冻结文件与公开契约

- `main.py`、`llm_client.py` 的不可变基线校验通过；
- 正式入口离线冒烟通过；
- `ReasoningAgent.solve()` 的公开结果仍为 JSON 可序列化映射；
- 输出保留非空 `final_response`、列表型 `trace` 和一致的状态/指标；
- 正式 Harness 仍只使用注入的 `client.chat(...)`，没有读取 API Key、
  创建第二在线客户端或依赖原生 function calling。

### 构建、内容与证据治理

以下治理检查全部通过：

```text
Submission validation passed.
Build provenance manifest verified.
Content review manifest verified.
Evidence registry verified.
Formal entry offline smoke passed.
```

- Prompt Compiler 的内容审查哈希已更新；
- Build Provenance 中的内容审查清单 SHA-256 已同步；
- `CHANGELOG.md` 已增加本轮阶段 0—4 整改记录；
- 被忽略的陈旧 `build/` 生成副本已在阶段 3 清除。

## 二、验收命令

```powershell
python -m compileall -q .
pytest -q
python scripts/verify_baseline_files.py
python scripts/validate_submission.py
python scripts/verify_build_provenance.py
python scripts/verify_content_reviews.py
python scripts/verify_evidence_registry.py
python scripts/formal_offline_smoke.py
```

所有命令退出码均为 `0`。

## 三、阶段结论

阶段 4 已完成。审查报告中的离线可验证整改已经闭环：

- 慢调用不会再因单个后台尾调用立即熔断整个 Harness；
- 已成功返回的 Candidate 不会因进入 deterministic finalize 窗口而被丢弃；
- 未分发的模型请求会退还调用预算；
- 角色输出软预算不再错误覆盖 256K 总上下文边界；
- 原始但未完全验证的可用 Candidate 会降级参与最佳可用仲裁；
- 被硬证据否定或未经怀疑者复核的扩展 Candidate 仍被禁止进入仲裁；
- 空 Finalizer、Terminalizer 局部失败和模型身份未知均有明确、真实的状态。

## 四、未伪造的外部验收状态

本阶段没有可用的官方 Intern-S2 397B 注入客户端，因此没有执行真实模型测试。
配置继续保持：

```text
candidate-unvalidated
```

这是有意保留的真实状态，不应仅凭离线 Stub 测试改为 `validated`。正式冻结前仍需在
目标 Docker/官方注入客户端环境完成：

1. `intern-s2-preview-397b` 精确模型的单题调用；
2. `LOCAL_MAX_CONCURRENCY=1` 下的本地/容器运行；
3. 多题并发、尾调用阈值和 15 分钟总时限验证；
4. 输出质量、Candidate Schema、Trace 和最终答案人工抽查；
5. 冻结 benchmark evidence 与人工内容审查签名。

`validate_submission.py` 当前只为以上两项未冻结事实给出警告，不会将其伪装成失败或
已完成。代码整改与离线工程验收已经通过，真实模型质量验收仍是独立的外部步骤。

## 五、提交状态

本阶段未自动创建 Git commit，也未推送远端。原因是当前工作树在本轮开始前已经包含
Phase 6 的未提交改动；在没有用户明确授权整理提交边界前，不把既有改动混入新的阶段
提交。
