from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SMOKE_TEST = """
from user_agent import ReasoningAgent

class OfflineClient:
    def chat(self, *, messages, temperature, max_tokens):
        del messages, temperature, max_tokens
        return '{"method":"offline","solution_text":"1+1=2","final_answer":"2"}'

result = ReasoningAgent(OfflineClient()).solve("Calculate the integer 1+1", {})
assert result["final_response"]
assert result["run_metrics"]["estimated_tokens"] > 0
assert result["provenance"]["schema_version"] == "1.0"
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
            ],
            cwd=ROOT,
            check=True,
        )
        subprocess.run(
            [str(python), "-c", SMOKE_TEST],
            cwd=ROOT,
            check=True,
        )
    print("Clean offline installation and smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
