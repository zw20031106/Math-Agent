# Math-Agent 逐文件作用、模块职责与调用关系

日期：2026-07-25
覆盖范围：`git ls-files` 返回的全部 257 个受控文件
阅读方式：本表描述“文件负责什么”和“主要被谁调用/调用谁”；空的包初始化文件
也单独列出，避免把目录边界误认为不存在。

## 1. 根目录与官方基线

| 文件 | 作用 | 主要关系 |
|---|---|---|
| `.env.example` | 展示本地环境变量名；不保存真实凭证 | 用户/CLI 复制后设置 `INTERN_API_KEY`、`INTERN_MODEL` |
| `.gitignore` | 忽略虚拟环境、缓存、测试结果、临时数据库和构建物 | Git 工作树；不参与运行时 |
| `AGENTS.md` | 仓库级开发约束，尤其是不可改官方文件、模型接口和测试门禁 | Codex/开发者工作流；约束全部代码 |
| `CHANGELOG.md` | 按阶段记录 S0–S6/E0–E7 的设计与实施变更 | README、审查报告和发布判断的历史依据 |
| `README.md` | 项目使命、架构、公共输出、运行命令和验收命令 | 用户入口；引用 `user_agent.py`、`scripts/run_case_outputs.py` |
| `baseline_manifest.json` | 保存不可变官方文件的 Git Blob 哈希 | `scripts/verify_baseline_files.py` 读取；当前实际校验 `main.py`、`llm_client.py` |
| `baseline_snapshot/user_agent_official.py` | 官方样例 `user_agent` 快照，便于审查基线 | 仅基线参考，不是当前生产入口 |
| `llm_client.py` | 官方注入式 Intern OpenAI-compatible Client；读取 API Key、Base URL、Model，调用 `requests.post` | 被不可变 `main.py` 和自定义 runner 实例化；当前默认模型是 Legacy `intern-s2-preview` |
| `main.py` | 官方样例批量入口；加载 JSONL、共享 Agent、异步题级并发、写结果 | 调用 `InternChatClient`、`ReasoningAgent`；与自定义四字段 runner 不同 |
| `pyproject.toml` | Setuptools、pytest、mypy、ruff、coverage 配置 | 测试/静态检查工具读取 |
| `requirements.txt` | 运行时依赖（requests、sympy） | 安装项目运行环境 |
| `requirements-dev.txt` | 开发和测试依赖（pytest、coverage、ruff、mypy） | 本地质量门 |
| `requirements-lock.txt` | CPython 3.13 锁定依赖版本 | 离线安装和可复现环境 |
| `user_agent.py` | 公共 `ReasoningAgent`；校验精确模型身份，构造 Harness，返回四字段公共结果 | 官方/自定义入口导入；调用 `mathforge.runtime`、`output.public_result` |

## 2. 配置文件

| 文件 | 作用 | 主要关系 |
|---|---|---|
| `config/competition.json` | 竞赛候选配置；6 次模型调用、模型并发 1、65,536 Completion、256K Context，功能大多开启 | `load_competition_config`、benchmark runner；状态仍为 `candidate-unvalidated` |
| `config/balanced.json` | 中等成本/能力配置；并发和 Completion 较保守 | `scripts/run_benchmark.py` 通过配置加载 |
| `config/safe.json` | 最小安全路径；关闭 Router、Skills、候选、工具、证据、Verifier、Memory 等 | 离线/故障降级和配置契约测试 |
| `config/component_decisions.json` | RAG、MCP、Finalizer 的默认开关、理由和启用门 | `mathforge.provenance`、治理校验 |
| `config/ablation/A0.json` | 基线消融：关闭 Router/Skills/高级闭环 | `run_benchmark` 合并到基础配置 |
| `config/ablation/A1.json` | 仅逐步开启 Alternatives 等候选相关能力 | 消融运行 |
| `config/ablation/A2.json` | 工具/证据相关消融 | 消融运行 |
| `config/ablation/A3.json` | 进一步关闭证据与验证路径 | 消融运行 |
| `config/ablation/A4.json` | 关闭 Proof/Verifier/Memory 等高阶闭环 | 消融运行 |
| `config/ablation/A5.json` | Memory/Lemma/RAG/Repair/Finalizer 消融 | 消融运行 |
| `config/ablation/A6.json` | Lemma/RAG/Repair/Finalizer 消融 | 消融运行 |
| `config/ablation/A7.json` | RAG/Repair/Finalizer 等可选组件消融 | 消融运行 |
| `config/ablation/A8.json` | Repair/Finalizer 对照 | 消融运行 |
| `config/ablation/A9.json` | Finalizer 对照 | 消融运行 |
| `config/ablation/A10.json` | Finalizer/末端展示对照 | 消融运行 |

所有 A0–A10 文件都是 overlay，不是完整独立配置；必须由
`scripts/run_benchmark.py` 与基础配置合并后才能解释。

## 3. 数据与治理输入

| 文件 | 作用 | 主要关系 |
|---|---|---|
| `data/dev_set_2_gold.jsonl` | 88 题规范化金标：expected answer、subject、answer type 等 | `benchmark.py`、评分、Router/E3 测试 |
| `data/golden_e2e.json` | 低/中/高风险端到端黄金案例及预期阶段 | `tests/test_s5_governance.py`、Runtime E2E |
| `data/knowledge_cards.json` | 审核过的离线数学知识卡 | `scripts/build_rag.py` 生成 SQLite；Retriever 只读 |
| `data/math_knowledge.sqlite` | 知识卡 FTS5/BM25 数据库 | `mathforge.retrieval.retriever.Retriever` 读取；Competition 默认不用 |
| `data/retrieval_bilingual_benchmark.json` | 中英文检索效果基准 | RAG 评测和内容治理 |
| `data/router_calibration.json` | Router 风险/置信度校准集 | Router 评估与配置判断 |
| `data/router_e5_baseline.json` | E5 Router 88 题基线结果 | `scripts/evaluate_router.py`、Skill/Router 审查 |

