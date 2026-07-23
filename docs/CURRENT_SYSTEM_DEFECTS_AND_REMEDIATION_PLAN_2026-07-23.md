# MathForge-Harness 当前系统缺陷汇总与修复实施计划

日期：2026-07-23
状态：`engineering-review / implementation-baseline`
仓库：`zw20031106/Math-Agent`
当前提交：`0fd50da`
输入基线：`MathForge-Harness_系统缺陷总结与修订实施计划.md`

## 1. 执行结论

当前项目已经不是只有设计骨架的早期版本。R0–R6 已经实现并测试了基线冻结、公开入口、线程隔离、Prompt Contract、候选编排、Evidence Ledger、证明义务、Repair、CEPC、Deadline、RAG 和可选 MCP 等主体模块。

但是，项目目前仍不能标记为：

- 数学正确性闭环完成；
- `competition-grade`；
- 最终竞赛配置已冻结；
- Benchmark 指标可信且足以支持消融决策。

阻断结论来自可复现的生产链路反例，而不是仅根据“尚缺功能”作出的推测：

1. 模型可以把任意数学断言标记为 `latex_syntax_check`，系统随后把“括号平衡”提升为“数学主张已验证”；
2. 上述错误证据可以满足 definition、sufficiency、uniqueness、boundary 等全部证明义务，使空断言证明通过完成门；
3. `LLMFinalizer` 只保护最终答案字符串，不保护推导内容，可在答案不变时注入明显错误论述并被接受；
4. `DeterministicFormatter` 用子串判断答案是否已出现，答案 `2` 会被错误地认为已包含在结论 `42` 中；
5. Trace 会删除键名含 `token` 的字段，因此 Benchmark 的 `average_estimated_tokens` 实际恒为 0；
6. `config/competition.json` 只被 Benchmark 脚本加载，公开提交入口 `ReasoningAgent` 并不读取它，最终运行配置与消融配置可能漂移；
7. Runtime 仍没有原缺陷文档要求的正式状态机，多个 Feature Flag 组合也没有依赖校验；
8. 工具调用数量、Claim 数量和工具耗时不受统一 Deadline/预算约束，模型输出可放大为长时间串行子进程调用。

因此，原计划中的“R7 真实消融与配置冻结”必须后移。先修复 P0/P1 正确性和评测可信度问题，再运行真实消融，否则得到的配置结论不可信。

## 2. 审查范围与验证

### 2.1 已审查范围

- 官方不可变入口：`main.py`、`llm_client.py`；
- 公开接口：`user_agent.py`；
- 生产主链路：`mathforge/runtime.py`；
- 配置、Feature Flags、预算、Deadline、并发和 Trace；
- Router、Primary、Alternative、Verifier、Lemma、Repair、Finalizer；
- Problem/Solution Parser 和输出格式化；
- Tool Registry、Direct Worker、StdIO MCP、Evidence Ledger；
- Proof Obligations、Completion Gate、Arbitration；
- Session Memory、Blackboard、CEPC 和角色视图；
- 离线 RAG、知识卡构建与审核元数据；
- Benchmark、Scorer、消融配置和提交校验；
- 全部 124 项现有测试；
- 用户提供的 D01–D30 缺陷总结及 R00–R15 实施建议；
- 仓库已有 R0–R6 实施状态报告和 2026-07-22 深度审查报告。

### 2.2 已执行门禁

```text
python -m compileall .
PASS

pytest -q
124 passed

python scripts/verify_baseline_files.py
Official immutable baseline files verified.

python scripts/validate_submission.py
Submission validation passed.

python -m pip check
No broken requirements found.

git diff --check
PASS
```

当前环境未安装 Ruff、Mypy 和 Coverage。因此，本次结论不包含正式 lint、静态类型和行/分支覆盖率数据；这本身应作为开发门禁缺口补入后续计划。

### 2.3 不能由现有测试证明的事项

`124 passed` 证明现有测试断言成立，但不能证明：

- 工具证据与数学 Claim 的语义能力匹配；
- Finalizer 没有改变已验证推导；
- 所有 Feature Flag 组合都合法；
- Token、CEPC、timeout 和并发污染指标真实有效；
- 中文题目的 RAG 能命中英文知识卡；
- 默认 4 次模型调用足以让 Repair、Verifier、Lemma 和 Finalizer 都按设计生效；
- 官方模型上的准确率、P50/P95、成本和故障率达标。

## 3. 已确认可保留的实现

以下能力已经形成真实代码和自动化测试，应保留并加防回归测试：

1. `main.py`、`llm_client.py` 的 byte-for-byte 基线冻结；
2. `ReasoningAgent.solve(problem, metadata)` 的公开返回契约；
3. 每题独立 `MathSession`、`SessionMemory` 和 `LemmaMemory`；
4. 共享官方客户端的 `BoundedSemaphore` 并发限制；
5. 只使用注入的 `client.chat(...)`，没有另建在线模型客户端；
6. Prompt Contract 已驱动 Router、Primary、Alternative、Verifier、Repair 和 Finalizer；
7. Alternative 初始调用看不到 Primary 的完整推导；
8. 确定性 CEPC 压缩、硬不变量校验和显式预算失败；
9. Evidence invocation 保存工具、版本、参数、假设、定义域和稳定摘要；
10. Repair 的版本化、局部合并、回滚和部分重验证门；
11. Lexicographic Arbitration 已优先于 soft score；
12. RAG 已保留 BM25/trust/condition 分数并显式关闭连接；
13. 知识卡已有版本、审核者、日期和内容哈希门禁；
14. Direct/MCP 工具结果一致性已有测试，MCP 默认关闭；
15. 模型慢调用在 Harness 返回后不会继续改写已返回的 Session/Trace；
16. judge trace 有 allowlist、路径/敏感字段清洗和总量限制。

保留这些能力不等于它们已经达到最终质量；后续修改必须避免退化。

## 4. 原 D01–D30 缺陷的当前状态映射

状态定义：

- `已解决`：核心验收条件已满足，后续只需防回归；
- `大部分解决`：主链路已接通，仍有明确边界问题；
- `部分解决`：存在代码，但契约或运行语义尚未闭环；
- `未解决`：关键验收条件仍不成立。

