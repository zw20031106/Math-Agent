from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm_client import InternChatClient  # noqa: E402
from mathforge.agents.registry import PromptContractLoader, SkillRegistry  # noqa: E402
from mathforge.benchmark import (  # noqa: E402
    benchmark_record_to_dict,
    load_jsonl,
    preflight_benchmark_cases,
    run_benchmark,
)
from mathforge.config import HarnessConfig, load_competition_config  # noqa: E402
from mathforge.evaluation.artifacts import finalize_artifact  # noqa: E402
from mathforge.model_identity import (  # noqa: E402
    EXACT_INTERN_MODEL,
    exact_model_identity,
)
from mathforge.provenance import build_run_provenance  # noqa: E402
from mathforge.retrieval.retriever import Retriever  # noqa: E402
from mathforge.runtime import MathForgeHarness  # noqa: E402
from mathforge.tools.registry import ToolRegistry  # noqa: E402


BENCHMARK_SCHEMA_VERSION = "3.4"


def build_benchmark_metadata(
    input_path: Path,
    config_path: Path,
    *,
    requested_model: str = EXACT_INTERN_MODEL,
) -> dict:
    model_identity = exact_model_identity(
        requested_model,
        request_source="argument:--model",
    )
    config = load_benchmark_config(config_path)
    provenance = build_run_provenance(
        config,
        model_identity=model_identity,
        inspect_worktree=True,
    )
    return {
        "benchmark_schema_version": BENCHMARK_SCHEMA_VERSION,
        "dataset_sha256": _file_sha256(input_path),
        "config_sha256": config.fingerprint,
        "config_schema_version": config.schema_version,
        "config_profile": config.profile,
        "config_status": config.status,
        "prompt_sha256": PromptContractLoader().fingerprint,
        "skill_sha256": SkillRegistry().fingerprint,
        "rag_sha256": Retriever().fingerprint,
        "tool_sha256": ToolRegistry().fingerprint,
        "git_commit": provenance.code_commit,
        "code_dirty": provenance.code_dirty,
        **model_identity.to_dict(),
        "run_provenance": provenance.to_dict(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a MathForge ablation benchmark.")
    parser.add_argument("--input", type=Path, required=True, help="JSONL benchmark cases")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "competition.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--model", default=EXACT_INTERN_MODEL)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    model_identity = exact_model_identity(
        args.model,
        request_source="argument:--model",
    )
    config = load_benchmark_config(args.config)
    client = InternChatClient()
    client.model = args.model
    harness = MathForgeHarness(
        client,
        config,
        model_identity=model_identity,
    )
    cases = load_jsonl(args.input)
    preflight = preflight_benchmark_cases(cases)
    records, summary = run_benchmark(
        cases,
        harness.solve,
        concurrency=args.concurrency,
        repetitions=args.repetitions,
        seed=args.seed,
    )
    output = finalize_artifact({
        **build_benchmark_metadata(
            args.input,
            args.config,
            requested_model=args.model,
        ),
        "config": args.config.as_posix(),
        "preflight": preflight.to_dict(),
        "summary": summary,
        "records": [benchmark_record_to_dict(record) for record in records],
    })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def load_benchmark_config(path: Path) -> HarnessConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("benchmark configuration must be a JSON object")
    metadata_fields = {"schema_version", "profile", "status"}
    if metadata_fields <= set(payload):
        return HarnessConfig.from_dict(payload)
    unknown = set(payload) - HarnessConfig.setting_names()
    if unknown:
        raise ValueError(f"unknown ablation configuration keys: {sorted(unknown)}")
    merged = load_competition_config().to_dict()
    merged.update(payload)
    merged["profile"] = f"ablation-{path.stem}"
    merged["status"] = "experiment"
    return HarnessConfig.from_dict(merged)


if __name__ == "__main__":
    raise SystemExit(main())
