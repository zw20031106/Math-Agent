from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_baseline_files import verify  # noqa: E402
from mathforge.config import load_competition_config  # noqa: E402
from mathforge.governance.reviews import validate_review_manifest  # noqa: E402
from user_agent import ReasoningAgent  # noqa: E402


_FORBIDDEN_IMPORTS = re.compile(r"^\s*(?:from|import)\s+(openai|anthropic|httpx|socket|urllib)", re.M)
_WINDOWS_ABSOLUTE = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]")


class OfflineClient:
    def chat(self, *, messages, temperature, max_tokens) -> str:
        del messages, temperature, max_tokens
        return '{"method":"offline","solution_text":"1+1=2","final_answer":"2"}'


def validate(max_file_mb: float = 5.0) -> list[str]:
    errors = verify()
    errors.extend(
        validate_review_manifest(
            ROOT / "docs" / "content_review_manifest.json",
            require_human=False,
        )
    )
    try:
        result = ReasoningAgent(client=OfflineClient()).solve("Calculate the integer 1+1", {})
        json.dumps(result)
        if not isinstance(result.get("trace"), list):
            errors.append("trace is not a list")
        if not str(result.get("final_response", "")).strip():
            errors.append("final_response is empty")
    except Exception as error:
        errors.append(f"public interface failed: {type(error).__name__}")

    scan_paths = [ROOT / "mathforge", ROOT / "user_agent.py"]
    for scan_path in scan_paths:
        files = scan_path.rglob("*.py") if scan_path.is_dir() else [scan_path]
        for path in files:
            text = path.read_text(encoding="utf-8")
            relative = path.relative_to(ROOT).as_posix()
            if _FORBIDDEN_IMPORTS.search(text):
                errors.append(f"forbidden online dependency: {relative}")
            if _WINDOWS_ABSOLUTE.search(text):
                errors.append(f"hard-coded absolute path: {relative}")

    limit = int(max_file_mb * 1024 * 1024)
    for path in ROOT.rglob("*"):
        if path.is_file() and ".git" not in path.parts and path.stat().st_size > limit:
            errors.append(f"oversized file: {path.relative_to(ROOT).as_posix()}")
    return errors


def validation_warnings() -> list[str]:
    config = load_competition_config()
    warnings: list[str] = []
    if config.status == "candidate-unvalidated":
        warnings.append(
            "WARNING: competition config is candidate-unvalidated; "
            "benchmark evidence has not frozen it."
        )
    review_manifest = json.loads(
        (ROOT / "docs" / "content_review_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    if review_manifest.get("status") != "human-approved":
        warnings.append(
            "WARNING: mathematical content has engineering review only; "
            "human signatures are still required before freezing."
        )
    return warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a Math-Agent competition submission.")
    parser.add_argument("--max-file-mb", type=float, default=5.0)
    args = parser.parse_args()
    for warning in validation_warnings():
        print(warning)
    errors = validate(args.max_file_mb)
    if errors:
        print("\n".join(errors))
        return 1
    print("Submission validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
