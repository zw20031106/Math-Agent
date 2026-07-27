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

class FormalSmokeClient:
    def chat(self, *, messages, temperature, max_tokens):
        del messages, temperature, max_tokens
        return '{"method":"direct-deduction","final_answer":"2","public_solution_steps":["Evaluate the sum directly: 1+1=2."],"claims":[{"claim_id":"c1","statement":"1+1=2","depends_on":[],"check_type":"symbolic_equivalence","importance":"critical"}],"method_steps":[{"step_id":"s1","kind":"computation","claim_ids":["c1"],"theorem":""}],"solution_text":"Adding the two unit quantities gives 1+1=2.","assumptions":[],"theorems":[],"unresolved_obligations":[]}'

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
