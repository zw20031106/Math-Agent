from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from mathforge.config import load_competition_config
from mathforge.harness.trace import TraceBuilder


ROOT = Path(__file__).resolve().parents[1]


def test_competition_keeps_llm_router_and_disables_optional_shadow_path():
    config = load_competition_config()

    assert config.enable_router
    assert not config.enable_shadow
    assert not config.enable_rag
    assert not config.enable_frozen_lemma_store
    assert not config.use_mcp


def test_disabled_optional_components_are_not_imported_by_runtime_startup():
    script = """
import sys
from mathforge.config import load_competition_config
from mathforge.runtime import MathForgeHarness
from tests.fake_client import FakeClient

MathForgeHarness(FakeClient(), load_competition_config())
blocked = {
    'mathforge.retrieval.retriever',
    'mathforge.memory.frozen_lemma_store',
    'mathforge.tools.mcp_adapter',
    'mathforge.tools.shadow_solver',
}
present = sorted(blocked.intersection(sys.modules))
if present:
    raise SystemExit(','.join(present))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_judge_trace_public_module_is_a_small_stable_facade():
    facade = ROOT / "mathforge" / "output" / "judge_trace.py"
    tree = ast.parse(facade.read_text(encoding="utf-8"))

    assert len(facade.read_text(encoding="utf-8").splitlines()) < 500
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        for node in tree.body
    )


def test_zero_internal_trace_limits_defer_to_a_hard_safety_ceiling():
    events: list[dict] = []
    trace = TraceBuilder(events, max_chars=0, max_events=0)

    for index in range(4200):
        trace.add("candidate_generated", candidate_id=f"candidate-{index}")

    assert len(events) <= 4096
    assert events[-1]["candidate_id"] == "candidate-4199"
    with pytest.raises(ValueError, match="nonnegative"):
        TraceBuilder([], max_chars=-1, max_events=0)


def test_online_provider_broad_transport_boundary_is_classified():
    provider = ROOT / "mathforge" / "harness" / "provider.py"
    tree = ast.parse(provider.read_text(encoding="utf-8"))
    broad_handlers = [
        handler
        for node in ast.walk(tree)
        if isinstance(node, ast.Try)
        for handler in node.handlers
        if isinstance(handler.type, ast.Name) and handler.type.id == "Exception"
    ]

    assert len(broad_handlers) == 1
    assert broad_handlers[0].name == "error"
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "classify_transport_failure"
        for node in ast.walk(broad_handlers[0])
    )
