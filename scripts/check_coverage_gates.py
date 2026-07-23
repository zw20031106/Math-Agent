from __future__ import annotations

import argparse
from io import StringIO
from pathlib import Path

from coverage import Coverage


ROOT = Path(__file__).resolve().parents[1]
MODULE_BRANCH_GATES = {
    "mathforge/runtime.py": 80.0,
    "mathforge/verification/completion.py": 85.0,
    "mathforge/verification/evidence.py": 85.0,
    "mathforge/config.py": 70.0,
    "mathforge/output/deterministic_formatter.py": 70.0,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enforce S4 branch-aware coverage gates for critical modules."
    )
    parser.add_argument("--data-file", type=Path, default=ROOT / ".coverage")
    args = parser.parse_args()

    coverage = Coverage(data_file=str(args.data_file))
    coverage.load()
    if not coverage.get_data().has_arcs():
        print("coverage gate failed: data was not collected with branch coverage")
        return 1

    failures: list[str] = []
    for relative_path, threshold in MODULE_BRANCH_GATES.items():
        path = ROOT / relative_path
        measured = coverage.report(morfs=[str(path)], file=StringIO())
        print(f"{relative_path}: {measured:.2f}% (required {threshold:.2f}%)")
        if measured + 1e-9 < threshold:
            failures.append(
                f"{relative_path} measured {measured:.2f}% below {threshold:.2f}%"
            )
    if failures:
        print("coverage gate failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
