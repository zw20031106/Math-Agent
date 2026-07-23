from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mathforge.governance.reviews import validate_review_manifest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify MathForge content hashes and review signatures."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "docs" / "content_review_manifest.json",
    )
    parser.add_argument("--require-human", action="store_true")
    args = parser.parse_args()
    errors = validate_review_manifest(
        args.manifest,
        require_human=args.require_human,
    )
    if errors:
        print("\n".join(errors))
        return 1
    print("Content review manifest verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
