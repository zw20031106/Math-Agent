"""Build the fail-closed R0 current-HEAD baseline artifact."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mathforge.evaluation.r0 import (  # noqa: E402
    R0_MIN_REPETITIONS,
    build_current_head_baseline,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate comparable repeated benchmark artifacts for R0."
    )
    parser.add_argument(
        "--identity",
        type=Path,
        default=ROOT / "artifacts" / "current_candidate_identity.json",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        required=True,
        help="the exact dataset file used by each repetition",
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        action="append",
        default=[],
        help="one completed benchmark artifact; repeat this option per run",
    )
    parser.add_argument(
        "--min-repetitions",
        type=int,
        default=R0_MIN_REPETITIONS,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "current_head_baseline.json",
    )
    args = parser.parse_args()

    identity_path = _rooted(args.identity)
    dataset_path = _rooted(args.dataset)
    identity = _read_object(identity_path)
    artifacts = [_read_object(_rooted(path)) for path in args.artifact]
    dataset_sha256 = sha256(dataset_path.read_bytes()).hexdigest()
    baseline = build_current_head_baseline(
        artifacts,
        identity=identity,
        dataset_sha256=dataset_sha256,
        min_repetitions=args.min_repetitions,
    )
    output = _rooted(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "status": baseline["status"],
                "valid_repetitions": len(baseline["repetitions"]),
                "required_repetitions": baseline["required_repetitions"],
                "active_baseline_eligible": baseline["active_baseline_eligible"],
            },
            ensure_ascii=False,
        )
    )
    return 0


def _rooted(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
