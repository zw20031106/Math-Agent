from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SMOKE_TEST = """
import os

os.environ.pop("INTERN_MODEL", None)
os.environ.pop("INTERN_API_KEY", None)

from user_agent import ReasoningAgent
import json

class FormalSmokeClient:
    def chat(self, *, messages, temperature, max_tokens):
        del temperature, max_tokens
        system = messages[0]["content"]
        user = messages[-1]["content"]
        if system.startswith("You are RouterPlanner"):
            methods = ["direct-deduction", "structural-transform", "constructive-computation"]
            return json.dumps({"primary_subject":"general-math","auxiliary_subject":None,"risk_level":"high","method_families":methods,"subgoals":[{"subgoal_id":"sg-1","objective":"Establish the result","depends_on":[]}],"task_proposals":[{"proposal_id":"p1","agent_role":"PrimarySolver","task_type":"solve_primary","subgoal_ids":["sg-1"],"method_family":methods[0],"priority":100},{"proposal_id":"p2","agent_role":"AlternativeSolver","task_type":"solve_alternative","subgoal_ids":["sg-1"],"method_family":methods[1],"priority":90},{"proposal_id":"p3","agent_role":"AlternativeSolver","task_type":"solve_alternative","subgoal_ids":["sg-1"],"method_family":methods[2],"priority":80}]})
        if system.startswith("You are LemmaCurator"):
            recipient = json.loads(user)["reply_recipient_role"]
            return json.dumps({"protocol_version":"1.0","task_result_type":"LemmaArtifact","action":"complete","public_state_delta":{},"result_payload":{"lemmas":[]},"outbound_intents":[{"recipient_role":recipient}],"progress_summary":"Lemma scan complete.","stop_reason":"lemma_scan_complete"})
        if "Public protocol mode is explore" in system or "Public protocol mode is continue" in system:
            delta = {"public_summary":"Direct arithmetic establishes the result.","strategy":"direct-deduction","subgoals":[],"claims":[],"open_obligations":[],"closed_obligation_ids":[],"contradictions":[],"next_step":"Synthesize.","stop_reason":"ready_for_candidate"}
            return json.dumps({"protocol_version":"1.0","task_result_type":"ProgressArtifact","action":"complete","public_state_delta":delta,"result_payload":{},"outbound_intents":[],"progress_summary":"Exploration complete.","stop_reason":"ready_for_candidate"})
        candidate = {"method":"direct-deduction","final_answer":"2","public_solution_steps":["Evaluate the sum directly: 1+1=2."],"claims":[{"claim_id":"c1","statement":"1+1=2","depends_on":[],"check_type":"symbolic_equivalence","importance":"critical"}],"solution_text":"Adding the two unit quantities gives 1+1=2.","assumptions":[],"theorems":[],"unresolved_obligations":[]}
        if "AgentTurnPayload 1.0" in system:
            return json.dumps({"protocol_version":"1.0","task_result_type":"CandidateArtifact","action":"publish_candidate","public_state_delta":{},"result_payload":candidate,"outbound_intents":[],"progress_summary":"Candidate published.","stop_reason":"candidate_complete"})
        return json.dumps(candidate)

result = ReasoningAgent(FormalSmokeClient()).solve(
    "Calculate the integer 1+1",
    {},
)
assert result["status"] == "success", result
assert "2" in result["final_response"], result
assert isinstance(result["trace"], list), result
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a clean venv, install only from a wheelhouse, and smoke-test."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--wheelhouse", type=Path)
    source.add_argument(
        "--prepare-wheelhouse",
        action="store_true",
        help="Download the lock into a temporary wheelhouse before the offline check.",
    )
    args = parser.parse_args()
    if args.prepare_wheelhouse:
        with tempfile.TemporaryDirectory(
            prefix="mathforge-wheelhouse-"
        ) as temporary:
            wheelhouse = Path(temporary)
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "download",
                    "--dest",
                    str(wheelhouse),
                    "-r",
                    str(ROOT / "requirements-lock.txt"),
                ],
                cwd=ROOT,
                check=True,
            )
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "wheel",
                    "--no-deps",
                    "--wheel-dir",
                    str(wheelhouse),
                    str(ROOT),
                ],
                cwd=ROOT,
                check=True,
            )
            return _verify(wheelhouse)
    assert args.wheelhouse is not None
    wheelhouse = args.wheelhouse.resolve()
    if not wheelhouse.is_dir():
        print("Offline wheelhouse does not exist.")
        return 1
    return _verify(wheelhouse)


def _verify(wheelhouse: Path) -> int:
    with tempfile.TemporaryDirectory(prefix="mathforge-offline-") as temporary:
        environment = Path(temporary) / "venv"
        subprocess.run(
            [sys.executable, "-m", "venv", str(environment)],
            check=True,
        )
        python = (
            environment / "Scripts" / "python.exe"
            if sys.platform == "win32"
            else environment / "bin" / "python"
        )
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--find-links",
                str(wheelhouse),
                "-r",
                str(ROOT / "requirements-lock.txt"),
                "mathforge-agent",
            ],
            cwd=temporary,
            check=True,
        )
        smoke_directory = Path(temporary) / "outside-repository"
        smoke_directory.mkdir()
        subprocess.run(
            [str(python), "-c", SMOKE_TEST],
            cwd=smoke_directory,
            check=True,
        )
    print("Clean offline installation and smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