## 4. 设计文档与实施记录

| 文件 | 作用 | 主要关系 |
|---|---|---|
| `docs/ADR_001_S3_DETERMINISTIC_LEMMA_CURATOR.md` | 决定 LemmaCurator 在生产中是确定性 Host 服务 | `runtime.py`、Lemma Loop、Prompt 审核 |
| `docs/ADR_002_S5_OPTIONAL_COMPONENT_DEFAULTS.md` | 决定 RAG/MCP/Finalizer 默认关闭和启用门 | `config/component_decisions.json`、Provenance |
| `docs/CURRENT_SYSTEM_DEFECTS_AND_REMEDIATION_PLAN_2026-07-23.md` | D01–D30、C01–C26 总缺陷和原实施计划 | 本次复审的历史基线 |
| `docs/DEEP_IMPLEMENTATION_AUDIT_2026-07-22.md` | 早期深度实现审查 | 设计演进参考 |
| `docs/KNOWLEDGE_CARD_REVIEW_CHECKLIST.md` | Knowledge Card 来源、条件和审核清单 | RAG 内容治理 |
| `docs/PUBLIC_OUTPUT_CONTRACT.md` | 四字段公共输出、status、Trace、逐题写盘和 Resume 契约 | `public_result.py`、`run_case_outputs.py`、提交校验 |
| `docs/R0_R2_IMPLEMENTATION_STATUS_2026-07-22.md` | R0–R2 阶段状态 | 早期工程验收 |
| `docs/R3_R5_IMPLEMENTATION_STATUS_2026-07-23.md` | R3–R5 角色、工具、记忆、RAG/MCP 状态 | 早期工程验收 |
| `docs/R6_IMPLEMENTATION_STATUS_2026-07-23.md` | R6 治理、内容和消融前状态 | S6 前置依据 |
| `docs/S1_IMPLEMENTATION_STATUS_2026-07-23.md` | S1 Schema/状态/配置实施状态 | C08/C09/C10 记录 |
| `docs/S2_IMPLEMENTATION_STATUS_2026-07-23.md` | S2 Router/预算/Deadline 实施状态 | C11–C14 记录 |
| `docs/S3_IMPLEMENTATION_STATUS_2026-07-23.md` | S3 Context/Memory/Lemma/Repair 实施状态 | C15–C19 记录 |
| `docs/S4_IMPLEMENTATION_STATUS_2026-07-23.md` | S4 Trace/指标/Benchmark/并发污染状态 | C20–C22 记录 |
| `docs/S5_IMPLEMENTATION_STATUS_2026-07-23.md` | S5 RAG/MCP/离线治理状态 | C24–C26 记录 |
| `docs/S6_A_IMPLEMENTATION_STATUS_2026-07-24.md` | E0 模型身份、安全、Provenance | `model_identity.py`、安全测试 |
| `docs/S6_B_IMPLEMENTATION_STATUS_2026-07-24.md` | E1 256K Context、15 分钟 Deadline | `context_budget.py`、`deadline.py` |
| `docs/S6_C_IMPLEMENTATION_STATUS_2026-07-24.md` | E2 Trace 2.0 和公开候选步骤 | `trace.py`、`public_result.py` |
| `docs/S6_D_IMPLEMENTATION_STATUS_2026-07-24.md` | E3 Problem Parser、Answer Type、Scoring | parsing/evaluation 模块 |
| `docs/S6_E_IMPLEMENTATION_STATUS_2026-07-25.md` | E4 Prompt Contract v2 | `prompts/`、Prompt Probe |
| `docs/S6_F_IMPLEMENTATION_STATUS_2026-07-25.md` | E5 Skill 2.0 与 Router | `skills/`、`router_planner.py` |
| `docs/S6_G_IMPLEMENTATION_STATUS_2026-07-25.md` | E6 Evidence、Repair、Lemma、工具闭环 | verification/harness |
| `docs/S6_H_IMPLEMENTATION_STATUS_2026-07-25.md` | E7 逐题生命周期、Manifest、原子输出 | `scripts/run_case_outputs.py` |
| `docs/SKILL_2_MATHEMATICAL_REVIEW_2026-07-25.md` | Skill/Prompt/数学内容工程审查记录 | `content_review_manifest.json` |
| `docs/content_review_manifest.json` | 内容树、哈希、工程审核人和人工审核状态 | `governance.reviews`、Provenance |
| `docs/PROJECT_FULL_ARCHITECTURE_AUDIT_AND_REMEDIATION_PLAN_2026-07-25.md` | 本次全局架构、模型调用、问题和实施计划 | 本文件的配套总审查 |
| `docs/FILE_MODULE_COMPONENT_CALL_MAP_2026-07-25.md` | 本逐文件职责/调用关系清单 | 项目开发文档 |

## 5. `mathforge` 公共包与核心入口

