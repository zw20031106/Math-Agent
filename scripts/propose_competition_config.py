from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


def build_proposal(
    profile: dict[str, Any],
    config: dict[str, Any],
    *,
    frozen_lemma_records: int,
) -> dict[str, Any]:
    failures: list[str] = []
    if profile.get("output_coverage") != 1.0:
        failures.append("output_coverage_below_100_percent")
    if profile.get("success_rate", 0.0) < 0.98:
        failures.append("case_success_rate_below_98_percent")
    dispatch = profile.get("model_dispatch", {})
    if not isinstance(dispatch, dict) or dispatch.get("success_rate", 0.0) < 0.98:
        failures.append("model_dispatch_success_rate_below_98_percent")
    if profile.get("candidate_acceptance_rate", 0.0) < 0.95:
        failures.append("candidate_acceptance_rate_below_95_percent")
    if profile.get("health_trace_completeness") != 1.0:
        failures.append("health_trace_incomplete")
    if profile.get("calls_per_case", {}).get("max", 0) > 6:
        failures.append("per_case_model_call_limit_exceeded")
    if profile.get("latency_seconds", {}).get("max", 0.0) > 900:
        failures.append("per_case_deadline_exceeded")

    changes: list[dict[str, Any]] = []
    if frozen_lemma_records == 0 and config.get(
        "enable_frozen_lemma_store"
    ) is not False:
        changes.append(
            {
                "field": "enable_frozen_lemma_store",
                "current": config.get("enable_frozen_lemma_store"),
                "proposed": False,
                "reason": "no reviewed frozen lemma records are available",
            }
        )
    return {
        "schema_version": "1.0",
        "freeze_eligible": not failures,
        "competition_status": {
            "current": config.get("status", ""),
            "proposed": (
                "live-validated" if not failures else "candidate-unvalidated"
            ),
        },
        "failed_gates": failures,
        "proposed_changes": changes,
        "hold_constant": [
            "max_model_calls",
            "model_max_concurrency",
            "deadline profile",
            "prompt and skill contracts",
        ],
        "next_action": (
            "complete human review and 16/88 live gates before freezing"
            if not failures
            else "stop scale-up and resolve canary transport reliability"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--frozen-lemma-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    config = json.loads(args.config.read_text(encoding="utf-8"))
    lemma_manifest = json.loads(
        args.frozen_lemma_manifest.read_text(encoding="utf-8")
    )
    proposal = build_proposal(
        profile,
        config,
        frozen_lemma_records=int(lemma_manifest.get("record_count", 0)),
    )
    proposal["profile_sha256"] = sha256(args.profile.read_bytes()).hexdigest()
    proposal["config_sha256"] = sha256(args.config.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(proposal, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(proposal, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
