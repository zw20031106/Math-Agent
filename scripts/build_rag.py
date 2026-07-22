from __future__ import annotations

import argparse
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mathforge.retrieval.builder import build_database, load_cards  # noqa: E402


def main() -> int:
    root = _ROOT
    parser = argparse.ArgumentParser(description="Build the offline MathForge FTS5 database.")
    parser.add_argument("--source", type=Path, default=root / "data" / "knowledge_cards.json")
    parser.add_argument("--output", type=Path, default=root / "data" / "math_knowledge.sqlite")
    args = parser.parse_args()
    cards = load_cards(args.source)
    build_database(args.output, cards)
    print(f"Built {args.output} with {len(cards)} reviewed cards.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