| 文件 | 作用 | 主要关系 |
|---|---|---|
| `mathforge/__init__.py` | 包级导出 `MathForgeHarness` | 外部包导入 |
| `mathforge/runtime.py` | 2,090 行总编排：初始化服务、创建题内 Session、串联全部阶段、Fallback、收尾指标 | `user_agent.py` 调用；依赖几乎所有子包 |
| `mathforge/config.py` | `HarnessConfig`、配置 Schema/范围/依赖校验、Competition 配置加载和指纹 | `user_agent.py`、Runtime、Benchmark、提交校验 |
| `mathforge/model_identity.py` | 精确模型 ID、环境变量校验、不可观测响应元数据声明 | `user_agent.py`、runner、Provenance、artifact |
| `mathforge/provenance.py` | 聚合代码/配置/Prompt/Skill/RAG/Tool/Tokenizer/模型审核指纹 | Runtime session_started、Benchmark artifact |
| `mathforge/benchmark.py` | JSONL 加载、预检、并发运行、逐题记录、污染检测、统计、Bootstrap/Wilson/配对分析 | `run_benchmark.py`、`run_case_outputs.py`、测试 |
| `mathforge/tool_prompt_examples.py` | 九个本地工具的精确 Claim、Host 重建参数和反例提示数据 | PromptCompiler、ToolRegistry、Phase 3 测试 |

## 6. `mathforge.agents`

| 文件 | 作用 | 主要关系 |
|---|---|---|
| `mathforge/agents/__init__.py` | 导出 Router 相关公共类 | 包级导入 |
| `mathforge/agents/registry.py` | 解析 Prompt/Skill frontmatter，加载版本、角色、章节、指纹；渲染 system/user messages | Router、Solver、Verifier、Repair、Finalizer、Provenance |
| `mathforge/agents/prompt_compiler.py` | 按题型/角色编译 minimal/standard/tool/proof Prompt，统一核心 Candidate 协议和动态输出预算 | Router、Solver、Verifier、Repair、Finalizer、Provenance |
| `mathforge/agents/router_planner.py` | 硬编码领域信号、风险分析、方法族、Skill/Tool 选择；低置信度时可发 Router LLM 请求 | Runtime 调用；Prompt Contract、ProblemIR |
| `mathforge/agents/solver.py` | `PrimarySolver`/`AlternativeSolver` 构造消息；`SolverExecutor` 消耗预算、调用 Provider、解析 Candidate | CandidateOrchestrator、Runtime |
| `mathforge/agents/verifier.py` | VerifierSkeptic 批量审查 Claims/义务；解析 pass/fail/unknown；含 LemmaVerifier | Runtime、Lemma Loop、EvidenceLedger |
| `mathforge/agents/repair.py` | RepairAgent 只接收失败 Claim dependency closure，调用模型返回局部 Patch | `harness.repair.ClaimRepairService`、Runtime |
| `mathforge/agents/lemma_curator.py` | 确定性问题内 Lemma 卡抽取/生成，不发起生产 LLM 调用 | `harness.lemma_loop`、LemmaMemory |
| `mathforge/agents/finalizer.py` | 可选 LLMFinalizer；要求保持答案/Claims/数学内容不变，失败时确定性格式化 | Runtime；Competition 默认关闭 |

## 7. `mathforge.context`

| 文件 | 作用 | 主要关系 |
|---|---|---|
| `mathforge/context/__init__.py` | 导出 ContextAssembler、Compressor、RoleContextFactory 等 | 包级导入 |
| `mathforge/context/assembler.py` | 以题目、候选、Evidence、Obligation、ClaimGraph 组装 `ContextSnapshot`；保存 RawContext 引用 | RoleContextFactory、Runtime |
| `mathforge/context/claim_graph.py` | 构建候选 Claim 依赖图、命名空间和闭包 | Compressor、Repair Scope、Trace |
| `mathforge/context/compressor.py` | 按角色过滤候选、证据、义务、Claim 图，先保硬证据再裁剪可选内容 | RoleContextFactory |
| `mathforge/context/errors.py` | `ContextBudgetExceeded` | Assembler/Compressor/Provider/Prompt Loader |
| `mathforge/context/invariants.py` | 提取压缩后必须保留的硬证据和必需义务 | CompressionValidator |
| `mathforge/context/role_views.py` | 通过 Blackboard 权限和 Compressor 构造角色视图 | Runtime、各角色 Agent |
| `mathforge/context/snapshots.py` | `ContextSnapshot`、`RoleContextView` 序列化和 Prompt JSON 投影 | Assembler、Compressor、Agent 消息构造 |
| `mathforge/context/validator.py` | 验证原题、条件、最终答案、硬证据、必需义务在压缩中未丢失 | Compressor |
| `mathforge/context/views.py` | 按角色裁剪 Candidate：Alternative 隐藏 Primary 解，Verifier 隐藏 solution_text，Repair 只保留影响 Claim | Compressor |

## 8. `mathforge.harness`