| 原 ID | 当前状态 | 当前证据与剩余问题 |
|---|---|---|
| D01 Prompt 子系统不完整 | 部分解决 | `PromptContractLoader.messages()` 已进入六个生产角色，但只有单一 `contract.md`；缺正式 output schema、renderer/validator/version registry、配置哈希和变量完整性验证；LemmaCurator Contract 未进入模型调用。 |
| D02 Runtime 缺少统一状态机 | 未解决 | `MathSession` 没有 `RuntimePhase`、`transition(expected, target)` 或合法转换表；`runtime.py` 依赖长函数中的隐式顺序和异常跳转。 |
| D03 缺少 Feature Flags | 部分解决 | 已有平铺布尔开关和 A0–A9，但没有 safe/balanced/full 配置层、依赖校验、配置哈希和公开入口绑定；被禁用组件仍会初始化。 |
| D04 角色名称和执行图不一致 | 部分解决 | 七个名称已冻结；LemmaCurator 仍是确定性 Claim 抽取器，`prompts/lemma_curator/contract.md` 未参与生产调用。 |
| D05 Agent 与确定性服务边界不清 | 部分解决 | 服务边界已基本形成，但模型控制 `role`、`answer_type`、`check_type` 等宿主契约字段，导致模型能影响确定性验证语义。 |
| D06 跨模块 Schema Contract 未冻结 | 未解决 | 核心 dataclass 只有 `to_dict()`；缺 `from_dict()`、`validate()`、`schema_version` 和 Enum；Solution Parser 对错误字段类型会逐字符转换。 |
| D07 缺少 Contract Tests | 部分解决 | 已有若干运行时集成测试，但没有系统化的 Router→Context→Prompt→Parser→Verifier→Arbiter→Formatter 契约套件，也没有 Feature 组合测试。 |
| D08 缺少低/中/高风险 E2E | 部分解决 | Proof、deadline、repair、role context 有局部 E2E；缺真实黄金答案和低/中/高三条完整业务路径、故障矩阵及输出正确性断言。 |
| D09 Router 职责过重 | 未解决 | 多领域同分时 auxiliary 仍不可达；`subject_candidates` 未填充；风险只看证明标记和关键词置信度；LLM 修改 risk 后不会同步 rounds/lemma/RAG。 |
| D10 Prompt/Skill/RAG/Memory 边界不清 | 部分解决 | 模块目录已分开，但 RAG 被直接拼接到 `skill_context`；raw problem 通过 Blackboard 再次进入角色视图；元数据没有注入白名单。 |
| D11 候选评分权重未经验证 | 大部分解决 | 已改为 lexicographic；但 `answer_consistency` 只检查非空，方法签名仍可被模型文本规避，表达式等价忽略题目假设。 |
| D12 Verifier 退化为纯 LLM 判断 | 部分解决 | 有 deterministic tools 和 soft Skeptic；但工具能力未绑定 Claim 语义，反而可产生伪 hard verification；Skeptic soft pass 仍能单独完成义务。 |
| D13 缺领域—主张—工具—证据矩阵 | 未解决 | `ToolDefinition.proves/limitations` 只是说明文字，`ClaimEvidenceVerifier` 不执行能力匹配、路由白名单或主张类型校验。 |
| D14 工具初始范围过大 | 未解决 | 九个工具中多个未接生产 Claim 参数映射；Claim/tool 调用数无统一上限；隔离工具逐 Claim 启动子进程。 |
| D15 缺 Round Protocol | 部分解决 | 已有两轮、progress 和 stop reason；但第二轮 Primary 可看到完整历史候选，扩展候选不再经过 batch Skeptic，调用预算也常与 Verifier/Finalizer冲突。 |
| D16 Memory 物理实现过重 | 大部分解决 | 已收敛为题内 Session/Lemma Memory；但 RawContextStore 每次 view 临时创建、引用不可再解析，memory 内容仍会重复原题。 |
| D17 CEPC 可能误用 LLM 摘要 | 大部分解决 | 当前是确定性压缩且有硬预算；但历史候选泄漏、candidate claim ID 冲突和不可用 raw reference 仍需修复。 |
| D18 Raw Context 缺容量管理 | 部分解决 | 有 view 字符预算；没有 per-session raw/tool/evidence 总预算，metadata、Claim 数、Evidence 数和工具参数没有完整上限。 |
| D19 RAG 治理不足 | 部分解决 | 已有来源/审核/哈希；当前只有内部 reviewed 卡，中文查询与英文卡基本无法匹配，数据库重建不是原子替换。 |
| D20 MCP 默认策略未冻结 | 已解决 | Direct 默认、StdIO MCP 可选、失败回退 Direct、无 HTTP MCP；继续默认关闭即可。 |
| D21 Trace 边界不明确 | 部分解决 | allowlist 和清洗存在；Token 成本被误删、终态事件不保留槽位、异常原因全部折叠为 `primary_unavailable`，internal trace 无持久 debug sink。 |
| D22 Finalizer 可能改坏答案 | 未解决 | 精确答案字符串有回滚，但推导文本没有再验证；已复现保持答案不变却注入错误论述并被接受。 |
| D23 Budget 缺统一 Deadline | 部分解决 | 模型调用有共享 Deadline；工具、RAG、压缩、解析和 Claim 循环不共享硬截止；启动模型调用也不考虑官方客户端最坏重试时长。 |
| D24 共享实例锁策略未冻结 | 已解决 | Session 题内隔离、共享模型 Gate、有慢调用回写隔离测试；继续保留并做长时压力验证。 |
| D25 依赖和离线可用性不足 | 部分解决 | 正式/开发依赖已分离且 `pip check` 通过；版本只限定大版本范围，`pyproject.toml` 缺 project/dependencies 元数据和 lock/constraints。 |
| D26 Prompt/Skill/RAG 缺版本化 | 部分解决 | 文件中有 version/source_version/tool_version；每次运行没有统一记录 prompt/skill/config/DB/model/code 指纹。 |
| D27 缺组件降级矩阵 | 部分解决 | 多处有局部 fallback；RAG 错误静默成空结果，非法 Flag 组合不拒绝，所有顶层异常都变成同一种 fallback。 |
| D28 Codex 计划缺架构守卫 | 部分解决 | `AGENTS.md` 和测试已有部分守卫；状态机、Schema、工具能力、配置绑定和阶段级 Definition of Done 仍缺。 |
| D29 完整代码与比赛配置未区分 | 未解决 | `competition.json` 标记 candidate-unvalidated 是正确的，但公开入口不用该文件且默认几乎全开；实验配置无法保证就是提交配置。 |
| D30 缺数学内容人工审核门 | 未解决 | 只有 8 张 RAG 卡有清单；18 个领域 Skill、7 个 Prompt、Proof Obligation 模板、工具能力边界和 E2E 数学样例没有签署式人工审核。 |

