from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mathforge.agents.registry import PromptContractLoader, SkillRegistry
from mathforge.evaluation.evidence_baseline import (
    extract_local_final_corpus,
    parse_official_evaluation_log,
    regression_case_snapshot,
    sha256_file,
)


DEFAULT_OUTPUT = ROOT / "data" / "evidence"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def build(run_directory: Path, official_log: Path, output: Path) -> None:
    local = extract_local_final_corpus(run_directory)
    official_bytes = official_log.read_bytes()
    official_text = official_bytes.decode("utf-8")
    official = {
        "schema_version": "1.0",
        "source_log": official_log.name,
        "source_log_sha256": sha256(official_bytes).hexdigest(),
        "metrics": parse_official_evaluation_log(official_text),
    }
    _write_json(output / "local88" / "final_corpus.json", local)
    _write_json(
        output / "local88" / "regression_cases.json",
        {
            "schema_version": "1.0",
            "cases": [
                regression_case_snapshot(run_directory, local, 7),
                regression_case_snapshot(run_directory, local, 77),
            ],
        },
    )
    (output / "official112").mkdir(parents=True, exist_ok=True)
    (output / "official112" / official_log.name).write_bytes(official_bytes)
    _write_json(output / "official112" / "summary.json", official)

    taxonomy_path = output / "failure_taxonomy.json"
    artifacts = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "baseline_manifest.json":
            artifacts.append(
                {
                    "path": path.relative_to(ROOT).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    run_identity = local["source_manifest"].get("run_contract", {}).get(
        "code_identity", {}
    )
    manifest = {
        "schema_version": "1.0",
        "phase": "0809-phase0",
        "repository_parent_commit": _git_head(),
        "evidence_run_identity": run_identity,
        "config_sha256": local["source_manifest"].get("config_sha256", ""),
        "prompt_sha256": PromptContractLoader().fingerprint,
        "skill_sha256": SkillRegistry().fingerprint,
        "failure_taxonomy_sha256": sha256_file(taxonomy_path),
        "metric_authority": {
            "attempt_metrics": "diagnostic_only",
            "corpus_metrics": "one_final_record_per_case",
        },
        "required_reproduction": {
            "local_correct": [49, 88],
            "local_all_candidates_failed": 38,
            "local_router_llm_accepted": [0, 88],
            "local_dual_candidate": [10, 88],
            "official_invalid": [92, 112],
            "official_truncated": [444, 657],
        },
        "artifacts": artifacts,
        "privacy": {
            "contains_credentials": False,
            "contains_absolute_paths": False,
            "contains_private_reasoning_transcripts": False,
        },
    }
    _write_json(output / "baseline_manifest.json", manifest)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-run", type=Path, required=True)
    parser.add_argument("--official-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build(args.local_run, args.official_log, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