| 文件 | 作用 | 主要关系 |
|---|---|---|
| `mathforge/harness/__init__.py` | Harness 包初始化 | 包边界 |
| `mathforge/harness/allocation.py` | `CallAllocationPlan`：按 Router/Primary/Alternative/Verifier/Repair/Lemma/Finalizer 分配模型调用槽位 | Runtime、CallBudget |
| `mathforge/harness/budget.py` | 题内模型、Token、Claim、Tool、Evidence、Prompt 字符和背景尾调用计数 | Runtime、Provider、Tool、Metrics |
| `mathforge/harness/context_budget.py` | Intern-S2 Tokenizer 选择、哈希校验、UTF-8 保守回退、Prompt/Completion 256K 分配 | Provider、Runtime、Provenance |
| `mathforge/harness/deadline.py` | 单调时钟、600/705/840/870 秒阶段、模型启动余量 | CallBudget、Provider、Runtime |
| `mathforge/harness/debug.py` | 注入式私有 Debug Sink、JSONL 写入和异常/路径/凭证脱敏 | Runtime；默认不启用 |
| `mathforge/harness/errors.py` | `MathForgeError`、`BudgetExceeded`、`ContractViolation`、FailureCode 分类 | Runtime、Provider、Benchmark |
| `mathforge/harness/events.py` | Trace Schema 2.0 的事件阶段、公共保护事件和事件白名单 | Trace、Public Result |
| `mathforge/harness/executor.py` | 兼容性重导出 `SolverExecutor` | 旧导入方；应视为薄兼容层 |
| `mathforge/harness/fallback.py` | 模型/闭环失败时返回非空确定性说明 | Runtime、逐题 Watchdog |
| `mathforge/harness/fingerprints.py` | 请求、文件、语义对象和 Markdown 目录哈希 | Benchmark、Provenance、Tool/Skill/Prompt |
| `mathforge/harness/lemma_loop.py` | 高风险证明题的 Lemma eligibility、轮次、验证、扩展候选和停止原因 | Runtime、LemmaCurator、LemmaVerifier、LemmaMemory |
| `mathforge/harness/metrics.py` | `RunMetrics` Schema 1.2，收集调用、Token、Tool、Evidence、Repair、RAG、污染和终态指标 | Runtime、Benchmark、Trace |
| `mathforge/harness/orchestration.py` | 候选 Fanout，固定方法族，线程池分支失败隔离，候选 Trace payload | Runtime、SolverExecutor |
| `mathforge/harness/provider.py` | 唯一模型访问边界；`ModelCallGate` 限并发，`OfficialClientProvider` 做 Context 分配和计量 | Runtime、所有 LLM 角色 |
| `mathforge/harness/repair.py` | `ClaimRepairService`：失败 Claim 影响闭包、版本化候选、局部再验证、回滚 | Runtime、RepairAgent、Evidence |
| `mathforge/harness/schemas.py` | ProblemIR、RoutePlan、Candidate、Claim、Evidence、ProofObligation、Lemma、Session 等核心 Schema | 几乎所有组件 |
| `mathforge/harness/session.py` | 每题创建 UUID Session、CallBudget、SessionMemory、LemmaMemory、RawContextStore | Runtime |
| `mathforge/harness/state.py` | RuntimePhase 枚举和合法状态转换 | MathSession、Runtime、测试 |
| `mathforge/harness/trace.py` | TraceBuilder 事件追加/脱敏/序列号/完整性校验 | Runtime、Public Result、Runner |

## 9. `mathforge.memory`

| 文件 | 作用 | 主要关系 |
|---|---|---|
| `mathforge/memory/__init__.py` | 导出 Blackboard 和 SessionMemory | 包级导入 |
| `mathforge/memory/session_memory.py` | 线程安全、题内隔离的 MemoryItem 列表 | Session、Blackboard、LemmaMemory |
| `mathforge/memory/blackboard.py` | 按角色读写权限发布和读取 memory | RoleContextFactory、Runtime |
| `mathforge/memory/policies.py` | System/Router/Solver/Verifier/Repair/Finalizer 的 category ACL | Blackboard |
| `mathforge/memory/lemma_memory.py` | 只允许 verified Lemma 写入题内 Lemma 区 | LemmaLoop、LemmaCurator、Verifier |

## 10. `mathforge.parsing`

| 文件 | 作用 | 主要关系 |
|---|---|---|
| `mathforge/parsing/__init__.py` | 导出 ProblemParser、SolutionParser | Benchmark、Runtime |
| `mathforge/parsing/latex.py` | 基础 LaTeX 花括号平衡检查 | ProblemParser、Formatting Tool |
| `mathforge/parsing/normalization.py` | Unicode/数学符号/空白/换行规范化 | ProblemParser |
| `mathforge/parsing/problem_parser.py` | 从自然语言识别 problem type、answer type、目标短语、假设、领域和风险标志 | Runtime、Benchmark、Router |
| `mathforge/parsing/solution_parser.py` | 解析 Candidate，并区分完整、Schema 违约、截断、畸形、自然语言和空响应；拒绝 JSON wrapper 泄漏 | SolverExecutor、RepairAgent、Finalizer |

## 11. `mathforge.output`

| 文件 | 作用 | 主要关系 |
|---|---|---|
| `mathforge/output/__init__.py` | 导出 AnswerValidator、DeterministicFormatter | 包级导入 |
| `mathforge/output/answer_validator.py` | 按 ProblemIR 检查 choice/integer/fraction/vector/tuple/interval/set/matrix 等形状 | Runtime、Evidence answer_type_check |
| `mathforge/output/deterministic_formatter.py` | 去重复 Answer 行，拼接公开 solution 和 Final answer | Runtime、Finalizer fallback |
| `mathforge/output/public_result.py` | 将内部结果投影为 `id/status/final_response/trace`；过滤/压缩公共 Trace | `user_agent.py`、逐题 runner、提交校验 |

## 12. `mathforge.evaluation` 与 `governance`

