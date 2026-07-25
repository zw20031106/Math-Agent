# Skill 2.0 数学内容工程审查

日期：2026-07-25

范围：`skills/domains/*.md`、`skills/general/*.md`

审查性质：工程侧数学内容审查；不替代人类数学专家签名。

全局治理状态：`pending-human`

## 审查结论

29 个领域 Skill 与 6 个通用 Skill 均已升级为 Skill 2.0。每个文件都有
可机器校验的 `triggers`、适用固定角色，以及以下九个完整章节：

1. Triggers
2. Roles
3. Method Decision Tree
4. Theorem Preconditions
5. Common Errors
6. Counterexample Checklist
7. Compatible Check Types
8. Answer Normalization
9. Trace Step Guidance

注册表会拒绝缺字段、未知角色、非 2.0 版本和缺章节文件。运行时按角色组合
完整 Skill 块；预算不足时省略整块并写入 Trace，不截断正文。该机制保证模型
不会收到只有触发词而没有定理条件、或只有方法开头而没有错误检查的残缺 Skill。

本次工程审查没有发现阻止 E5 合并的数学内容错误。正式内容冻结仍需人类专家
对定理适用范围、中文术语和竞赛题覆盖签名。

## 十二个高级领域审查

| 领域 | 方法树审查 | 关键前置条件 | 主要错误/反例门 | 兼容检查与结论 |
|---|---|---|---|---|
| Abstract Algebra | 按群、环、域结构先分类，再选同态、商结构、分解或计数不变量 | 同态定义域/陪域、正规性、理想、有限性、域特征 | 非正规子群误作商群、把整环当域、忽略特征；用小阶群与零因子反例 | theorem/precondition、symbolic、finite enumeration；通过 |
| Advanced Linear Algebra | 先判断谱、Jordan/最小多项式、二次型或秩空间，再选不变量 | 基域、有限维、可对角化条件、内积/对称性 | 特征多项式与最小多项式混淆、几何重数遗漏、相似与合同混淆 | symbolic、rank、spectral、boundary；通过 |
| Advanced Real Analysis | 先解析量词与收敛模式，再选择 ε–δ、紧致性、控制收敛或估计 | 一致/逐点收敛区别、紧致性、可测性、支配函数与可积性 | 非一致收敛误交换极限、端点遗漏、无支配函数；检查边界层反例 | symbolic、numerical sanity、theorem/precondition、boundary；通过 |
| Complex Analysis | 按解析性、奇点、围道、零点或整函数增长选择 Cauchy、留数、Rouché 等 | 区域单连通、围道方向、奇点位置、边界无零点、增长条件 | 留数符号、边界零点、分支切割、无穷远点分类错误 | symbolic residue、contour orientation、theorem/precondition；通过 |
| Functional Analysis | 先区分空间几何、泛函、算子谱和收敛，再选 Hahn–Banach/Riesz/谱方法 | Banach/Hilbert、算子有界性、定义域稠密性、闭性 | 无界算子误套有界谱论、范数与弱收敛混淆、伴随定义域遗漏 | theorem/precondition、norm bound、spectral sanity；通过 |
| Measure and Integration | 先判非负/绝对可积，再选 Tonelli、Fubini、MCT、DCT 或变量代换 | 可测性、σ-有限性、非负性或绝对可积、支配函数 | 在条件不满足时交换积分/极限、忽略零测集、把点态界当可积支配 | theorem/precondition、boundary、symbolic/numerical integral；通过 |
| Ordinary Differential Equations | 按可分离、线性、精确、降阶、系统或定性方法分流 | 连续性、局部 Lipschitz、初值所在区间、最高阶系数非零 | 通解丢失奇解、除零、最大存在区间遗漏、重复根形式错误 | substitution、initial-condition、residual、boundary；通过 |
| Partial Differential Equations | 先识别椭圆/抛物/双曲型和边初条件，再选分离变量、能量或变换 | 区域正则性、边界条件兼容、解的正则性、谱基完备性 | 初边值不兼容、符号/特征值号错、无正则性即分部积分 | PDE residual、boundary/initial、energy identity、theorem；通过 |
| Stochastic Processes | 先按 Markov、Poisson、Brownian、鞅或停时分流 | 过滤、适应性、独立增量、可积性、停时与可选停止条件 | 无条件使用独立性、把参数率混为均值、无界停时直接可选停止 | distribution、conditioning、transition matrix、boundary；通过 |
| Operations Research | 先识别 LP/对偶、网络流、最短路、指派或零和博弈 | 原/对偶可行性、有界性、容量非负、图方向、博弈策略单纯形 | 对偶不等号方向、强对偶条件遗漏、负边权误用 Dijkstra | primal-dual certificate、flow conservation、enumeration；通过 |
| Regression | 按 OLS、投影、诊断、岭回归或预测分流 | 设计矩阵维数与秩、误差条件、正则参数、可识别性 | 把相关当因果、全秩假设遗漏、残差/误差混淆、杠杆公式符号错 | matrix identity、normal equation、residual、dimension；通过 |
| Differential Geometry | 先辨曲线/曲面、第一/第二基本形式、曲率或整体定理 | 参数化正则、光滑性、定向、度量正定、边界条件 | 法向方向导致符号变化、坐标奇点、局部公式误作全局结论 | symbolic tensor、regularity、orientation、special-point check；通过 |

## 六个通用 Skill 审查

| Skill | 动态触发 | 角色边界 | 审查结论 |
|---|---|---|---|
| answer-normalization | 所有 Route | Solver、Repair、Finalizer | 保留精确值、集合/向量顺序约定和最终答案格式；通过 |
| counterexample-search | medium/high risk | VerifierSkeptic | 只挑战公开 Claim 和条件，不生成替代私有推理；通过 |
| lemma-compression | high-risk proof/derivation | LemmaCurator | 只压缩问题内可复验 Lemma，保留条件和依赖；通过 |
| numerical-stability | 数值领域或误差/条件数触发 | Solver、Verifier | 区分截断误差、舍入误差、条件性与算法稳定性；通过 |
| proof-obligation | proof/derivation | Solver、Lemma、Verifier、Repair | 要求必要性、充分性、边界和定理条件闭合；通过 |
| symbolic-equivalence | expression/polynomial | Solver、Verifier | 区分形式相等、定义域相等和数值抽样证据；通过 |

## 路由与角色边界审查

- 29 个生产领域 Skill 与 Router 的 29 个 Subject 一一对应；
- 每个 Subject 都有三个互异、非空的 MethodFamily；
- Domain Skill 与 General Skill 均按固定角色白名单注入；
- Verifier 优先获得 counterexample/proof guidance，Finalizer 获得答案规范化，
  LemmaCurator 获得 lemma compression；
- 未命中专门领域时 Route 标记 `general_math_fallback` 并至少提升为 medium risk；
- `parser_confidence < 0.70` 时 Route 标记 `low_parser_confidence` 并提升风险；
- Trace 保存路由置信度、触发原因、按角色实际注入的 Skill、整块省略项与未知项；
- Trace 不保存私有推理文本、密钥、绝对路径或被截断的 Skill 内容。

## 待人类专家确认

以下项目不会在工程审查中被冒充为已完成：

- 高阶定理的全部边界条件和中文术语最终签名；
- Intern-S2-Preview-397B 在每个高级领域对 Skill 指令的真实遵循率；
- 竞赛分布变化后的 Router/Skill 漂移复核；
- `content_review_manifest.json` 的 `human_signatures`。

