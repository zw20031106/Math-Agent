from __future__ import annotations

import json
import sys

from mathforge.tools.registry import run_tool_direct


def main() -> int:
    try:
        request = json.loads(sys.stdin.read())
        result = run_tool_direct(str(request["name"]), dict(request.get("arguments", {})))
        sys.stdout.write(json.dumps(result.to_dict(), ensure_ascii=False))
        return 0
    except Exception as error:
        sys.stdout.write(json.dumps({"error": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