| 文件 | 作用 | 主要关系 |
|---|---|---|
| `mathforge/evaluation/__init__.py` | 导出 Prompt Probe、Score API、Artifact API | 测试/脚本 |
| `mathforge/evaluation/artifacts.py` | Benchmark artifact 生成、语义指纹和 Schema 校验 | `run_benchmark.py`、验证脚本 |
| `mathforge/evaluation/prompt_contract_probe.py` | 固定 20 题 Prompt Contract Probe、响应分类、私有推理字段检测和门槛 | E4 测试、真实/注入 Client |
| `mathforge/evaluation/routing.py` | 使用 RouterRuleEngine 对金标计算 Top-1/Top-2 和错误 | `evaluate_router.py`、Router 测试 |
| `mathforge/evaluation/scoring.py` | final answer 提取、exact/choice/integer/fraction/symbolic/vector/tuple/set/interval/matrix 比较和 LaTeX 规范化 | Benchmark、外部结果分析 |
| `mathforge/governance/__init__.py` | Governance 包初始化 | 包边界 |
| `mathforge/governance/reviews.py` | 校验 content review manifest 的路径、文件计数、hash、审核范围和人工签名 | `validate_submission.py`、Provenance |

## 13. `mathforge.retrieval`

| 文件 | 作用 | 主要关系 |
|---|---|---|
| `mathforge/retrieval/__init__.py` | 导出 Retriever、KnowledgeCard、SearchHit | Runtime/脚本 |
| `mathforge/retrieval/schemas.py` | KnowledgeCard、SearchHit、SearchResult、RetrievalStatus Schema | Builder、Retriever、Provenance |
| `mathforge/retrieval/builder.py` | 读取 JSON 知识卡、校验并原子构建 SQLite FTS5 数据库 | `scripts/build_rag.py` |
| `mathforge/retrieval/retriever.py` | 只读 SQLite/BM25、subject/trust/condition 过滤、结构化失败状态 | Runtime（RAG 开启时）、Benchmark/Provenance |

## 14. `mathforge.tools`

| 文件 | 作用 | 主要关系 |
|---|---|---|
| `mathforge/tools/CAPABILITIES.md` | 工具 Capability、Strength 和限制的文字契约 | 工具治理、人工审核 |
| `mathforge/tools/__init__.py` | 导出 ToolExecutor、ToolRegistry、ToolResult | 包级导入 |
| `mathforge/tools/registry.py` | 9 个工具定义、输入 Schema、能力/限制、版本、Direct 执行入口 | ToolExecutor、Evidence、MCP Server |
| `mathforge/tools/executor.py` | Direct 或可选 StdIO MCP 执行；隔离工具子进程、超时、错误降级 | Evidence、Arbitration、Runtime |
| `mathforge/tools/safe_parse.py` | 受限 AST→SymPy 表达式解析，拒绝任意调用/属性 | Symbolic Tool、Scoring |
| `mathforge/tools/symbolic.py` | safe parse、simplify、带假设/域的 symbolic equivalence 和 counterexample | ToolRegistry、Evidence、Scoring |
| `mathforge/tools/numerical.py` | numerical residual、density normalization、small-case enumeration | ToolRegistry、Evidence |
| `mathforge/tools/linear_algebra.py` | 矩阵字面量的矩形和维度检查 | ToolRegistry、Evidence |
| `mathforge/tools/formatting.py` | LaTeX 花括号与 answer type 形状检查 | ToolRegistry、Evidence |
| `mathforge/tools/worker.py` | 隔离子进程的 JSON stdin/stdout 工具 Worker | ToolExecutor |
| `mathforge/tools/mcp_adapter.py` | 一次性 StdIO MCP Client，超时和协议错误转换为 ToolResult | ToolExecutor（MCP 开启时） |
| `mathforge/tools/mcp_server.py` | 一次性 StdIO JSON-RPC MCP Server，复用 ToolRegistry/Executor | `worker`/外部 MCP 调用 |

## 15. `mathforge.verification`

| 文件 | 作用 | 主要关系 |
|---|---|---|
| `mathforge/verification/__init__.py` | 导出 EvidenceLedger、ArbitrationPolicy、ProofObligationEngine | 包级导入 |
| `mathforge/verification/capabilities.py` | ClaimKind、VerificationCapability、ClaimVerificationState 和能力匹配矩阵 | Evidence、Completion、Tools |
| `mathforge/verification/evidence.py` | EvidenceLedger、ClaimEvidenceVerifier、工具参数重建、可重现 invocation | Runtime、ToolExecutor、Repair |
| `mathforge/verification/proof_obligations.py` | 根据题型、定理、目标和 Claim check_type 生成义务 | Runtime、ProofCompletion |
| `mathforge/verification/completion.py` | 检查每个 required obligation 是否有匹配 Claim/Evidence/Capability | Runtime、Lemma 扩展 |
| `mathforge/verification/equivalence.py` | 按 answer type、假设、域比较候选答案，构造等价/未知/不一致关系 | Arbitration |
| `mathforge/verification/arbitration.py` | 硬失败→义务覆盖→答案一致→独立方法→软证据的字典序排名 | Runtime |
| `mathforge/verification/methods.py` | Candidate MethodStep/Claim topology 签名、方法契约校验 | Orchestrator、Arbitration |
| `mathforge/verification/repair_scope.py` | 失败 Claim、依赖闭包、影响闭包、下游消费者计算 | ClaimRepairService |

## 16. Prompt Contract 文件

