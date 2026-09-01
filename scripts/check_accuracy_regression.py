"""运行固定 30 题准确率回归门禁。

``--responses`` 可以是 ``{case_id: final_response}`` JSON，也可以是包含逐题
公共结果 JSON 的目录；目录模式直接消费 ``run_case_outputs.py`` 产物，避免
用内部候选计数冒充端到端数学准确率。脚本故意要求显式传入基线，不读取旧
日志猜测基线。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mathforge.evaluation.accuracy_gate import (  # noqa: E402
    DEFAULT_MAX_DROP,
    evaluate_accuracy_regression,
    load_golden_set,
)


def _load_responses(path: Path) -> dict[str, str]:
    """读取映射文件或逐题公共结果目录。"""

    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    if not files:
        raise ValueError("responses directory contains no JSON files")
    responses: dict[str, str] = {}
    for source in files:
        payload = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in payload.items()
        ):
            responses.update(payload)
            continue
        if not isinstance(payload, dict):
            raise ValueError(f"response file must contain an object: {source.name}")
        case_id = str(payload.get("id", payload.get("case_id", ""))).strip()
        final_response = payload.get("final_response")
        if not case_id or not isinstance(final_response, str):
            if source.name == "run_manifest.json":
                continue
            raise ValueError(f"public response is missing id/final_response: {source.name}")
        if case_id in responses:
            raise ValueError(f"duplicate response case_id: {case_id}")
        responses[case_id] = final_response
    return responses


def main() -> int:
    parser = argparse.ArgumentParser(description="检查固定题集准确率是否回归")
    parser.add_argument(
        "--golden-set",
        type=Path,
        default=ROOT / "data" / "evidence" / "local88" / "golden30.jsonl",
    )
    parser.add_argument("--responses", type=Path, required=True)
    parser.add_argument("--baseline-accuracy", type=float, required=True)
    parser.add_argument("--max-drop", type=float, default=DEFAULT_MAX_DROP)
    args = parser.parse_args()

    try:
        payload = _load_responses(args.responses)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error
    report = evaluate_accuracy_regression(
        load_golden_set(args.golden_set),
        payload,
        baseline_accuracy=args.baseline_accuracy,
        max_drop=args.max_drop,
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