## 5. 当前缺陷总表

### 5.1 优先级定义

| 优先级 | 定义 |
|---|---|
| P0 阻断 | 能输出错误证明/错误论述，或使评测与配置结论失真；修复前不得做最终消融。 |
| P1 高 | 会破坏契约、预算、隔离、阶段可达性或重要结果质量；应在真实消融前完成。 |
| P2 中 | 影响可维护性、复现性、降级质量或可选模块有效性。 |
| P3 低/延后 | 默认关闭或不影响主链路，可在证据证明有价值后处理。 |

### 5.2 汇总

| 当前 ID | 优先级 | 问题 | 主要影响 |
|---|---:|---|---|
| C01 | P0 | 工具能力没有绑定 Claim 语义 | 格式检查、可解析性可被提升为数学真值。 |
| C02 | P0 | ProofCompletionGate 可接收被错误提升的 verified Claim | 空断言证明可通过 definition/sufficiency/uniqueness/boundary 全部义务。 |
| C03 | P0 | Finalizer 只保护答案，不保护已验证推导 | 正确答案可搭配错误解释输出。 |
| C04 | P0 | Formatter 使用答案子串判断 | 精确答案可能不出现在最终输出的明确答案位。 |
| C05 | P0 | 提交入口不绑定 competition 配置 | 消融、文档和真实提交可能运行不同 Feature 集。 |
| C06 | P0 | Trace 清洗删除 `estimated_tokens` | Token 成本指标恒为 0，消融成本结论失真。 |
| C07 | P0 | Benchmark 的 CEPC/timeout 指标定义错误或无事件来源 | 稳定性与故障指标会给出虚假的 0 或错误归因。 |
| C08 | P1 | Solution Schema 宽松，宿主字段由模型覆盖 | 字符串被逐字符解析；role/answer_type/method/check_type 可污染决策。 |
| C09 | P1 | Runtime 没有显式状态机 | 阶段越级、Repair/Verifier/Lemma 后重验依赖隐式控制流。 |
| C10 | P1 | Feature Config 无类型、范围、依赖和未知键校验 | `"false"` 可成为 truthy；拼写错误被静默忽略；非法组合可运行。 |
| C11 | P1 | Router auxiliary 不可达、风险特征过浅 | 多领域复杂题被当作 low，仅运行单候选。 |
| C12 | P1 | LLM Router 的 risk 与 rounds/RAG/lemma 不同步 | RoutePlan 内部自相矛盾。 |
| C13 | P1 | Claim/tool 数和工具总耗时无预算 | 模型输出可放大为大量串行子进程并越过硬截止。 |
| C14 | P1 | 阶段调用预算互相争抢 | 默认 4 calls 下 Verifier、Repair、Lemma、Finalizer 经常不可同时到达。 |
| C15 | P1 | Lemma Round Primary 可见完整历史候选 | 与“只注入 verified lemmas、隐藏完整失败候选”的设计冲突。 |
| C16 | P1 | Lemma 扩展候选不再经过 batch Skeptic | 高层推理 Claim 往往无法完成证明义务。 |
| C17 | P1 | ClaimGraph 无重复 ID、未知依赖、环检测和候选命名空间 | 多候选图覆盖；Repair 可引入悬空依赖。 |
| C18 | P1 | 表达式答案等价不携带题目假设和定义域 | 正确等价候选可能无法聚类，仲裁一致性失真。 |
| C19 | P1 | Method Contract 只有提示和标签，没有确定性约束 | 模型可用不同字符串伪装相同方法，独立一致性仍不可靠。 |
| C20 | P1 | Trace 不保证终态事件，顶层异常不可诊断 | 成本可能缺失，所有失败都变成同一原因。 |
| C21 | P1 | Benchmark 不保存每题 Trace/成本，污染检查只核验回显指纹 | 结果难以复核，也不能证明答案未串题。 |
| C22 | P1 | 缺 adversarial Contract/E2E 测试与类型/覆盖率门禁 | 现有 124 项测试未覆盖已复现的关键反例。 |
| C23 | P2 | RawContextStore 引用生命周期无效，metadata 注入无白名单 | 上下文重复、不可追溯，非必要元数据进入模型。 |
| C24 | P2 | RAG 对中文题和英文卡缺跨语言匹配，构建非原子 | 默认开启但实际收益可疑；失败可能损坏已有 DB。 |
| C25 | P2 | Prompt/Skill/RAG/Config 缺统一运行指纹和人工审核 | 实验不可完整复现，数学内容错误可能固化。 |
| C26 | P3 | StdIO MCP 每次调用启动新进程 | 性能成本高；默认关闭时不阻断主链路。 |

## 6. 阻断级缺陷详解与验收

### C01/C02：证据能力提升漏洞

#### 证据链

- `mathforge/harness/schemas.py:40-46`：`Claim.check_type` 是自由字符串；
- `mathforge/parsing/solution_parser.py:81-87`：模型输出直接写入 `check_type`；
- `mathforge/verification/evidence.py:109-138`：验证器按该字符串执行工具，任一 hard pass 都把 Claim 标为 `verified`；
- `mathforge/tools/registry.py:52-68`：工具已经声明 `proves` 和 `limitations`，但生产验证器未读取；
- `mathforge/tools/formatting.py:8-10`：`latex_syntax_check` 只检查括号平衡，却返回 hard pass；
- `mathforge/verification/proof_obligations.py:53-60`：义务按 kind 的字符串包含关系映射到 Claim，verified Claim 直接满足义务；
- `mathforge/verification/completion.py:69-89`：verified Claim 可通过完成门。

