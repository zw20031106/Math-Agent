from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mathforge.evaluation.routing import evaluate_router_gold  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate deterministic subject routing on reviewed gold cases."
    )
    parser.add_argument(
        "--gold",
        type=Path,
        default=Path("data/dev_set_2_gold.jsonl"),
    )
    parser.add_argument("--min-top1", type=float, default=0.90)
    parser.add_argument("--min-top2", type=float, default=0.97)
    args = parser.parse_args()

    result = evaluate_router_gold(args.gold)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return int(
        result.case_count != 88
        or result.top1_accuracy < args.min_top1
        or result.top2_accuracy < args.min_top2
        or result.general_top1_count != 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
