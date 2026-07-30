from __future__ import annotations

import json
import sys
from typing import Any

from mathforge.tools.executor import ToolExecutor
from mathforge.tools.registry import ToolRegistry


class StdioMCPServer:
    def __init__(self) -> None:
        self._registry = ToolRegistry()
        self._executor = ToolExecutor(use_mcp=False)

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        request_id = request.get("id")
        method = request.get("method")
        result: dict[str, Any]
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "mathforge-local-tools", "version": "1.0"},
            }
        elif method == "tools/list":
            result = {"tools": self._registry.mcp_schemas()}
        elif method == "tools/call":
            parameters = request.get("params", {})
            name = str(parameters.get("name", ""))
            arguments = parameters.get("arguments", {})
            if not isinstance(arguments, dict):
                return self._error(request_id, -32602, "tool arguments must be an object")
            try:
                model_claimable = self._registry.is_model_claimable(name)
            except KeyError:
                model_claimable = False
            if not model_claimable:
                return self._error(request_id, -32602, "tool is not model-callable")
            tool_result = self._executor.execute(name, arguments)
            structured = tool_result.to_dict()
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(structured, ensure_ascii=False),
                    }
                ],
                "structuredContent": structured,
                "isError": tool_result.status == "error",
            }
        else:
            return self._error(request_id, -32601, "method not found")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }


def main() -> int:
    server = StdioMCPServer()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            response = server.handle(request)
        except Exception as error:
            response = StdioMCPServer._error(None, -32603, type(error).__name__)
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