#### 已复现反例

题目：

```text
Prove that the solution is unique.
```

模型只返回四条空断言：

```text
definition is handled
sufficiency is handled
uniqueness is handled
boundary is handled
```

四条 Claim 的 `check_type` 均设为 `latex_syntax_check`。结果：

```text
四条 Claim status = verified
四个 required obligations = satisfied
ProofCompletionGate = complete
最终输出 = Unsupported assertions only. / Final answer: QED
fallback = false
```

#### 根因

Evidence 的“强度”与“证明能力”被混为一谈。hard 只能表示工具执行结果确定，不表示该工具证明了整个数学主张。

#### 修复

1. 增加不可由模型控制的 `ClaimKind` 和 `VerificationCapability`；
2. 建立强制能力矩阵，例如：

   ```text
   latex_syntax_check -> syntax.brace_balance
   safe_parse_expression -> syntax.restricted_parse
   matrix_shape_check -> matrix.shape
   answer_type_check -> answer.shape
   symbolic_equivalence -> equality.symbolic_under_domain
   ```

3. `ClaimEvidenceVerifier` 只接受宿主根据 Claim IR 推导出的 tool request；
4. 模型返回的 `check_type` 只能作为建议，不得直接决定执行和 status；
5. Claim 状态拆分为：

   ```text
   syntax_checked
   numerically_supported
   semantically_verified
   rejected
   unknown
   ```

6. Completion Gate 只接收与 obligation kind 匹配的 semantic capability；
7. 删除按 `obligation.kind in claim.statement.lower()` 的自由文本完成逻辑，改为显式 `obligation_ids`/`claim_kind` 映射；
8. LemmaVerifier 使用同一能力矩阵，不能继承弱检查的 `verified`。

#### 验收

- `latex_syntax_check`、`safe_parse_expression`、`answer_type_check` 永远不能完成数学证明义务；
- 模型伪造/未知 `check_type` 只产生 `unknown`；
- 每个 satisfied obligation 能反查到匹配 capability、Claim、Evidence 和 invocation；
- 上述四句空断言 E2E 必须 fallback；
- 旧的合法 symbolic equivalence、matrix shape、answer shape 测试仍通过，但只更新各自能力范围内的状态。

### C03：Finalizer 可注入错误推导

#### 证据链

- `mathforge/agents/finalizer.py:72-84`：只比较 `finalized.final_answer` 和原答案；
- Finalizer 新生成的 `solution_text` 不经过 Claim Parser、Evidence、ProofCompletionGate 或差异检查；
- Prompt 的“不要新增结论”只是软指令。

#### 已复现反例

原候选：

```text
Because one plus one equals two.
Final answer: 2
```

Finalizer 返回：

```text
False claim: one plus one equals three, but we print two.
Final answer: 2
```

系统结果：

```text
finalization_completed.used_llm = true
reason = accepted
```

#### 修复

优先采用最简单的安全方案：

1. 比赛默认关闭 LLM Finalizer；
2. `DeterministicFormatter` 成为唯一提交输出器；
3. 若后续消融证明 Finalizer 有价值，只允许它输出受限的段落重排/措辞 patch，不允许返回新的 CandidateSolution；
4. 对 patch 做句子/Claim 对齐，禁止新增数学实体、数字、公式、假设、结论和引用；
5. patch 后重新执行 AnswerValidator 和 ProofCompletionGate，任何不确定性都回滚。

#### 验收

- 保持 final answer 不变但更改任一数学 Claim 的输出必须回滚；
- 新增数字、公式、假设或定理名必须回滚；
- 默认 competition 配置中 `enable_finalizer=false`，直到独立消融证明收益。

### C04：Formatter 子串误判

#### 证据

`mathforge/output/deterministic_formatter.py:15-16` 使用：

```python
if answer and answer not in solution:
```

答案 `2` 是错误结论 `42` 的子串，因此不会追加明确的 `Final answer: 2`。

#### 修复

- 不做子串推断；
- 除 raw-text proof 的明确策略外，始终在末尾输出一个规范化、唯一的最终答案块；
- 若 solution 已有答案块，解析并严格等价比较后替换，而不是跳过。

#### 验收

- `answer=2, solution=...42` 最后必须出现独立 `Final answer: 2`；
- 只允许一个最终答案块；
- choice/fraction/set/interval/matrix 的答案块均保持原始精确表示。

### C05/C10：配置没有成为提交契约

#### 证据

- `scripts/run_benchmark.py:43-44` 显式加载 JSON 配置；
- `user_agent.py:5-7` 删除所有 `args/kwargs`，直接 `MathForgeHarness(client)`；
- `MathForgeHarness` 因此只使用 dataclass 默认值和两个环境变量；
- `HarnessConfig.from_json()` 静默忽略未知键且不校验类型、范围和 Feature 依赖。

#### 修复

1. 建立单一 `config/competition.json` 加载入口；
2. `ReasoningAgent` 默认从仓库内只读 competition 配置构造 Harness；
3. 测试可显式注入 `HarnessConfig`，生产入口不接受不可信外部路径；
4. 未知键、错误类型和越界值立即失败；
5. 增加依赖规则：

   ```text
   verifier -> evidence + proof_obligations
   repair -> evidence + tools
   lemma_loop -> memory + proof_obligations
   rag -> skills 或独立 knowledge context
   use_mcp -> tools
   finalizer -> deterministic formatter + post validator
   ```

6. Trace 记录配置 schema version 和 hash；
7. 配置状态为 `candidate-unvalidated` 时，提交校验必须显式报警，不能误称 frozen。

#### 验收

- Benchmark 与 `ReasoningAgent` 对同一配置文件生成相同 hash；
- 未知键和 `"false"` 字符串被拒绝；
- 任一非法依赖组合被拒绝；
- 修改 competition 配置能确定性改变公开入口行为；
- safe/balanced/competition 三种命名配置有明确继承关系或完整展开值。

