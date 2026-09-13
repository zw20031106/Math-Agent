"""Regenerate the checked-in compiled-prompt golden snapshots.

This is intentionally a small, deterministic maintenance script.  It mirrors
the representative role/mode matrix exercised by
``tests/test_e2_prompt_structured_output.py`` after a prompt-contract change.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mathforge.agents.prompt_compiler import PromptCompiler
from mathforge.agents.router_planner import RouterRuleEngine
from mathforge.parsing.problem_parser import ProblemParser
from mathforge.agent_runtime.protocol import LITE_PROTOCOL_SCHEMA_VERSION


FIXTURE = ROOT / "tests" / "fixtures" / "e2_compiled_prompt_snapshots.json"


def main() -> None:
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    problem = ProblemParser().parse("Compute 2+2.")
    route = RouterRuleEngine().plan(problem)
    compiler = PromptCompiler()
    common = "Problem: Compute 2+2.\n# Skill: general-math\nPublic state: none"
    current = {}
    for role in (
        "router_planner",
        "lemma_curator",
        "verifier_skeptic",
        "repair",
        "finalizer",
    ):
        current[f"{role}:role"] = compiler.compile_role(
            role,
            user_content=common,
        ).snapshot().to_dict()
    for role in ("primary_solver", "alternative_solver"):
        current[f"{role}:candidate-lite"] = compiler.compile_solver(
            role,
            problem=problem,
            route=route,
            user_content=common,
            autonomous=True,
            protocol_variant=LITE_PROTOCOL_SCHEMA_VERSION,
            semantic_payload=True,
        ).snapshot().to_dict()
        current[f"{role}:progress-lite"] = compiler.compile_solver_progress(
            role,
            problem=problem,
            route=route,
            user_content=common,
            mode="explore",
            autonomous=True,
            protocol_variant=LITE_PROTOCOL_SCHEMA_VERSION,
        ).snapshot().to_dict()

    fields = (
        "role_directory",
        "profile",
        "protocol_version",
        "contract_version",
        "contract_sha256",
        "prompt_sha256",
        "output_schema_name",
        "output_schema_fields",
        "selected_skill_summary",
        "max_output_cap",
    )
    regenerated = {
        key: {field: current[key][field] for field in fields}
        for key in expected
    }
    FIXTURE.write_text(
        json.dumps(regenerated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"updated {len(regenerated)} prompt snapshots: {FIXTURE}")


if __name__ == "__main__":
    main()
