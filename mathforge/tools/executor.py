from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from mathforge.tools.registry import ToolRegistry, ToolResult, run_tool_direct
from typing import Protocol


class MCPAdapter(Protocol):
    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult: ...


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry | None = None,
        default_timeout: float = 3.0,
        *,
        use_mcp: bool = False,
        mcp_adapter: MCPAdapter | None = None,
    ) -> None:
        self._registry = registry or ToolRegistry()
        self._default_timeout = default_timeout
        self._repo_root = Path(__file__).resolve().parents[2]
        self._use_mcp = use_mcp
        if use_mcp and mcp_adapter is None:
            from mathforge.tools.mcp_adapter import StdioMCPAdapter

            mcp_adapter = StdioMCPAdapter(timeout=max(1.0, default_timeout + 1.0))
        self._mcp_adapter = mcp_adapter

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> ToolResult:
        if self._use_mcp and self._mcp_adapter is not None:
            try:
                return self._mcp_adapter.execute(name, dict(arguments))
            except Exception as adapter_error:
                del adapter_error
        try:
            definition = self._registry.get(name)
        except KeyError:
            return ToolResult(name, "error", "soft", "tool is not registered", {})
        if not definition.isolated:
            try:
                return run_tool_direct(name, dict(arguments))
            except Exception as error:
                return ToolResult(name, "error", "soft", f"tool failed: {type(error).__name__}", {})
        request = json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False)
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "mathforge.tools.worker"],
                input=request,
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=self._repo_root,
                timeout=self._default_timeout if timeout is None else timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(name, "unknown", "soft", "tool timed out", {})
        if completed.returncode != 0:
            return ToolResult(name, "error", "soft", "isolated tool failed", {})
        try:
            payload = json.loads(completed.stdout)
            return ToolResult(
                name,
                str(payload["status"]),
                str(payload["strength"]),
                str(payload["summary"]),
                dict(payload.get("payload", {})),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return ToolResult(name, "error", "soft", "invalid isolated tool response", {})