### C06/C07：Benchmark 指标不可信

#### Token 指标

`mathforge/harness/trace.py:10` 把所有包含 `token` 的键视为敏感字段。`estimated_tokens` 因此从 `primary_completed` 和 `budget_summary` 被删除。`mathforge/benchmark.py:244-245` 再从已清洗 Trace 读取该字段，结果为 0。

#### CEPC 指标

`mathforge/benchmark.py:174-181` 统计 `compression_validated`，但生产 Runtime 从未发送该事件。实际失败事件是 `context_budget_infeasible`。

#### timeout 指标

`mathforge/benchmark.py:164-167` 把全部 `status == unknown` 计为 timeout；symbolic context 不完整、无有限样本等语义 unknown 也会被误计。

#### 修复

1. 敏感键规则改成精确匹配 secret/API credential，而不是包含 `token`；
2. 成本不从 judge trace 反推；返回/内部记录独立的结构化 `RunMetrics`；
3. Trace 为 `session_started`、`budget_summary`、`fallback_used` 保留不可被挤出的终态槽位；
4. CEPC 指标直接统计 `context_view_built` 和 `context_budget_infeasible`；
5. Tool check 增加 `outcome_reason=timeout|parse_unknown|domain_unknown|error|pass|fail`；
6. Benchmark 每题保存 cost、trace 摘要、配置 hash、prompt/skill/DB 指纹；
7. 增加指标自一致性测试：summary 必须等于 records 的可重算结果。

#### 验收

- 非零模型输出产生非零 estimated token；
- 人工制造 context budget failure 后 CEPC failure rate 非零；
- domain unknown 不计入 timeout；
- Trace 达到大小/事件上限时仍保留 budget summary 和 fallback；
- Benchmark 产物可离线重算所有汇总指标。

## 7. 高优先级缺陷解决方案

### C08：Schema 和宿主字段所有权

问题：

- `depends_on="base"` 被解析为 `["b","a","s","e"]`；
- `assumptions="x>0"` 被解析为 `["x",">","0"]`；
- 模型可覆盖 `role` 和 `answer_type`；
- Claim 数、文本长度、ID 唯一性和依赖关系没有统一校验。

方案：

1. 为所有跨模块对象定义版本化 Schema；
2. 宿主强制写入 `candidate_id`、`role`、`answer_type`、`planned_method_family` 和 version；
3. 模型只能填写允许字段；
4. 每字段做严格类型校验和有界局部降级；
5. 对 claims 设数量、单项长度和总长度上限；
6. Claim ID 必须唯一，依赖必须存在且图必须无环；
7. Parser 输出后统一 `validate()`，不允许松散 dict 进入 Runtime。

验收：

- 字符串列表字段不再逐字符转换；
- 错误 role/answer_type 被覆盖为宿主值并记录 contract deviation；
- 重复 Claim ID、悬空依赖和环被拒绝；
- Parser fuzz/property tests 不抛出未分类异常。

### C09：Runtime 状态机

建议阶段：

```text
CREATED
-> PARSED
-> ROUTED
-> CONTEXT_READY
-> CANDIDATES_READY
-> EVIDENCE_READY
-> OBLIGATIONS_READY
-> VERIFIED
-> LEMMA_EXPANDED?
-> REVERIFIED
-> ARBITRATED
-> FORMATTED
-> FINALIZED
-> COMPLETED

任意阶段 -> FAILED -> FALLBACK_COMPLETED
```

要求：

- 只有 `session.transition(expected, target)` 可改变阶段；
- Repair、Lemma expansion 后必须回到 EVIDENCE/VERIFIED；
- Finalizer 回滚也必须有明确状态；
- Feature 关闭时有合法 skip transition；
- Trace 只记录公共 phase 和原因，不暴露私有推理。

### C11/C12：Router 和风险校准

问题：

- 任何单关键词命中至少 0.80，auxiliary 条件却要求 top score `<0.75`；
- `probability + random + matrix + eigenvalue` 得到 linear-algebra/probability 同为 0.88，却仍是 low、无 auxiliary；
- LLM 把 risk 改为 high 时，`max_reasoning_rounds` 仍可为 1、`use_lemma_loop` 仍为 false。

方案：

1. 分离 confidence、ambiguity margin 和 complexity；
2. top1/top2 接近时无论 top1 是否高都允许 auxiliary；
3. 填充并持久化 `ProblemIR.subject_candidates`；
4. 用一个纯函数从最终 risk 重算所有派生字段；
5. 风险特征至少覆盖：题长、条件数、符号数、分段/绝对值、定理交换、存在唯一、病态数值、混合领域、证明深度；
6. 建立带人工标签的小型路由校准集。

### C13/C14：统一资源计划

方案：

1. 增加 per-session：

   ```text
   max_claims
   max_tool_calls
   max_isolated_tool_calls
   max_tool_seconds
   max_evidence_records
   max_prompt_chars_total
   ```

2. 每次工具/RAG/压缩/Parser 重计算前检查共享 Deadline；
3. 工具 timeout 使用 `min(tool_default, deadline.remaining_for_stage)`；
4. 模型调用启动阈值考虑官方客户端单次最坏重试时间或阶段保留；
5. 在路由后生成显式 `CallAllocationPlan`：

   ```text
   router
   primary
   alternatives
   verifier
   repair reserve
   lemma reserve
   finalizer reserve
   ```

6. 必选阶段优先，不能由较早的可选 Repair 抢走 Verifier 配额；
7. Feature 开启但预算必然不可达时，配置校验直接拒绝或 Trace 明确 `unreachable_by_budget`。

### C15/C16：Lemma 闭环

方案：

- 第二轮 Solver 只接收 verified LemmaCard、原题和必要 conditions，不接收历史 `solution_text`；
- Primary/Alternative 历史候选统一使用结构化摘要视图；
- Lemma ID 和依赖使用候选命名空间；
- expanded candidate 必须重新执行：

  ```text
  schema validation
  answer validation
  claim evidence
  proof obligations
  VerifierSkeptic（需要时）
  completion gate
  arbitration
  ```

