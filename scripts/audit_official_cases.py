from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mathforge.evaluation.official_case_audit import (  # noqa: E402
    audit_official_artifact,
    load_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a fingerprint-bound per-case official evidence audit."
    )
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=ROOT / "data" / "evidence" / "phase0_0824_snapshot.json",
    )
    parser.add_argument("--proof-reviews", type=Path)
    parser.add_argument(
        "--origin",
        choices=("official-platform-export", "local-diagnostic"),
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    reviews = load_json(args.proof_reviews) if args.proof_reviews else {}
    audit = audit_official_artifact(
        load_json(args.artifact),
        load_json(args.snapshot),
        proof_reviews=reviews,
        evidence_origin=args.origin,
        root=ROOT,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(audit["summary"], ensure_ascii=False, indent=2))
    if not audit["active_baseline_eligible"]:
        print(json.dumps(audit["eligibility_errors"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
