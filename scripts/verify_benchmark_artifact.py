from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mathforge.evaluation.artifacts import validate_artifact  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a MathForge benchmark artifact and provenance."
    )
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.artifact.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("Benchmark artifact is unreadable.")
        return 1
    if not isinstance(payload, dict):
        print("Benchmark artifact must be a JSON object.")
        return 1
    errors = validate_artifact(payload)
    if errors:
        print("\n".join(errors))
        return 1
    print("Benchmark artifact verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