- LemmaCurator 是否必须是 LLM 角色需做架构决策：若保留确定性抽取，应修改角色定义和文档，不能继续声称其 Prompt Contract 驱动生产调用。

### C17：ClaimGraph 和 Repair 完整性

方案：

- 图键改为 `(candidate_id, claim_id)` 或稳定 namespaced ID；
- 建图时校验重复、悬空、自依赖和环；
- Repair patch 不允许新增未声明依赖；
- 依赖变更后重新计算影响闭包，而不是只使用原图闭包；
- Repair 接受前验证新的 ClaimGraph、obligations 和 final answer dependency；
- 回滚的 proposed evidence 标记为 rejected transaction，不与 active evidence 混淆。

### C18：假设感知的答案等价

方案：

- `equivalent_answers()` 接收 ProblemIR assumptions/domains；
- answer type 使用宿主 ProblemIR，而不是候选自报字段；
- interval、set、piecewise、radical 等高风险表达式在假设不完整时返回 unknown，不伪造 hard disagreement；
- Arbitration 把 unknown agreement 与 confirmed disagreement 分开。

### C19：方法独立性

方案：

- `method` 不再由自由文本单独定义签名；
- Router 输出受控 `MethodFamily` Enum；
- Solver 返回结构化 method steps，由宿主分类器/规则提取实际签名；
- contract deviation 候选不获得 independent agreement；
- 两个不同字符串但同构 Claim topology/定理/步骤的候选视为重复；
- 在真实数据上校准重复检测，避免把真正不同方法误合并。

### C20/C21：可诊断性与 Benchmark

方案：

- 顶层异常映射为安全错误码：parse、context、budget、tool、proof_incomplete、all_candidates_failed、config；
- judge trace 不含原始异常，但本地可选 debug sink 保存脱敏 stack 和 internal events；
- Benchmark 保存每题结构化 RunMetrics，不依赖被截断的 judge trace；
- 污染测试除 session/fingerprint 外，再检查：
  - 每题 nonce 是否进入捕获的模型 messages；
  - 输出/Trace 是否包含其他题 nonce；
  - 慢调用返回后结果对象是否不变；
  - 并发下模型调用和候选归属是否一致；
- 提供重复次数、随机种子、bootstrap/Wilson 置信区间和配对显著性分析。

### C22：测试门禁

必须新增以下反例：

1. syntax evidence 不能完成数学 obligation；
2. Finalizer 同答案错误推导必须回滚；
3. Formatter 的 `2`/`42` 子串反例；
4. Router 同分多领域和 risk 派生字段一致性；
5. malformed list 字段、重复 Claim ID、悬空依赖、依赖环；
6. competition config 与公开入口 hash 一致；
7. Trace Token 指标非零；
8. CEPC failure/timeout reason 指标可触发；
9. 工具/Claim 数量和 Deadline 压力；
10. Lemma 第二轮不可见完整历史候选；
11. expanded candidate 必须重新 Skeptic/Completion；
12. Repair 改依赖后重新计算闭包；
13. assumptions-aware answer equivalence；
14. 低、中、高风险三条黄金 E2E；
15. 8/16 并发长时故障注入；
16. Prompt/Schema fuzz 和 property tests。

提交门禁升级为：

```text
python -m compileall .
ruff check .
mypy mathforge user_agent.py
pytest -q
pytest --cov=mathforge --cov-branch --cov-report=term-missing
python scripts/verify_baseline_files.py
python scripts/validate_submission.py
git diff --check
```

覆盖率目标不能替代关键路径断言；对 Runtime、Completion、Evidence、Config 和 Formatter 设置分支覆盖门槛。

## 8. 中低优先级缺陷

### C23：Context 与 Metadata

- 每个 RoleContextFactory 调用都创建临时 RawContextStore，`raw_context_ref` 随后无法 resolve；
- 原题通过显式 Problem 和 Blackboard raw memory 重复进入上下文；
- metadata 整体写入 raw memory，没有角色级白名单；
- Primary 的 lemma round view 当前包含历史候选完整 solution。

处理：

- Session 持有唯一有总容量上限的 RawContextStore；
- Prompt 中原题只出现一次；
- metadata 只允许 `idx`、公开标签和 benchmark nonce 等白名单字段；
- 禁止 API key、路径、用户私有字段进入模型；
- 每个 role view 以真实发送的 `to_prompt_json()` 计算预算，而不是另一个序列化形态。

### C24：RAG

- 当前卡片正文为英文；中文连续文本在 `unicode61` 下无法可靠分词并与英文卡匹配；
- RAG 默认打开但没有真实收益证据；
- builder 先删除现有 DB，再原地重建，构建中途失败会丢失旧库；
- RAG 失败静默返回空列表，Trace 无失败原因。

处理：

- 在 R7 前默认关闭 RAG；
- 若保留，增加中英术语归一化、受控关键词映射或双语卡；
- 用临时数据库完整构建/校验后原子 replace；
- 区分 no-match、missing-db、fts-unavailable、query-error；
- 权威来源卡经双人审核后才能升级 verified。

### C25：版本与人工审核

每次运行至少记录：

```text
code_commit
config_schema_version + config_hash
prompt_versions + prompt_hashes
skill_versions + skill_hashes
rag_schema_version + knowledge_db_hash
tool_versions
model identifier（仅使用公开可获得字段）
```

需要人工签署：

- 18 个领域 Skill；
- 6 个通用 Skill；
- 7 个 Prompt Contract；
- Proof Obligation 模板；
- 工具 capability/limitation；
- Router 校准集；
- 低/中/高风险黄金 E2E。

### C26：MCP

继续保持：

```text
Direct = default
StdIO MCP = disabled
HTTP MCP = forbidden
```

只有真实消融证明准确率、隔离性或维护价值优于 Direct 时，才考虑常驻进程和完整协议生命周期。当前不应为展示目的增加复杂度。

## 9. 修订后的实施顺序

现有 R0–R6 的提交历史保留。原 R7“真实消融”重新定义为最后阶段，新增以下整改阶段。

### S0：正确性止血（P0）

范围：

