from __future__ import annotations

"""Run the Phase S5 Skill selection audit and optional real-run ablation."""

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mathforge.skills.s5_benchmark import (  # noqa: E402
    S5_DEFAULT_CASE_PATH,
    run_s5_benchmark,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic Phase S5 Skill selection and paired ablation checks."
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=S5_DEFAULT_CASE_PATH,
        help="Versioned S5 case taxonomy JSON",
    )
    parser.add_argument(
        "--ablation-records",
        type=Path,
        help="JSON array/object containing paired observed ON/OFF rows",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON report destination")
    args = parser.parse_args()

    records = _load_records(args.ablation_records) if args.ablation_records else None
    report = run_s5_benchmark(args.cases, ablation_records=records)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    # A missing real-model ablation is an explicit pending state, not a CLI
    # error. Invalid observed rows still fail closed with a non-zero exit.
    return 0


def _load_records(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("records"), list):
        rows = payload["records"]
    else:
        raise ValueError("ablation records must be a JSON array or an object.records array")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("ablation records must contain only JSON objects")
    return [dict(row) for row in rows]


if __name__ == "__main__":
    raise SystemExit(main())
