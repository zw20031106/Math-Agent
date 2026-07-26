from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mathforge.evaluation.evidence_registry import (  # noqa: E402
    load_evidence_registry,
    validate_evidence_registry,
    validate_registered_trees,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate explicit benchmark-evidence eligibility and fingerprints."
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=ROOT / "data" / "evaluation_evidence_registry.json",
    )
    parser.add_argument(
        "--results-root",
        type=Path,
        help="Optional local results root used to verify registered tree fingerprints.",
    )
    args = parser.parse_args()
    try:
        registry = load_evidence_registry(args.registry)
    except (OSError, UnicodeDecodeError, ValueError):
        print("Evidence registry is unreadable.")
        return 1
    errors = validate_evidence_registry(registry)
    if args.results_root is not None and not errors:
        errors.extend(validate_registered_trees(registry, args.results_root))
    if errors:
        print("\n".join(errors))
        return 1
    print("Evidence registry verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
