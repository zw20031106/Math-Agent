from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from mathforge.tools.registry import ToolResult


class StdioMCPAdapter:
    def __init__(self, timeout: float = 5.0) -> None:
        self._timeout = timeout
        self._repo_root = Path(__file__).resolve().parents[2]

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> ToolResult:
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        completed = subprocess.run(
            [sys.executable, "-m", "mathforge.tools.mcp_server"],
            input=json.dumps(request, ensure_ascii=False) + "\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=self._repo_root,
            timeout=(
                self._timeout
                if timeout is None
                else min(self._timeout, max(0.001, timeout))
            ),
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError("MCP process failed")
        line = next((line for line in completed.stdout.splitlines() if line.strip()), "")
        response = json.loads(line)
        if "error" in response:
            raise RuntimeError("MCP protocol error")
        payload = response["result"]["structuredContent"]
        return ToolResult(
            tool_name=str(payload["tool_name"]),
            status=str(payload["status"]),
            strength=str(payload["strength"]),
            summary=str(payload["summary"]),
            payload=dict(payload.get("payload", {})),
            tool_version=str(payload.get("tool_version", "1")),
            capability=str(payload.get("capability", "none")),
            claim_state=str(payload.get("claim_state", "unknown")),
        )
