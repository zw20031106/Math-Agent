# External Skill source audit

This record is part of Phase S4. The entries identify the external knowledge
sources used for method selection and workflow ideas. The executable Skill
files in this repository are original MathForge V3 rewrites: they do not copy
source frontmatter, prompts, commands, runtime directives, or tool invocations.

| Source | File URL | Resolved revision | License status | Concepts retained and rewritten |
| --- | --- | --- | --- | --- |
| `parcadei/Continuous-Claude-v3` | [math-progress-monitor/SKILL.md](https://github.com/parcadei/Continuous-Claude-v3/blob/main/.claude/skills/math/math-progress-monitor/SKILL.md) | `d07ff4b06b62f43771bc0c927d0211b734d6149e` | MIT License (repository `LICENSE` at the resolved revision) | Public-state inventory, learning extraction, complexity assessment, spot checks, decomposition, sunk-cost awareness; rewritten as `strategy-progress-assessment` and deterministic Host recommendations. |
| `parcadei/Continuous-Claude-v3` | [root-finding/SKILL.md](https://github.com/parcadei/Continuous-Claude-v3/blob/main/.claude/skills/math/numerical-methods/root-finding/SKILL.md) | `d07ff4b06b62f43771bc0c927d0211b734d6149e` | MIT License (repository `LICENSE` at the resolved revision) | Bracket/regularity/multiplicity decision tree; rewritten to use `numerical_residual` only as finite-sample support and to require mathematical existence and error obligations. |
| `parcadei/Continuous-Claude-v3` | [proof-theory/SKILL.md](https://github.com/parcadei/Continuous-Claude-v3/blob/main/.claude/skills/math/mathematical-logic/proof-theory/SKILL.md) | `d07ff4b06b62f43771bc0c927d0211b734d6149e` | MIT License (repository `LICENSE` at the resolved revision) | Proof dependencies, structural induction, soundness/completeness distinctions, and step auditing; rewritten as `proof-theory` without claiming a proof kernel. |
| `Tibsfox/gsd-skill-creator` | [proof-techniques/SKILL.md](https://github.com/Tibsfox/gsd-skill-creator/blob/main/examples/skills/math/proof-techniques/SKILL.md) | `e179dfe911f3b3c2ff8bcd90ecd6ee4738648d17` | MariaDB-derived license text in repository `LICENSE`; redistribution requires retaining its terms and reviewing compatibility | Direct, contrapositive, contradiction, cases/WLOG, existence/uniqueness, induction, counterexample, and invariant ideas; split into five small MathForge Skills with explicit obligations. |
| `trailofbits/skills` | [writing-lean-proofs/SKILL.md](https://github.com/trailofbits/skills/blob/main/plugins/writing-lean-proofs/skills/writing-lean-proofs/SKILL.md) | `321ccfe628eca0d314b0ee4eaffcdd8a05639aaf` | CC BY-SA 4.0 (repository `LICENSE` at the resolved revision) | Statement-first, design top-down, prove bottom-up, small goals, and compiler-evidence discipline; rewritten as `lean-proof-workflow` and explicitly marked unsupported when no Lean Host capability is configured. |

## Transformation controls

- Source material was used for mathematical method inventory only. The
  package frontmatter and section prose were authored for the MathForge V3
  schema and current fixed roles.
- Claude-specific interaction, `Bash`, `Read`, SciPy/Z3 commands, external
  runtimes, and tools absent from `ToolRegistry` were removed. Verification
  hooks name only current MathForge tools and state their maximum claim scope.
- Numerical residuals, formula normalization, finite enumeration, and syntax
  parsing are recorded as supporting evidence or bounded checks; none is
  promoted to universal proof or Lean kernel acceptance.
- License status is recorded at the resolved revisions above. A release that
  redistributes these rewrites must retain the applicable notices and complete
  the repository's provenance/release review.