- C01/C02 Evidence capability 与 ProofCompletion；
- C03 Finalizer 默认关闭和安全回滚；
- C04 Formatter 唯一答案块；
- C06/C07 Token/CEPC/timeout 指标修复；
- 为所有已复现反例先写失败测试。

验收：

- 四句空断言证明必须 fallback；
- 错误 Finalizer 文本必须回滚；
- `2`/`42` 输出反例通过；
- Benchmark Token 非零且 CEPC/timeout 可正确触发；
- 全量旧测试通过。

建议工作量：3–5 个工程日。

### S1：Contract-first 与配置冻结

范围：

- C05/C08/C09/C10；
- 版本化 Schema、Enum、validate/from_dict；
- Runtime State Machine；
- public/benchmark 单一配置加载；
- Feature 依赖和范围校验；
- 配置/Prompt/Skill 指纹。

验收：

- 非法 Schema 和 Feature 组合在启动时失败；
- 所有阶段转换有测试；
- public 与 benchmark 配置 hash 一致；
- 无松散 dict 静默穿过模块边界。

建议工作量：4–6 个工程日。

### S2：Router 与资源控制

范围：

- C11/C12/C13/C14；
- Router 校准、派生字段纯函数；
- Claim/tool/context 总预算；
- Deadline 覆盖工具和本地重计算；
- CallAllocationPlan。

验收：

- 多领域同分题产生 auxiliary；
- high risk 的所有派生字段一致；
- 恶意大量 Claim 在固定时间和调用数内降级；
- 必选 Verifier 不被早期可选 Repair 抢占。

建议工作量：3–5 个工程日。

### S3：推理闭环与上下文隔离

范围：

- C15–C19、C23；
- namespaced ClaimGraph；
- Repair 依赖变更重算；
- lemma-only 第二轮 view；
- expanded candidate 全链路重验；
- assumptions-aware equivalence；
- 方法独立性结构化。

验收：

- 第二轮 messages 中不存在历史完整 solution；
- 悬空/循环依赖被拒绝；
- expanded proof 不经 Verifier/Completion 不能入仲裁；
- 定义域约束下的等价候选正确聚类。

建议工作量：5–8 个工程日。

### S4：可观测性与评测可信度

范围：

- C20/C21/C22；
- 结构化 RunMetrics；
- debug sink；
- Benchmark 记录与 summary 可重算；
- 重复实验、置信区间和真实污染检测；
- Ruff/Mypy/Coverage 门禁。

验收：

- 任一 summary 指标都能从 records 重算；
- Trace 截断不影响成本；
- 并发污染探针能检测实际消息/结果串题；
- 低/中/高风险黄金 E2E 和故障注入全部通过。

建议工作量：4–6 个工程日。

### S5：RAG、内容和依赖治理

范围：

- C24/C25/C26；
- RAG 原子构建、双语检索、失败原因；
- Prompt/Skill/Obligation/Capability 人工审核；
- 依赖 constraints/lock 和安装验证；
- 决定是否删除无收益 MCP/RAG/Finalizer。

验收：

- 中英文检索基准达标；
- 数据库中断构建不损坏旧库；
- 全部数学内容有 reviewer、date、version/hash；
- 干净环境可离线安装运行。

建议工作量：3–5 个工程日，不含数学专家审核时间。

### S6：真实重复消融与配置冻结（原 R7）

前置条件：

- S0–S5 完成；
- P0/P1 缺陷清零；
- Benchmark 自一致性通过；
- 有代表性的隐藏验证集和官方模型额度。

执行：

```text
A0 单模型
A1 + Router/Skills
A2 + Alternatives
A3 + Tools
A4 + Evidence
A5 + Proof/Verifier
A6 + Memory/CEPC
A7 + Lemma
A8 + RAG
A9 + Repair
A10 + Finalizer（仅在安全门完成后）
```

每个配置至少多次重复，并报告：

- 总体及分领域/题型准确率；
- 配对差值和置信区间；
- model calls、estimated tokens、P50/P95；
- fallback、JSON/Schema、context、tool timeout/error；
- proof incomplete、lemma、repair、RAG hit；
- 并发污染和返回后变异；
- 每个可选模块的净正确率收益与成本。

冻结规则：

- 没有稳定正确率收益的模块默认关闭；
- 显著增加 P95、fallback 或故障率的模块默认关闭；
- 只有最终选择结果写回 `config/competition.json`；
- 状态从 `candidate-unvalidated` 改为 `frozen` 时，必须附 benchmark artifact hash、数据集 hash、commit 和审核签名。

## 10. 阶段依赖与禁止并行项

```text
S0 正确性止血
  -> S1 Contract/State/Config
    -> S2 Router/Resource
      -> S3 Reasoning/Context
        -> S4 Metrics/E2E
          -> S5 Content/RAG
            -> S6 Real Ablation/Freeze
```

可局部并行：

- S0 的 Formatter 与 Trace 指标可并行；
- S1 的 Schema 与 Config 可并行，但必须在 State Machine 集成前汇合；
- S5 的人工内容审核可在 S2–S4 期间进行。

禁止提前：

- 修复 C06/C07 前不得用当前 Token/CEPC/timeout 指标做配置决策；
- 修复 C01–C04 前不得宣称证明或最终输出闭环；
- public config 与 benchmark config 统一前不得冻结 competition 配置；
- expanded candidate 全重验完成前不得用 Lemma 消融结果证明收益。

## 11. 每阶段统一 Definition of Done

每个阶段必须：

1. 先增加能够复现本阶段缺陷的失败测试；
2. 只修改本阶段范围内的代码；
3. 为新增跨模块对象提供 Schema version、validate 和序列化测试；
4. 不修改 `main.py`、`llm_client.py`；
5. 所有模型调用仍只经过注入的 `client.chat(...)`；
6. 所有题内可变状态仍归属当前 Session；
7. 所有数学证据都能反查 capability、invocation、Claim 和 obligation；
8. 更新 `CHANGELOG.md`、本报告状态和必要 ADR；
9. 执行完整门禁；
10. 一个阶段一个提交，提交信息对应阶段目标；
11. 报告变更文件、测试结果、剩余风险和下一阶段边界。

## 12. 最终 Competition Definition of Done

