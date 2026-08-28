"""Validate the E8 freeze gate from an explicit evidence JSON object."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mathforge.evaluation.e8 import evaluate_freeze_gate  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the E8 competition freeze gate.")
    parser.add_argument("evidence", type=Path, help="JSON with engineering/architecture/summary")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.evidence.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        print(f"evidence is unreadable: {type(error).__name__}")
        return 1
    if not isinstance(payload, dict):
        print("evidence must be a JSON object")
        return 1
    result = evaluate_freeze_gate(
        engineering=payload.get("engineering", {}),
        architecture=payload.get("architecture", {}),
        summary=payload.get("summary", {}),
        ablation_validation=payload.get("ablation_validation"),
        baseline_accuracy=payload.get("baseline_accuracy"),
        human_review=bool(payload.get("human_review", False)),
        required_repetitions=int(payload.get("required_repetitions", 3)),
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.eligible or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
