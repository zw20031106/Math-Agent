# Phase S2 执行报告：Verification Hook 能力与证据强度审计

日期：2026-09-12  
状态：实现完成，待阶段校验提交  
范围：V3 Skill 的 `requires`、`verification_hooks`、ToolRegistry 能力声明、
验证方法边界，以及运行时 admission/trace

## 目标

把“Skill 声称使用某个验证工具”和“该工具能够支持的数学结论”分开审查，
防止把有限样本、形状检查或语法检查误读为普遍定理证明。审计遵循以下
结论边界：

| Hook | 可支持的最大范围 | 不能推导 |
| --- | --- | --- |
| `symbolic_equivalence` | 带明确域/假设的条件等式 | 无条件、域外等式或定理前提 |
| `numerical_residual` | 有限样本的数值支持 | 普遍等式/普遍定理 |
| `matrix_shape_check` | 矩阵形状与维度 | 可逆性、矩阵恒等式、谱性质 |
| `density_normalization` | 指定区间上的归一化积分 | 非负性及完整概率模型 |
| `small_case_enumeration` | 明确给出的有限实例 | 未测试范围内的普遍命题 |
| `safe_parse_expression` / `latex_syntax_check` | 语法/解析层检查 | 数学语义与正确性 |
| `answer_type_check` | 答案形状符合题目类型 | 答案数学正确 |

## 实现内容

1. 新增 `mathforge/skills/hook_audit.py`：
   - 用显式 `HOOK_POLICIES` 将每个 hook 绑定到 Tool Capability、
     `ClaimVerificationState`、最大证据强度、结论范围和验证方法边界；
   - 独立检查 `requires` 与 `verification_hooks` 的未知工具；两者不被强制
     相等（某工具可只用于求解），但 hook 未列入 `requires` 会产生可解释警告；
   - 检查 ToolRegistry 的 capability/claim_state/proves/limitations 是否与
     policy 一致；映射错误为阻断型 error；
   - 检查 `Verification Recipe` 是否写明弱证据边界。当前旧包未全部声明，
     因而记录 warning，不把存量内容悄悄当作普遍证明。
2. `SkillRuntime` 在加载时执行一次全量 V3 审计：
   - `hook_audit_report` 提供不可变的全量结果；
   - `SkillCheckPlan` 输出 `audit_warnings`、`audit_errors` 和
     `hook_assurance`；存在未知工具或能力/claim-state 不一致时，状态为
     `verification_hook_invalid`，不会被 admission；
   - 已知但弱的 hook 仍可执行其支持性检查，证据的实际硬/软状态仍由
     `EvidenceLedger`/`ClaimEvidenceVerifier` 的 capability-to-claim gate 决定。
3. 选择器的拒绝原因会包含 hook audit error，避免 trace 只显示一个空的
   `capability_admission`。

## 全量审计结果

当前目录共加载 51 个 V3 method Skill：

- 阻断型错误：0；
- 边界声明警告：39（主要是旧包的 Verification Recipe 未明确写出
  sampled/finite/shape/normalization 等证据边界）；
- `dominated-convergence`、`uniform-convergence`、Rouché/复分析等高风险
  包仍被标为可执行，但其 numerical hook 只具备 `finite_samples_only` 范围，
  不能单独关闭普遍收敛或复分析定理的 Proof Obligation。这些包的文字重写
  留到后续 S3，避免在审计阶段篡改数学内容。

## 验证

新增 `tests/test_phase_s2_verification_hook_audit.py`，覆盖：

- 真实 51 包全量审计无 capability/claim-state 错配；
- numerical hook 的 `finite_samples_only` assurance 与 medium 支持强度；
- 运行时审计警告可见且不冒充定理证明；
- 未知 `requires`/`verification_hooks` 阻断 admission；
- Tool capability 与 claim state 错配阻断 admission；
- hook 可作为验证工具而非求解必需工具时只产生非阻断警告。

阶段定向测试：`16 passed`（并与 E3、Phase 8 相关测试合计 `16 passed`）。
完整仓库校验沿用阶段边界结果：`compileall` 通过，官方冻结文件校验通过；
完整 `pytest` 的两个既有失败是陈旧的 `docs/content_review_manifest.json`
内容哈希，未通过手工修改 manifest 规避。

## 后续动作

S3 应优先重写高风险 Skill 的 Verification Recipe，并为每个 theorem-level
obligation 写出必要条件、反例边界和“支持性 hook 不能关闭该 obligation”的
明确文本；S5 再通过正例、负例、对抗样例和消融实验验证选择与准确率变化。

