from __future__ import annotations

from mathforge.tools.executor import ToolExecutor
from mathforge.tools.mcp_adapter import StdioMCPAdapter
from mathforge.tools.mcp_server import StdioMCPServer


def test_mcp_lists_clear_tool_schemas():
    response = StdioMCPServer().handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    tools = response["result"]["tools"]
    assert {tool["name"] for tool in tools} >= {
        "symbolic_equivalence",
        "answer_type_check",
    }
    assert all(tool["inputSchema"]["type"] == "object" for tool in tools)


def test_direct_and_stdio_mcp_results_are_equal():
    arguments = {"answer": "A", "answer_type": "choice"}
    direct = ToolExecutor().execute("answer_type_check", arguments)
    via_mcp = StdioMCPAdapter().execute("answer_type_check", arguments)
    assert direct.to_dict() == via_mcp.to_dict()


class FailingAdapter:
    def execute(self, name, arguments):
        raise RuntimeError("offline")


def test_mcp_failure_falls_back_to_direct():
    result = ToolExecutor(use_mcp=True, mcp_adapter=FailingAdapter()).execute(
        "answer_type_check",
        {"answer": "2", "answer_type": "integer"},
    )
    assert result.status == "pass"
