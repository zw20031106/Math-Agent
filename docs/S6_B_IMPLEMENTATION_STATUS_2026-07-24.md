# S6-B / E1 实施状态：256K 动态上下文与 15 分钟墙钟

日期：2026-07-24

对应计划：阶段 E1

提交目标：`S6-B: enforce 256K dynamic context budget and 15-minute wall clock`

## 结论

E1 已把所有在线模型角色统一收口到同一个动态 Context Budget。Competition
配置不再设置 4096、1536、2048 等低 Completion 上限，也不再用 `len//4`
承担安全门禁。每次调用均先计算完整 `messages` 的 Token 数，再把正整数
`effective_max_output_tokens` 传给官方注入的 `client.chat()`：

```text
effective_max_output_tokens
  = min(
      positive_configured_cap_or_infinity,
      262144 - prompt_tokens - 8192
    )
```

若右侧不为正，调用会在进入 Client 前失败。当前 Competition 配置使用
`primary_max_tokens=65536`，避免向服务端申请接近整个上下文窗口的 Completion；
`max_model_tokens=0` 表示只记录总 Token、不按估算总量触发回退。

## 1. Config 1.2

Competition 配置固定为：

- `primary_max_tokens=65536`；
- `max_model_tokens=0`；
- `model_context_window_tokens=262144`；
- `context_safety_margin_tokens=8192`；
- `trace_max_chars=0`；
- `trace_max_events=0`；
- `soft_deadline_seconds=600`；
- `exploration_deadline_seconds=705`；
- `hard_deadline_seconds=870`；
- `deterministic_finalize_reserve_seconds=30`；
- `model_call_start_margin_seconds=135`。

`model_context_window_tokens` 只接受 262144。输出正数上限必须给 Prompt 和安全
余量留下空间。Competition 的会话 Prompt 字符预算提高到 5,000,000，避免旧的
200,000 字符累计额度先于 256K 单调用边界错误终止正常调用。

## 2. 固定 Tokenizer 与保守 Fallback

Token 计数身份固定为：

- 仓库：`internlm/Intern-S2-Preview-397B`；
- Revision：`35eba5f142353d180472cdad2d70b09d0a383113`；
- `tokenizer.json` SHA-256：
  `5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42`；
- `tokenizer_config.json` SHA-256：
  `b5e16dc283fec919c7c43ead8f7f5cdb37417ef108b4abf224a2a832335f127a`；
- `chat_template.jinja` SHA-256：
  `ae808284ec32b532b894f4d8d9f90fcc8db9826c33265a8602ffdab15d569210`。

仅当 `MATHFORGE_INTERN_S2_TOKENIZER_DIR` 指向的本地快照同时通过以上哈希
校验时，Harness 才会用官方 chat template 精确计数。加载过程禁止联网，也不
信任远程代码。未配置、文件缺失、哈希不符、依赖不可用或加载失败时，改用
Intern-S2 ChatML/Thinking 消息包络的 UTF-8 字节上界，并把实际模式、版本和
哈希写入每次调用记录。Fallback 不再使用字符数除以四。

## 3. 单一 Provider 调用边界

RouterPlanner、PrimarySolver、AlternativeSolver、Lemma 扩展、
VerifierSkeptic、RepairAgent 和 LLMFinalizer 都只把配置的 0/正数意图交给
`OfficialClientProvider`。Provider 在任何 Client 调用前：

1. 对完整消息应用固定 Token 计数策略；
2. 计算 Context Allocation；
3. 验证 `prompt + margin + requested_output <= 262144`；
4. 只把计算出的正整数传给注入 Client；
5. 记录调用阶段、计数模式、Prompt、请求输出、实际输出、字符数和耗时；
6. 拒绝违反已分配输出容量的响应。

模型调用并发仍由有界 Semaphore 控制。Provider 不读取 API Key、不创建第二
模型客户端、不访问 Client 私有字段，也不假定原生函数调用。

## 4. Deadline 状态机

统一单调时钟语义如下：

