# Math-Agent Phase 10 Production Preflight / Release Governance 执行报告

## 1. 结论

Phase 10 不只是增加一次模型探活。本阶段完成两个相互独立的控制面：

1. 运行前的六层 Production Preflight；
2. 发布前不可绕过的 Strict Release Governance。

普通开发提交仍由 `validate_submission` 校验；只有证据、人工复核和冻结状态
全部满足后，`validate_release --strict` 才能通过。

## 2. Production Preflight L0-L5

| Level | 检查对象 | 失败含义 |
|---|---|---|
| L0 | exact model identity + injected client | 客户端或模型身份不可用 |
| L1 | exact raw JSON | 基础传输可用但 JSON 契约不可用 |
| L2 | model-owned AgentTurn | Agent 协议 envelope 不可用或越权生成 Host ID |
| L3 | RouterPlanner authoritative outcome | Router 语义失败或退化到 rule fallback |
| L4 | PrimarySolver Candidate | Candidate parser/schema/必要数学字段失败 |
| L5 | optional Verifier | 验证组件无法产生 Claim/obligation 映射 Finding |

L0-L4 是完整主链。L5 可按部署配置显式标为 `skipped`，但不能省略记录，也
不能把前五层失败隐藏为“总体可用”。完整竞赛配置启用 Verifier，因此正式
批量运行默认执行 L5。

每层记录：

```text
level / status / safe error_code / elapsed_seconds
max_tokens / observable transport_attempts
```

报告不保留原始异常、Provider 私密详情或模型私有推理。

## 3. Submission 与 Release 分离

### 3.1 Development / package gate

```text
python scripts/validate_submission.py
```

该命令检查 immutable baseline、公开接口、secret/path policy、内容工程审查、
证据注册表和 release manifest 指纹。它允许真实的
`candidate-unvalidated` 状态。

### 3.2 Strict release gate

```text
python scripts/validate_release.py --strict --results-root <evidence-root>
```

严格发布必须同时满足：

1. evidence registry 有且只有一个 active baseline；
2. active baseline 的目录、文件数和 tree SHA256 可复验；
3. baseline commit 是 release commit 的祖先，且 config hash 与冻结配置一致；
4. Git worktree clean；
5. compileall、全量 pytest 和所有治理命令通过；
6. test attestation 状态为 passed 且绑定 release source fingerprint；
7. content manifest 有完整 human signatures；
8. Prompt/Skill tree hash 与 release manifest 一致；
9. Competition config hash 一致且 status=`frozen`。

任何一项缺失都返回非零状态。`validate_submission` 成功不能替代 strict
release 成功。

## 4. 当前严格发布状态

Phase 10 完成时，以下条件仍有意保持未满足：

```text
active baseline: missing
benchmark evidence tree: unavailable
human review: pending
test attestation: pending-phase11
competition status: candidate-unvalidated
```

因此当前 `validate_release --strict` 必须失败。这是正确的工程结果，不是
Phase 10 实现失败。Phase 11 负责 C0-C7 + FULL 证据；Phase 12 才能在证据
支持下完成人工签名、test attestation 和 Competition Freeze。

## 5. 验收与回归

新增测试覆盖：

- L1-L5 各层失败的精确归因；
- L5 disabled 的显式 skipped 语义；
- 完整六层成功路径与 L4 schema retry；
- strict release 十二个条件的逐项 fail-closed；
- 当前 candidate 状态不能被误发布；
- release manifest 指纹纳入 submission/build provenance。

提交前执行仓库要求的完整门禁，并保持 `main.py`、`llm_client.py` 不变。
