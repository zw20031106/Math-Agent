# Phase P1：Prompt 合约改造执行报告

日期：2026-09-12

## 范围与目标

本阶段执行 0907 Prompt/Skill 改造方案的 Phase P1。范围限定为 RouterPlanner、
PrimarySolver、AlternativeSolver、LemmaCurator、VerifierSkeptic、RepairAgent
和 LLMFinalizer 七个固定角色的 Prompt 合约。目标是在不改变既有机器协议的
前提下，把数学职责边界和可检查的推理要求写入角色合约。

## 已完成的实现

- Router 合约明确只输出 RouterIntentV1 的七个既有意图字段，补充结构化
  领域/方法识别规则和 low/medium/high 风险判定；明确禁止求解、Claim、
  Task、DAG、预算、候选和验证结论。
- PrimarySolver 合约补充原题条件保留、定理精确前提、等价/单向推出、
  定义域/符号/分支/可逆性/收敛性检查，以及证明题的存在性、唯一性、
  归纳和反证要求；无法关闭义务时必须公开暴露，而不是补造假设。
- AlternativeSolver 合约定义真正的方法独立性，禁止换符号或重排同一
  推导冒充替代方案；方法不成立或缺少前提时明确 abstain。
- LemmaCurator 合约要求引理与局部义务有直接关系，检查新假设、目标重述、
  伪分解和边界遗漏，禁止把暂定引理当作已验证事实。
- VerifierSkeptic 合约固定从原题条件到最终答案的依赖审计顺序，区分数学
  缺陷分类与系统级失败分类，并要求 Finding 引用真实 Claim/Step/Obligation/
  Evidence。
- RepairAgent 合约固定“最早失败 Claim → dependency closure → 最小修复 →
  重新验证”流程，要求把全局方法失败报告为 global_method_failure。
- LLMFinalizer 合约限定为已验证候选的表达整理，禁止新增推导、Evidence、
  结论或验证状态。

七个合约的 frontmatter、版本、输入/输出 schema、RouterIntent 字段和
解析行为均保持不变；没有新增 parser recovery，也没有修改冻结的
main.py、llm_client.py。

## 验证结果

代码与测试证据：

- python -m compileall . 通过；
- Prompt、路由、Prompt 编译快照和 P1 不变量测试通过（受影响测试合计
  16 项）；
- Prompt golden snapshot 已按新的合约指纹刷新；
- python scripts/verify_baseline_files.py 通过。

全套测试中，Prompt 变更造成的 golden mismatch 已修复；仓库仍有两项
content-review/submission 测试被历史 docs/content_review_manifest.json
的多组旧内容 hash 阻塞。这些 hash 涵盖此前阶段文件，并非本阶段的测试
失败修复目标；本阶段没有手工改动治理清单来掩盖该问题。

## 证据边界与后续

本阶段只有代码和离线测试证据，未运行真实 Intern 模型、官方题集或准确率
回归，因此不宣称数学准确率提升。真实模型验证必须在固定 Prompt/Skill/
配置指纹下单独记录，并通过官方结果与治理清单审查。

