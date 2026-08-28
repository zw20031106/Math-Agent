"""Run one E8 ablation family in interleaved paired repetitions.

The script delegates every model request to the existing benchmark runner and
therefore keeps the injected official client and competition concurrency rules
as the only transport path.  It writes one artifact per arm/repetition and a
recomputable E8 report; a failed child run is recorded rather than converted
into a successful arm.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mathforge.benchmark import benchmark_record_from_dict  # noqa: E402
from mathforge.evaluation.e8 import (  # noqa: E402
    E8_SCHEMA_VERSION,
    ablation_arm_specs,
    summarize_ablation_arms,
    summarize_e8,
    validate_paired_ablation,
)
from mathforge.model_identity import EXACT_INTERN_MODEL  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an E8 paired ablation family.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--family",
        choices=("workflow", "skill", "verification", "prompt"),
        required=True,
    )
    parser.add_argument("--arms", help="comma-separated arm IDs; default is the full family")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--concurrency", type=int, choices=range(1, 4), default=3)
    parser.add_argument("--model", default=EXACT_INTERN_MODEL)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    if args.model != EXACT_INTERN_MODEL:
        parser.error(f"--model must be exactly {EXACT_INTERN_MODEL}")

    specs = ablation_arm_specs(args.family)
    selected_ids = (
        tuple(item.strip() for item in args.arms.split(",") if item.strip())
        if args.arms
        else tuple(spec.arm_id for spec in specs)
    )
    known = {spec.arm_id for spec in specs}
    unknown = sorted(set(selected_ids) - known)
    if len(selected_ids) < 2:
        parser.error("E8 paired ablation requires at least two arms")
    if unknown:
        parser.error("unknown arms: " + ", ".join(unknown))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    execution_order: list[str] = []
    run_rows: list[dict[str, Any]] = []
    records_by_arm: dict[str, list[Any]] = {arm_id: [] for arm_id in selected_ids}
    child_runs: list[dict[str, Any]] = []
    for repetition in range(args.repetitions):
        for arm_id in selected_ids:
            spec = next(item for item in specs if item.arm_id == arm_id)
            execution_order.append(arm_id)
            destination = (
                args.output_dir
                / args.family
                / arm_id
                / f"repetition-{repetition + 1:02d}.json"
            )
            child = {
                "arm_id": arm_id,
                "family": args.family,
                "repetition": repetition,
                "artifact": destination.as_posix(),
                "config": spec.config_path,
                "status": "planned",
            }
            if destination.exists() and not args.resume and not args.dry_run:
                child["status"] = "refused_existing_artifact"
                child_runs.append(child)
                continue
            if not args.dry_run:
                command = [
                    sys.executable,
                    str(ROOT / "scripts" / "run_benchmark.py"),
                    "--input",
                    str(args.input),
                    "--config",
                    str(ROOT / spec.config_path),
                    "--output",
                    str(destination),
                    "--concurrency",
                    str(args.concurrency),
                    "--model",
                    args.model,
                    "--repetitions",
                    "1",
                    "--seed",
                    str(args.seed),
                ]
                if args.family == "prompt":
                    command.extend(["--prompt-variant", arm_id])
                started = perf_counter()
                completed = subprocess.run(
                    command,
                    cwd=ROOT,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                child["elapsed_seconds"] = round(perf_counter() - started, 6)
                child["returncode"] = completed.returncode
                child["status"] = "completed" if completed.returncode == 0 else "failed"
                if destination.exists():
                    try:
                        artifact = json.loads(destination.read_text(encoding="utf-8"))
                    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                        artifact = None
                    if isinstance(artifact, dict) and isinstance(artifact.get("records"), list):
                        for payload in artifact["records"]:
                            try:
                                record = benchmark_record_from_dict(payload)
                            except (TypeError, ValueError, KeyError):
                                continue
                            records_by_arm[arm_id].append(
                                replace(record, repetition_index=repetition)
                            )
                            run_rows.append(
                                {
                                    "arm_id": arm_id,
                                    "case_id": record.case.idx,
                                    "repetition_index": repetition,
                                    "run_metrics": record.run_metrics.to_dict(),
                                }
                            )
            child_runs.append(child)

    validation = validate_paired_ablation(
        args.family,
        {
            arm_id: [row for row in run_rows if row["arm_id"] == arm_id]
            for arm_id in selected_ids
        },
        execution_order=execution_order,
    )
    payload: dict[str, Any] = {
        "schema_version": E8_SCHEMA_VERSION,
        "family": args.family,
        "input": str(args.input),
        "repetitions": args.repetitions,
        "seed": args.seed,
        "execution_order": execution_order,
        "arms": [spec.to_dict() for spec in specs if spec.arm_id in selected_ids],
        "child_runs": child_runs,
        "validation": validation.to_dict(),
        "arm_summaries": {
            arm_id: summarize_e8(records_by_arm[arm_id])
            for arm_id in selected_ids
            if records_by_arm[arm_id]
        },
        "paired": summarize_ablation_arms(
            args.family,
            records_by_arm,
            execution_order=execution_order,
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    destination = args.output_dir / f"e8_{args.family}_report.json"
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(validation.to_dict(), ensure_ascii=False, indent=2))
    return 0 if validation.valid or args.dry_run else 1


if __name__ == "__main__":
    raise SystemExit(main())