| 文件 | 作用 | 主要调用方 |
|---|---|---|
| `prompts/router_planner/contract.md` | Router 的领域、风险、三方法族 JSON Contract | `RouterPlanner` |
| `prompts/primary_solver/contract.md` | Primary 的完整 CandidateSolution v2、公开步骤和 Claim Contract | `PrimarySolver` |
| `prompts/alternative_solver/contract.md` | Alternative 的独立方法、禁止 Primary 解全文和方法族 Contract | `AlternativeSolver` |
| `prompts/verifier_skeptic/contract.md` | Verifier 的公开 Claims/义务审查和 pass/fail/unknown Contract | `VerifierSkepticAgent` |
| `prompts/repair/contract.md` | Repair 的失败 Claim 局部 Patch 和回滚 Contract | `RepairAgent` |
| `prompts/finalizer/contract.md` | Finalizer 只改公开表述、保留答案和数学内容 | `LLMFinalizer`，默认关闭 |
| `prompts/lemma_curator/contract.md` | Lemma 角色的审核模板；明确生产中不渲染、不调用模型 | 内容治理、Prompt Probe |

## 17. Skill 文件

所有 Skill 文件均由 `SkillRegistry` 加载、校验 frontmatter、按角色拼接并生成
指纹；实际是否触发仍由 `router_planner.py` 的领域信号和 `selected_skills_for`
决定。

### 17.1 领域 Skill

| 文件 | 领域职责 | 主要使用角色 |
|---|---|---|
| `skills/domains/abstract-algebra.md` | 群、环、域、理想、同态、Sylow 和不可约多项式 | Primary/Alternative/Verifier/Repair |
| `skills/domains/advanced-linear-algebra.md` | Jordan、最小多项式、Kronecker、中心化子、二次型 | Primary/Alternative/Verifier/Repair |
| `skills/domains/advanced-real-analysis.md` | 极限、级数、幂级数、收敛、积分交换 | Primary/Alternative/Verifier/Repair |
| `skills/domains/algebra.md` | 方程、不等式、多项式、因式分解 | Primary/Alternative/Verifier/Repair |
| `skills/domains/calculus.md` | 初等微积分、导数、积分、极值、换元 | Primary/Alternative/Verifier/Repair |
| `skills/domains/combinatorics.md` | 计数、排列组合、双射、递推、生成函数 | Primary/Alternative/Verifier/Repair |
| `skills/domains/complex-analysis.md` | 留数、围道、全纯、Rouché、解析延拓 | Primary/Alternative/Verifier/Repair |
| `skills/domains/differential-equations.md` | 通用微分方程分类和归约 | Primary/Alternative/Verifier/Repair |
| `skills/domains/differential-geometry.md` | 曲面、基本形式、Gaussian/测地曲率 | Primary/Alternative/Verifier/Repair |
| `skills/domains/discrete-math.md` | 图、递推、离散结构、归纳 | Primary/Alternative/Verifier/Repair |
| `skills/domains/functional-analysis.md` | Banach/Hilbert、泛函、算子谱和范数 | Primary/Alternative/Verifier/Repair |
| `skills/domains/general-math.md` | 没有可靠专门路由时的保守数学方法 | Primary/Alternative/Verifier/Repair |
| `skills/domains/geometry.md` | 三角形、圆、角、欧氏/向量几何 | Primary/Alternative/Verifier/Repair |
| `skills/domains/linear-algebra.md` | 矩阵、向量、特征值、线性映射、秩 | Primary/Alternative/Verifier/Repair |
| `skills/domains/logic.md` | 命题、谓词、量词、有效性、模型/反模型 | Primary/Alternative/Verifier/Repair |
| `skills/domains/measure-integration.md` | 测度、Lebesgue、Tonelli/Fubini、Lp | Primary/Alternative/Verifier/Repair |
| `skills/domains/number-theory.md` | 素数、整除、同余、赋值、丢番图方程 | Primary/Alternative/Verifier/Repair |
| `skills/domains/numerical-analysis.md` | 求积、迭代、插值、条件数、稳定性 | Primary/Alternative/Verifier/Repair |
| `skills/domains/operations-research.md` | 线性规划、对偶、最短路、最大流、指派 | Primary/Alternative/Verifier/Repair |
| `skills/domains/optimization.md` | 凸性、约束极值、驻点、对偶 | Primary/Alternative/Verifier/Repair |
| `skills/domains/ordinary-differential-equations.md` | 一/二阶 ODE、初值、线性系统、Euler | Primary/Alternative/Verifier/Repair |
| `skills/domains/partial-differential-equations.md` | 热/波/Laplace 方程、边界值、特征展开 | Primary/Alternative/Verifier/Repair |
| `skills/domains/probability.md` | 随机变量、分布、条件概率、期望、方差 | Primary/Alternative/Verifier/Repair |
| `skills/domains/real-analysis.md` | 实分析、紧致、完备、连续、收敛模式 | Primary/Alternative/Verifier/Repair |
| `skills/domains/regression.md` | 最小二乘、Ridge、Hat Matrix、残差和 F 检验 | Primary/Alternative/Verifier/Repair |
| `skills/domains/set-theory.md` | 集合、关系、幂集、基数和构造 | Primary/Alternative/Verifier/Repair |
| `skills/domains/statistics.md` | 似然、估计、Fisher 信息、Cramér–Rao | Primary/Alternative/Verifier/Repair |
| `skills/domains/stochastic-processes.md` | Brownian、Markov、Poisson、停时、平稳分布 | Primary/Alternative/Verifier/Repair |
| `skills/domains/topology.md` | 拓扑空间、同调、亏格、同胚、映射度 | Primary/Alternative/Verifier/Repair |

### 17.2 通用 Skill

