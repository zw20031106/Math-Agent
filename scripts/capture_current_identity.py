"""Capture the public reproducibility identity for the current candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mathforge.evaluation.r0 import capture_current_candidate_identity  # noqa: E402
from mathforge.model_identity import EXACT_INTERN_MODEL  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture the current candidate identity without making model calls."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config" / "competition.json",
        help="authoritative competition configuration",
    )
    parser.add_argument(
        "--model",
        default=EXACT_INTERN_MODEL,
        help="exact callable Intern model ID",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "current_candidate_identity.json",
    )
    args = parser.parse_args()

    identity = capture_current_candidate_identity(
        ROOT,
        config_path=_rooted(args.config),
        requested_model=args.model,
    )
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(identity, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output), "git_commit": identity["git_commit"]}))
    return 0


def _rooted(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