| 时间 | 允许行为 |
|---|---|
| 0–600 秒 | 正常主链及可选工作 |
| 600–705 秒 | 停止替代候选、RAG、Lemma、Finalizer；仍允许证据触发的 Repair/Verifier |
| 705–840 秒 | 不再启动模型调用，仅允许本地验证与已启动调用收尾 |
| 840–870 秒 | 强制 deterministic finalize/fallback |
| 870–900 秒 | Runner 构造终态、清洗、序列化并原子替换单题 JSON |

`DeadlineController` 不再把 optional 截止误当作所有 exploration 的截止。
在 705 秒或剩余模型等待时间不大于 135 秒时，任何新模型调用均被拒绝。

## 5. 900 秒终态与晚返回隔离

`PerCaseWallClockRunner` 给 Harness 870 秒返回窗口，并保留 30 秒结果持久化
窗口。若 Harness 未按时返回，Runner 生成：

- 非空确定性 `final_response`；
- `per_case_wall_clock_timeout` 事件；
- outcome 为 `timeout` 的 `run_completed` 终态；
- `per_case_wall_clock_exceeded` 稳定错误码；
- 独立的 timeout 指标。

结果仍由原有同目录临时文件加 `os.replace()` 原子写入，公开 JSON 顶层仍只有
`id/status/final_response/trace`。后台线程只能写入 Runner 的局部内存槽，没有文件
路径或持久化回调，因此晚返回不能二次覆盖已经写出的 timeout JSON。

## 6. Metrics 与 Trace

RunMetrics schema 1.1 和 `budget_summary` 现在记录：

- `token_limit_mode`；
- context window 与 safety margin；
- official/fallback Prompt Token；
- requested/observed output Token；
- output chars；
- 单模型调用和累计耗时；
- final response Token 与计数模式；
- deadline phase；
- model call timeout count；
- per-case wall-clock timeout count。

`trace_max_chars=0` 和 `trace_max_events=0` 的含义是总字符和事件数不截断。
Trace 的逐字段公开内容升级属于后续 E2，本阶段仍保留现有秘密、绝对路径和
私有推理清洗边界。

## 7. 自动化验收覆盖

E1 新增或更新的测试覆盖：

- 0 sentinel 配置和正数旧语义；
- 固定 Context Window；
- 官方 Tokenizer 身份与哈希；
- UTF-8 字节 Fallback；
- 临界窗口动态缩小；
- 超窗口 Prompt 在 Client 前拒绝；
- 七个模型角色阶段共用动态正整数；
- 600/705/840/870 秒边界；
- Trace 总字符和事件数的 0 sentinel；
- 超大模型响应和 final response 256K 门禁；
- 缩短时钟下的 900 秒等价 Runner timeout；
- timeout 四字段原子文件；
- 后台晚返回不覆盖；
- immutable baseline。

完整门禁以仓库 `README.md` 的 Verification 命令为准。`main.py` 与
`llm_client.py` 未修改。

本阶段最终验收结果：

- `python -m compileall .`：通过；
- `pytest -q`：276 passed；
- branch coverage：81.38%，高于 80% 总门槛；
- 关键模块 coverage gate：全部通过；
- Ruff：通过；
- Mypy：88 个源文件通过；
- secret scan、content review、baseline、submission validation、`pip check`
  和 `git diff --check`：全部通过；
- submission validation 仅保留预期的配置未冻结和人工数学签署待完成警告。

## 8. 当前边界

- 本阶段没有执行真实 397B 全量题集；按原计划，E0–E4 完成前不重复进行昂贵
  全量测试。
- 精确 Tokenizer 依赖预先准备的哈希匹配本地快照；缺失时会明确记录并使用
  保守 Fallback，不会静默声称精确计数。
- Trace 2.0 的候选公开步骤、逐字段无截断、统一 `seq/elapsed/stage` 属于 E2，
  未在 E1 越阶段实现。
- Competition 配置继续保持 `candidate-unvalidated`，直到后续真实 397B 重复
  试验和人工数学审核完成。