| 文件 | 作用 | 主要使用角色 |
|---|---|---|
| `skills/general/answer-normalization.md` | 分数、根式、向量、矩阵、集合和代数结构的答案规范化 | Solver/Alternative/Repair/Finalizer |
| `skills/general/counterexample-search.md` | 中高风险、全称和逆命题的反例检查 | VerifierSkeptic |
| `skills/general/lemma-compression.md` | 高风险证明中压缩已验证局部 Lemma | LemmaCurator |
| `skills/general/numerical-stability.md` | 近似、误差、迭代、条件数和数值稳定性 | Solver/Alternative/Verifier |
| `skills/general/proof-obligation.md` | 证明、存在性、唯一性、充分必要和交换条件 | Solver/Lemma/Verifier/Repair |
| `skills/general/symbolic-equivalence.md` | 表达式、恒等式和变形结果的符号等价 | Solver/Alternative/Verifier |

## 18. 脚本与运行工具

| 文件 | 作用 | 主要关系 |
|---|---|---|
| `scripts/__init__.py` | 脚本包初始化 | `python -m scripts...` |
| `scripts/run_case_outputs.py` | 推荐逐题 runner：预检、900 秒 watchdog、单题 JSON 原子写入、Manifest、Resume、重试包装 | 直接调用 `InternChatClient`、`MathForgeHarness`、`run_benchmark` |
| `scripts/run_benchmark.py` | 配置合并、Prompt/Skill/Tool/RAG/Provenance 组装，运行 Benchmark artifact | `MathForgeHarness`、`benchmark.py` |
| `scripts/build_rag.py` | 读取知识卡并原子重建 SQLite FTS5 | `retrieval.builder` |
| `scripts/evaluate_router.py` | 在 Router 金标上统计 Top-1/Top-2 和错误 | `evaluation.routing` |
| `scripts/check_coverage_gates.py` | 检查全局、关键模块、分支覆盖率门槛 | coverage XML/CI |
| `scripts/scan_secrets.py` | 扫描 Git 文件和未跟踪文件中的 API token 模式 | `validate_submission.py`、安全门禁 |
| `scripts/validate_submission.py` | 冻结基线、内容审核、离线 Public Interface、秘密、依赖和绝对路径校验 | 提交前最终门禁 |
| `scripts/verify_baseline_files.py` | 用 Git Blob SHA-1 检验 `main.py`/`llm_client.py` 未修改 | 每次提交前 |
| `scripts/verify_benchmark_artifact.py` | 读取并校验 Benchmark artifact 完整性和哈希 | 运行后校验 |
| `scripts/verify_content_reviews.py` | 单独校验 content review manifest | 人工审核/提交门禁 |
| `scripts/verify_offline_install.py` | 构建临时 wheelhouse、clean venv、无网络安装和 Public API smoke test | 可复现部署 |

## 19. 测试文件