只有同时满足以下条件，项目才可标记为 competition-grade：

### 接口与基线

- 官方文件完整性通过；
- 公开入口使用已冻结配置；
- final_response 非空，trace/metrics 可序列化；
- 所有失败路径有安全、可诊断降级。

### 数学正确性

- 弱能力证据不能提升为数学真值；
- required obligation 只能由匹配 capability 的证据完成；
- Finalizer/Formatter 不改变已验证结论或推导；
- Repair/Lemma 后执行完整重验；
- assumption/domain 贯穿工具、等价和仲裁。

### 契约与状态

- 核心 Schema 版本化、严格验证；
- Runtime 状态转换合法；
- Feature 依赖合法；
- Prompt/Skill/RAG/Config/Tool 版本可追溯。

### 稳定性

- 模型、本地工具、RAG 和上下文操作共享资源边界；
- 并发不串题，返回后状态不变；
- Deadline 内有确定性 finalize/fallback；
- Trace 截断不丢终态指标。

### 测试与评测

- Unit、Contract、E2E、fuzz、故障注入和并发测试通过；
- 低/中/高风险黄金集通过；
- Benchmark 指标可从 records 重算；
- 真实重复消融具有置信区间；
- 最终配置由证据选择并附完整 provenance。

## 13. S0 实施记录（2026-07-23）

S0 已按 C01–C04、C06–C07 的解决方案实施；C05 的公开入口配置绑定仍属于 S1，不在本阶段提前混入。

### C01/C02

- 新增宿主定义的 `ClaimKind`、`ClaimVerificationState` 和
  `VerificationCapability`；
- Direct、隔离进程和 StdIO MCP 的 ToolResult 统一携带 capability；
- `check_type` 只作为受控建议进入宿主白名单，未知建议产生
  `unknown` host evidence；
- syntax、parse、answer-shape 和 numerical support 不再把数学 Claim
  标为 `verified`；
- 删除 obligation 对 Claim statement 的自由文本包含匹配；
- `ProofCompletionGate` 只接受显式 obligation ID、Claim ID 和匹配
  capability 的 Evidence，并记录 `satisfaction_evidence_ids`；
- Lemma 不继承弱检查或 soft obligation review 的 verified 状态；
- 四句空断言 E2E 进入 deterministic fallback。

### C03/C04

- `HarnessConfig`、competition 和 A9 配置默认关闭 LLM Finalizer；
- 显式启用时，答案、推导、Claim、假设或定理发生任何变化均回滚；
- Formatter 清除已有答案行并生成唯一 `Final answer:` 块；
- choice、fraction、set、interval 和 matrix 保持原始精确表示；
- raw-text 降级路径继续原样返回，保持公开入口兼容。

### C06/C07

- Trace 敏感键使用 credential 精确规则，保留 `estimated_tokens`；
- `session_started`、`budget_summary`、`fallback_used` 在事件压力下保留；
- Runtime 返回独立于 judge trace 的 `run_metrics`；
- Tool trace 使用
  `timeout|parse_unknown|domain_unknown|error|pass|fail` 原因；
- context failure rate 直接由 `context_view_built` 和
  `context_budget_infeasible` 重算；
- benchmark schema 升级到 2.1，序列化 records 可离线 round-trip 后重算
  同一 summary。

### S0 验收结果

- 新增反例测试均通过；
- 全量 pytest：146 项通过；
- `python -m compileall .`：通过；
- `ruff check .`：通过；
- `mypy mathforge user_agent.py`：77 个源文件通过；
- 分支覆盖率测试：146 项通过，总覆盖率 80%；
- `verify_baseline_files.py`：官方冻结文件完整；
- `validate_submission.py`：通过；
- `pip check`：无损坏依赖；
- `git diff --check`：通过。

## 14. S1 实施状态

S1（C05/C08/C09/C10）已完成工程实现：

1. ProblemIR、RoutePlan、Claim 与 CandidateSolution 已冻结版本化
   Schema，并在 parser、router、solver 和 repair 边界统一校验；
2. 模型返回中的宿主字段被覆盖并记录 contract deviation；
3. Runtime 已建立显式成功、skip、失败和 fallback 状态转换；
4. public 与 benchmark 已统一加载 `config/competition.json`，并使用相同
   语义配置哈希；
5. safe/balanced/competition 配置已完整展开，类型、范围、未知键和 Feature
   依赖在启动期校验；
6. Trace 与 benchmark 元数据已记录配置、Prompt、Skill、RAG 和 Tool 指纹；
7. `candidate-unvalidated` 状态会由提交校验显式报警。

详细实现和验收记录见
`docs/S1_IMPLEMENTATION_STATUS_2026-07-23.md`。

## 15. S2 实施状态

S2（C11/C12/C13/C14）已完成工程实现：

1. Router 已分离 confidence、ambiguity margin 和 complexity，并持久化
   `ProblemIR.subject_candidates`；
2. 同分或近同分高置信领域会保留 auxiliary；
3. 最终 risk 通过唯一纯函数重算 candidate、round、RAG、Lemma 和
   Finalizer 派生字段；
4. 新增 7 条人工标注路由校准集；
5. 配置 Schema 升级至 1.1，并完整加入 Claim、Tool、隔离 Tool、Tool
   秒数、Evidence 和 Prompt 总预算；
6. Parser、RAG、Context、模型、Direct/MCP/隔离 Tool 与仲裁等价检查共享
   Deadline；
7. Runtime 在路由后建立 CallAllocationPlan，必选 Verifier 配额不会被
   较早的可选 Repair 抢占；
8. Feature 容量不可达时，Trace 记录 `unreachable_by_budget`。

详细实现和验收记录见
`docs/S2_IMPLEMENTATION_STATUS_2026-07-23.md`。

## 16. 下一步

下一开发阶段为 S3（C15–C19、C23）：Lemma-only 第二轮上下文、
expanded candidate 全链路重验、namespaced ClaimGraph、Repair 依赖变更
闭包、assumptions-aware 等价和结构化方法独立性。

`config/competition.json` 仍保持 `candidate-unvalidated`；在真实重复消融前
不得标记 frozen，也不启动最终 A0–A10 配置结论。
