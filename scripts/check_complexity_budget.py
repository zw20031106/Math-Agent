"""对 ``mathforge`` Python 源码执行可重复的复杂度行数门禁。"""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MATHFORGE_ROOT = ROOT / "mathforge"
# 这是 CI 复杂度政策，不是运行时配置；运行时参数仍以 competition.json 为准。
MAX_MATHFORGE_SOURCE_LINES = 55_000


def count_source_lines(root: Path = MATHFORGE_ROOT) -> int:
    """统计非空 Python 源码行，忽略缓存目录和生成文件。"""

    total = 0
    for path in sorted(root.rglob("*.py")):
        if any(part in {"__pycache__", ".pytest_cache"} for part in path.parts):
            continue
        total += sum(bool(line.strip()) for line in path.read_text(encoding="utf-8").splitlines())
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 mathforge 源码行数上限")
    parser.add_argument("--root", type=Path, default=MATHFORGE_ROOT)
    parser.add_argument("--max-lines", type=int, default=MAX_MATHFORGE_SOURCE_LINES)
    args = parser.parse_args()
    actual = count_source_lines(args.root)
    print(f"mathforge_nonblank_python_lines={actual}; ceiling={args.max_lines}")
    return 0 if actual <= args.max_lines else 1


if __name__ == "__main__":
    raise SystemExit(main())