| 文件 | 覆盖内容 | 主要被测模块 |
|---|---|---|
| `tests/__init__.py` | 测试包初始化 | pytest |
| `tests/conftest.py` | 环境变量 fixture、模型身份和通用夹具 | 全部测试 |
| `tests/fake_client.py` | 注入式 Fake/可控延迟/失败模型 Client | Runtime/Provider/线程测试 |
| `tests/test_arbitration.py` | 字典序仲裁、硬证据和方法独立性 | `verification.arbitration` |
| `tests/test_baseline_integrity.py` | 官方基线哈希 | `verify_baseline_files` |
| `tests/test_benchmark.py` | Benchmark 运行、统计、污染、序列化 | `benchmark.py` |
| `tests/test_benchmark_metadata.py` | Benchmark 配置/模型/Provenance 元数据 | Benchmark/Config |
| `tests/test_budget.py` | CallBudget、阶段分配、Token/Tool/Evidence 预算 | `harness.budget/allocation` |
| `tests/test_case_outputs.py` | 逐题输出文件、字段和状态 | `run_case_outputs.py` |
| `tests/test_claim_verification.py` | Claim→Tool→Evidence 映射和能力状态 | `verification.evidence` |
| `tests/test_compression.py` | Context 压缩不丢硬证据/义务 | `context.compressor/validator` |
| `tests/test_config_contract.py` | 配置 Schema、范围和依赖 | `config.py` |
| `tests/test_coverage_gates.py` | 覆盖率脚本门槛 | `check_coverage_gates.py` |
| `tests/test_deadline_runtime.py` | Deadline、Provider 超时、并发门、Runtime 截止 | `deadline/provider/runtime` |
| `tests/test_evidence.py` | EvidenceLedger、事务和记录引用 | `verification.evidence` |
| `tests/test_fallback.py` | 空问题/调用失败的非空 Fallback | `harness.fallback` |
| `tests/test_finalizer.py` | Finalizer 答案/数学内容保持和回滚 | `agents.finalizer` |
| `tests/test_formatting.py` | 候选格式化和答案验证 | `output.*` |
| `tests/test_lemma_loop.py` | Lemma 资格、轮次、验证和扩展 | `harness.lemma_loop` |
| `tests/test_mcp.py` | StdIO MCP Server/Adapter 与 Direct fallback | `tools.mcp_*` |
| `tests/test_memory.py` | SessionMemory 和 Blackboard ACL | `memory.*` |
| `tests/test_orchestration.py` | Fanout、方法族、分支失败隔离 | `harness.orchestration` |
| `tests/test_parsing.py` | Problem/Solution Parser 基础和降级 | `parsing.*` |
| `tests/test_proof_completion.py` | Proof Obligation Completion Gate | `verification.completion` |
| `tests/test_proof_obligations.py` | Obligation 生成和 Claim 类型映射 | `verification.proof_obligations` |
| `tests/test_proof_runtime.py` | 证明题 Runtime 集成 | `runtime.py` |
| `tests/test_public_interface.py` | Public Result 四字段/status/Trace | `output.public_result` |
| `tests/test_repair.py` | Repair Scope 和局部 Patch | `harness.repair/verification.repair_scope` |
| `tests/test_repair_runtime.py` | Runtime Repair 事务 | `runtime.py` |
| `tests/test_retrieval.py` | KnowledgeCard、SQLite 建库和检索状态 | `retrieval.*` |
| `tests/test_role_context_runtime.py` | 角色 View、权限和 Runtime Context | `context.role_views` |
| `tests/test_routing.py` | Router signals、Risk、Skill/Tool 选择 | `agents.router_planner` |
| `tests/test_runtime_state.py` | Phase 合法转换和异常路径 | `harness.state/runtime` |
| `tests/test_s2_resources.py` | S2 资源预算和组件开关 | Config/Runtime |
| `tests/test_s3_reasoning_context.py` | ClaimGraph、Memory、Context、Repair/Lemma 闭环 | S3 组件 |
| `tests/test_s4_observability.py` | Trace、Metrics、错误码、Debug Sink、Benchmark 观测 | S4 组件 |
| `tests/test_s5_governance.py` | RAG/MCP/Artifact/Review/治理门 | S5 组件 |
| `tests/test_s6_e0_security.py` | 精确模型身份、Key/路径/秘密安全 | E0 组件 |
| `tests/test_s6_e1_context_deadline.py` | 256K、Tokenizer、Deadline、背景尾和超时输出 | E1 组件 |
| `tests/test_s6_e2_trace_v2.py` | Trace 2.0 序号、事件、投影、完整性 | E2 组件 |
| `tests/test_s6_e3_parser_scoring.py` | 88 题类型、Parser、评分回归 | E3 组件 |
| `tests/test_s6_e4_prompt_contracts.py` | 七角色 Contract、注入 Probe、禁止私有推理 | E4 组件 |
| `tests/test_s6_e5_skills_router.py` | 35 Skill 结构、Router 金标、角色组成 | E5 组件 |
| `tests/test_s6_e7_case_lifecycle.py` | Manifest、Resume、逐题原子写盘、watchdog | E7 runner |
| `tests/test_phase3_prompt_parser_integrity.py` | Prompt Profile/长度/预算、四类题三次完整 Candidate、响应完整性和工具 Claim 示例 | Phase 3 验收 |
| `tests/test_schema_contracts.py` | Problem/Candidate/Route/Claim Schema 严格校验 | `harness.schemas` |
| `tests/test_scoring.py` | 各答案类型 Scorer 和 LaTeX 规范化 | `evaluation.scoring` |
| `tests/test_serialization.py` | Schema/Benchmark/Trace JSON round-trip | 多个 `to_dict/from_dict` |
| `tests/test_session_isolation.py` | 多题 Session 和候选状态隔离 | Runtime/Memory |
| `tests/test_submission_validation.py` | 最终提交验证输出和 warning | `validate_submission.py` |
| `tests/test_thread_safety.py` | 共享 Agent、Gate、题内状态和 late callback | Runtime/Provider |
| `tests/test_tools.py` | 9 个工具、输入限制、Direct/isolated 结果 | `tools.*` |
| `tests/test_trace.py` | TraceBuilder、脱敏、终态和非法事件 | `harness.trace` |
| `tests/test_verifier_agent.py` | Verifier Prompt、finding 解析和义务引用 | `agents.verifier` |

## 20. 主调用关系摘要

```text
main.py
  └─ llm_client.InternChatClient
     └─ user_agent.ReasoningAgent
        └─ mathforge.runtime.MathForgeHarness
           ├─ config / model_identity / provenance
           ├─ parsing.problem_parser
           ├─ agents.router_planner + agents.registry
           ├─ context.role_views → assembler/compressor/claim_graph
           ├─ memory.blackboard → session_memory/lemma_memory
           ├─ harness.orchestration → agents.solver → harness.provider
           ├─ tools.executor/registry → verification.evidence
           ├─ verification.proof_obligations/completion
           ├─ harness.repair → agents.repair
           ├─ harness.lemma_loop → agents.lemma_curator/verifier
           ├─ agents.verifier
           ├─ verification.equivalence/arbitration
           ├─ output.answer_validator/deterministic_formatter
           ├─ harness.trace/metrics/deadline/fallback
           └─ output.public_result

scripts/run_case_outputs.py
  ├─ llm_client.InternChatClient(timeout/retry override)
  ├─ SerializedFastRetryClient
  ├─ PerCaseWallClockRunner
  ├─ mathforge.benchmark.run_benchmark
  ├─ MathForgeHarness
  └─ write_case_output + CaseRunManifest
```

## 21. 文件层面的关键边界结论

1. `main.py`、`llm_client.py` 是官方冻结样例，不等于当前自定义 runner 的真实
   生产行为；任何提交审查必须先确认评测入口。
2. `runtime.py` 是当前真正的 Harness 核心，调用关系完整但过于集中。
3. Prompt/Skill 是可版本化静态内容，不是可执行插件系统。
4. Memory 是题内工作区，不是长期学习记忆。
5. Tools 是 Host 执行的受限能力，不是模型原生函数调用。
6. `public_result.py` 是四字段契约的真正边界；`main.py` 没有复用它，是当前最
   重要的调用关系分叉。
7. 任何新增文件都应同时更新：注册/指纹、对应 Contract、单元测试、内容审核范围、
   本文件和总架构报告。
