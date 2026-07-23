from __future__ import annotations

import json
from pathlib import Path

import pytest

from mathforge.config import HarnessConfig
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
    assert all(
        "type" in property_schema or "anyOf" in property_schema
        for tool in tools
        for property_schema in tool["inputSchema"]["properties"].values()
    )


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


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("safe_parse_expression", {"expression": "x+1"}),
        (
            "symbolic_equivalence",
            {"left": "(x+1)^2", "right": "x^2+2*x+1"},
        ),
        ("simplify_expression", {"expression": "x+x"}),
        (
            "numerical_residual",
            {"left": "x", "right": "x", "samples": [0.0, 1.0]},
        ),
        ("matrix_shape_check", {"matrix": [[1, 2], [3, 4]]}),
        (
            "density_normalization",
            {"expression": "1", "variable": "x", "lower": "0", "upper": "1"},
        ),
        (
            "small_case_enumeration",
            {"expression": "n-n", "variable": "n", "values": [0, 1]},
        ),
        ("latex_syntax_check", {"text": r"\frac{1}{2}"}),
        ("answer_type_check", {"answer": "2", "answer_type": "integer"}),
    ],
)
def test_all_registered_tools_match_direct_and_stdio_mcp(name, arguments):
    direct = ToolExecutor().execute(name, arguments)
    via_mcp = StdioMCPAdapter().execute(name, arguments)
    assert direct.to_dict() == via_mcp.to_dict()


def test_mcp_is_disabled_by_default_in_runtime_and_competition_config():
    root = Path(__file__).resolve().parents[1]
    competition = json.loads(
        (root / "config" / "competition.json").read_text(encoding="utf-8")
    )
    assert HarnessConfig().use_mcp is False
    assert competition["use_mcp"] is False
