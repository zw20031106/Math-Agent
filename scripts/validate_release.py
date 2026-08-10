from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mathforge.governance.release import (  # noqa: E402
    collect_release_readiness,
    evaluate_release_readiness,
)


_TEST_ERROR = "full release test suite has not passed"
_RELEASE_COMMANDS = (
    (sys.executable, "-m", "compileall", "."),
    (sys.executable, "-m", "pytest", "-q"),
    (sys.executable, "scripts/verify_baseline_files.py"),
    (sys.executable, "scripts/verify_content_reviews.py", "--require-human"),
    (sys.executable, "scripts/verify_build_provenance.py"),
    (sys.executable, "scripts/verify_evidence_registry.py"),
    (sys.executable, "scripts/validate_submission.py"),
)


def validate_release(
    *,
    results_root: Path | None,
    run_commands: bool,
) -> list[str]:
    initial = collect_release_readiness(
        ROOT,
        results_root=results_root,
        all_tests_passed=False,
    )
    errors = evaluate_release_readiness(initial)
    static_errors = [error for error in errors if error != _TEST_ERROR]
    if static_errors or not run_commands:
        return errors
    for command in _RELEASE_COMMANDS:
        completed = subprocess.run(command, cwd=ROOT, check=False)
        if completed.returncode != 0:
            return [_TEST_ERROR]
    final = collect_release_readiness(
        ROOT,
        results_root=results_root,
        all_tests_passed=True,
    )
    return evaluate_release_readiness(final)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate evidence-complete Math-Agent release readiness."
    )
    parser.add_argument("--strict", action="store_true")
    parser.add_argument(
        "--results-root",
        type=Path,
        help="Root containing the active registered benchmark evidence tree.",
    )
    args = parser.parse_args()
    if not args.strict:
        print("validate_release requires --strict")
        return 2
    errors = validate_release(
        results_root=args.results_root,
        run_commands=True,
    )
    if errors:
        print("\n".join(errors))
        return 1
    print("Strict release validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
